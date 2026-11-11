import json

from synth import write_session
from tokenwise.db import connect
from tokenwise.ingest.loader import ingest_dir


def step(i, tool="Read"):
    return {"tool": tool, "input": {"file_path": f"/f{i}"}, "result": "x" * (i + 1)}


def count(con):
    return con.execute("SELECT count(*) FROM raw_events").fetchone()[0]


def test_ingest_twice_no_duplicates(tmp_path):
    write_session(tmp_path / "proj", "s1", [step(0), step(1)])
    con = connect(":memory:")
    first = ingest_dir(tmp_path, con)
    n = count(con)
    second = ingest_dir(tmp_path, con)
    assert first.files == 1 and first.new_rows == n == 6
    assert second.new_rows == 0 and count(con) == n


def test_file_grown_between_runs_adds_only_new_rows(tmp_path):
    p = write_session(tmp_path / "proj", "s1", [step(0)])
    con = connect(":memory:")
    ingest_dir(tmp_path, con)
    before = count(con)
    extra = write_session(tmp_path / "other", "tmp", [step(1)]).read_text()
    with p.open("a", encoding="utf-8") as f:
        f.write(extra)
    stats = ingest_dir(tmp_path, con)
    assert stats.new_rows == 3 and count(con) == before + 3


def test_skipped_lines_counted(tmp_path):
    p = write_session(tmp_path / "proj", "s1", [step(0)])
    with p.open("a", encoding="utf-8") as f:
        f.write("{broken\n" + json.dumps({"type": "mode"}) + "\n")
    stats = ingest_dir(tmp_path, connect(":memory:"))
    assert stats.skipped_lines == 2


def test_non_utf8_bytes_do_not_crash(tmp_path):
    p = write_session(tmp_path / "proj", "s1", [step(0)])
    with p.open("ab") as f:
        f.write(b"\xff\xfe garbage\n")
    con = connect(":memory:")
    stats = ingest_dir(tmp_path, con)
    assert stats.skipped_lines == 1 and count(con) == 3
