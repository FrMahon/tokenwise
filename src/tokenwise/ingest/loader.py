"""Incremental, streaming ingestion of session .jsonl files into raw_events."""
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from .parser import COLUMNS, parse_line

BATCH = 5000
MAX_LINE = 32 * 1024 * 1024  # characters; a longer line is skipped instead of being held in memory
NEWLINE = chr(10)


@dataclass
class IngestStats:
    files: int = 0
    new_rows: int = 0
    skipped_lines: int = 0


INT_COLUMNS = frozenset({"line_no", "input_tokens", "output_tokens", "cache_write_tokens", "cache_read_tokens",
                         "result_chars", "cache_write_5m_tokens"})


def _text(v):
    return v if v is None or isinstance(v, str) else str(v)


def _flush(con, rows):
    """Insert a batch in one bulk statement (row-by-row inserts are ~1000x slower in DuckDB)."""
    if not rows:
        return
    data = {}
    for c in COLUMNS:
        col = [r[c] for r in rows]
        if c in INT_COLUMNS:
            data[c] = pd.array(col, dtype="Int64")  # nullable, exact for the full 64-bit range
        elif c == "is_error":
            data[c] = pd.array(col, dtype="boolean")
        else:
            data[c] = pd.Series([_text(v) for v in col], dtype=object)
    batch = pd.DataFrame(data)
    cols = ", ".join(COLUMNS)
    cur = con.cursor()  # own cursor: unaffected by any half-read result on the caller's connection
    try:
        cur.register("_batch", batch)
        # column names are constants from the parser, never user input; the values come from the registered frame
        cur.execute(f"INSERT INTO raw_events ({cols}) SELECT {cols} FROM _batch")  # nosec B608
    finally:
        cur.close()
    rows.clear()


def _discard_rest(f) -> bool:
    """Drop the rest of an oversized line in bounded chunks. False if the file ended before its newline."""
    while True:
        chunk = f.readline(MAX_LINE)
        if not chunk:
            return False
        if chunk.endswith(NEWLINE):
            return True


def _identity(root: Path, path: Path) -> tuple[str, str]:
    """(project, session_id) from the path under the sessions folder; subagent files nest deeper."""
    parts = path.relative_to(root).with_suffix("").parts
    if len(parts) == 1:
        return "", parts[0]
    return parts[0], "/".join(parts[1:])


def _backfill_skills(root: Path, con) -> None:
    """Fill in skill data for files ingested before it existed: re-read only the lines already ingested and
    add the skill rows (and the skill name on Skill tool calls), leaving everything else as it is."""
    queued = [r[0] for r in con.execute("SELECT path FROM skill_backfill").fetchall()]
    for key in queued:
        path = Path(key)
        seen = con.execute("SELECT lines_read FROM ingest_files WHERE path = ?", [key]).fetchall()
        if path.is_file() and seen:
            try:
                project, session_id = _identity(root.resolve(), path)
            except ValueError:
                continue  # belongs to another sessions folder: keep it queued for a run that uses that one
            rows: list[dict] = []
            names: list[tuple[str, str, str]] = []
            with path.open("r", encoding="utf-8", errors="replace", newline="") as f:
                line_no = 0
                while line_no < seen[0][0]:
                    line = f.readline(MAX_LINE)
                    if not line:
                        break
                    if not line.endswith(NEWLINE):
                        if len(line) < MAX_LINE or not _discard_rest(f):
                            break
                        line_no += 1
                        continue
                    line_no += 1
                    for r in parse_line(line, session_id, project, line_no):
                        if r["type"] in ("skill_listed", "skill_used"):
                            rows.append(r)
                        elif r["type"] == "tool_use" and r["skill_name"] and r["tool_use_id"]:
                            names.append((r["skill_name"], session_id, r["tool_use_id"]))
                    if len(rows) >= BATCH:
                        _flush(con, rows)
            _flush(con, rows)
            if names:
                con.executemany("UPDATE raw_events SET skill_name = ? WHERE session_id = ? AND tool_use_id = ? "
                                "AND type = 'tool_use'", names)
        con.execute("DELETE FROM skill_backfill WHERE path = ?", [key])


def ingest_dir(sessions_dir: Path, con) -> IngestStats:
    root = Path(sessions_dir)
    _backfill_skills(root, con)
    stats = IngestStats()
    for path in sorted(root.rglob("*.jsonl")):
        key = str(path.resolve())
        size = path.stat().st_size
        found = con.execute("SELECT size, lines_read FROM ingest_files WHERE path = ?", [key]).fetchall()
        seen = found[0] if found else None  # fetchall: leave no half-read result on the connection
        if seen and seen[0] == size:
            continue
        start = seen[1] if seen else 0
        project, session_id = _identity(root, path)
        stats.files += 1
        rows: list[dict] = []
        complete = start
        with path.open("r", encoding="utf-8", errors="replace", newline="") as f:
            line_no = 0
            while True:
                line = f.readline(MAX_LINE)
                if not line:
                    break
                if not line.endswith(NEWLINE):
                    if len(line) < MAX_LINE or not _discard_rest(f):
                        break  # half-written last line: leave it for the next run
                    line_no += 1  # oversized line, now fully skipped
                    complete = line_no
                    if line_no > start:
                        stats.skipped_lines += 1
                    continue
                line_no += 1
                complete = line_no
                if line_no <= start:
                    continue
                parsed = parse_line(line, session_id, project, line_no)
                if parsed:
                    rows.extend(parsed)
                    stats.new_rows += len(parsed)
                else:
                    stats.skipped_lines += 1
                if len(rows) >= BATCH:
                    _flush(con, rows)
        _flush(con, rows)
        con.execute("DELETE FROM ingest_files WHERE path = ?", [key])
        con.execute("INSERT INTO ingest_files VALUES (?, ?, ?)", [key, size, complete])
    return stats
