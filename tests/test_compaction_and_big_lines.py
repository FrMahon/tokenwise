import json

from synth import write_session
from tokenwise.db import connect
from tokenwise.ingest import loader
from tokenwise.ingest.loader import ingest_dir
from tokenwise.ingest.parser import parse_line
from tokenwise.transform import build_layers


def steps(n):
    return [{"tool": "Read", "input": {"file_path": f"/f{i}"}, "result": "x" * 100} for i in range(n)]


def test_parser_marks_compaction_lines():
    boundary = json.dumps({"type": "system", "subtype": "compact_boundary", "timestamp": "t",
                           "content": "Conversation compacted"})
    summary = json.dumps({"type": "user", "isCompactSummary": True, "timestamp": "t",
                          "message": {"role": "user", "content": "SECRET summary text"}})
    for line in (boundary, summary):
        rows = parse_line(line, "s", "p", 3)
        assert [r["type"] for r in rows] == ["compact"] and rows[0]["line_no"] == 3
        assert "SECRET" not in str(rows)
    other = json.dumps({"type": "system", "subtype": "informational", "timestamp": "t"})
    assert parse_line(other, "s", "p", 1) == []


def insert_after(path, n_lines, extra):
    lines = path.read_text(encoding="utf-8").splitlines()
    lines[n_lines:n_lines] = [json.dumps(x) for x in extra]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def remaining(root, tmp_path):
    con = connect(tmp_path / "t.duckdb")
    ingest_dir(root, con)
    build_layers(con)
    return [r[0] for r in con.execute("SELECT turns_remaining FROM steps ORDER BY step_idx").fetchall()]


def test_turns_remaining_stops_at_a_compaction(tmp_path):
    root = tmp_path / "sess"
    path = write_session(root / "proj", "a", steps(4))
    assert remaining(root, tmp_path) == [3, 2, 1, 0]
    (tmp_path / "t.duckdb").unlink()
    insert_after(path, 4, [{"type": "system", "subtype": "compact_boundary", "timestamp": "t"}])  # after step 1
    assert remaining(root, tmp_path) == [1, 0, 1, 0]


def test_oversized_line_is_skipped_without_losing_neighbours(tmp_path, monkeypatch):
    monkeypatch.setattr(loader, "MAX_LINE", 3000)
    root = tmp_path / "sess"
    path = write_session(root / "proj", "a", steps(2))
    lines = path.read_text(encoding="utf-8").splitlines()
    lines.insert(2, json.dumps({"type": "user", "message": {"role": "user", "content": "y" * 10_000}}))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    con = connect(tmp_path / "t.duckdb")
    stats = ingest_dir(root, con)
    assert stats.skipped_lines == 1
    assert con.execute("SELECT count(*) FROM raw_events WHERE type = 'tool_use'").fetchone()[0] == 2
    assert con.execute("SELECT count(*) FROM raw_events WHERE type = 'tool_result'").fetchone()[0] == 2
    again = ingest_dir(root, con)
    assert again.new_rows == 0 and again.skipped_lines == 0


def test_oversized_unfinished_last_line_waits_for_the_next_run(tmp_path, monkeypatch):
    monkeypatch.setattr(loader, "MAX_LINE", 3000)
    root = tmp_path / "sess"
    path = write_session(root / "proj", "a", steps(1))
    with path.open("a", encoding="utf-8") as f:
        f.write("z" * 10_000)  # still being written, no newline yet
    con = connect(tmp_path / "t.duckdb")
    stats = ingest_dir(root, con)
    assert stats.skipped_lines == 0
    assert con.execute("SELECT lines_read FROM ingest_files").fetchone()[0] == 2
