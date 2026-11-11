"""Incremental, streaming ingestion of session .jsonl files into raw_events."""
from dataclasses import dataclass
from pathlib import Path

from .parser import COLUMNS, parse_line

BATCH = 5000
MAX_LINE = 32 * 1024 * 1024  # characters; a longer line is skipped instead of being held in memory
NEWLINE = chr(10)


@dataclass
class IngestStats:
    files: int = 0
    new_rows: int = 0
    skipped_lines: int = 0


def _flush(con, rows):
    if rows:
        placeholders = ",".join("?" * len(COLUMNS))
        # placeholders only: "?" repeated; every value is bound as a parameter
        con.executemany(f"INSERT INTO raw_events VALUES ({placeholders})",  # nosec B608
                        [[r[c] for c in COLUMNS] for r in rows])
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


def ingest_dir(sessions_dir: Path, con) -> IngestStats:
    root = Path(sessions_dir)
    stats = IngestStats()
    for path in sorted(root.rglob("*.jsonl")):
        key = str(path.resolve())
        size = path.stat().st_size
        seen = con.execute("SELECT size, lines_read FROM ingest_files WHERE path = ?", [key]).fetchone()
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
