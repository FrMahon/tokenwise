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
    root = tmp_path / "sessions"
    p = write_session(root / "proj", "s1", [step(0)])
    con = connect(":memory:")
    ingest_dir(root, con)
    before = count(con)
    extra = write_session(tmp_path / "helper", "tmp", [step(1)]).read_text()
    with p.open("a", encoding="utf-8") as f:
        f.write(extra)
    stats = ingest_dir(root, con)
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


def test_partial_last_line_is_read_once_completed(tmp_path):
    p = write_session(tmp_path / "proj", "s1", [step(0), step(1)])
    full = p.read_text(encoding="utf-8")
    fresh = connect(":memory:")
    ingest_dir(tmp_path, fresh)
    expected = count(fresh)
    p.write_text(full[:-25], encoding="utf-8")  # cut mid-line, as during a live session
    con = connect(":memory:")
    ingest_dir(tmp_path, con)
    assert count(con) < expected
    p.write_text(full, encoding="utf-8")
    ingest_dir(tmp_path, con)
    assert count(con) == expected


def test_same_folder_other_spelling_no_duplicates(tmp_path):
    write_session(tmp_path / "proj", "s1", [step(0), step(1)])
    con = connect(":memory:")
    ingest_dir(tmp_path, con)
    n = count(con)
    ingest_dir(tmp_path / "proj" / "..", con)
    assert count(con) == n


def test_subagent_transcripts_are_ingested(tmp_path):
    write_session(tmp_path / "proj" / "s1" / "subagents", "agent-x", [step(0)])
    con = connect(":memory:")
    stats = ingest_dir(tmp_path, con)
    assert stats.files == 1 and count(con) == 3
    assert con.execute("SELECT DISTINCT project FROM raw_events").fetchall() == [("proj",)]


def test_hostile_line_does_not_abort_ingest(tmp_path):
    p = write_session(tmp_path / "proj", "s1", [step(0)])
    hostile = "[" * 100_000 + "]" * 100_000
    huge = json.dumps({"type": "assistant", "message": {"id": "m", "usage": {"input_tokens": 10 ** 30}}})
    with p.open("a", encoding="utf-8") as f:
        f.write(hostile + chr(10) + huge + chr(10))
    write_session(tmp_path / "proj", "s2", [step(1)])
    con = connect(":memory:")
    stats = ingest_dir(tmp_path, con)
    assert stats.files == 2 and count(con) == 3 + 1 + 3


def test_bulk_insert_keeps_exact_values(tmp_path):
    import json
    from tokenwise.db import connect
    from tokenwise.ingest.loader import ingest_dir
    root = tmp_path / "s"
    root.mkdir()
    big = 2 ** 62 + 1  # float64 would round this
    line = json.dumps({"type": "assistant", "timestamp": "t", "message": {
        "role": "assistant", "id": "m1", "model": "x",
        "usage": {"input_tokens": big, "output_tokens": 0}, "content": [
            {"type": "tool_use", "id": "u1", "name": "Bash", "input": {"command": "ls"}}]}})
    (root / "a.jsonl").write_text(line + "\n", encoding="utf-8")
    con = connect(tmp_path / "t.duckdb")
    ingest_dir(root, con)
    assert con.execute("SELECT input_tokens FROM raw_events WHERE type = 'assistant'").fetchone()[0] == big
    assert con.execute("SELECT cache_read_tokens, is_error FROM raw_events WHERE type = 'assistant'").fetchone() == (None, None)


def test_ingestion_is_not_row_by_row(tmp_path):
    import time
    from synth import write_session
    from tokenwise.db import connect
    from tokenwise.ingest.loader import ingest_dir
    write_session(tmp_path / "s" / "p", "a", [{"tool": "Read", "input": {"file_path": f"/f{i % 9}"}, "result": "x"}
                                              for i in range(2500)])
    con = connect(tmp_path / "t.duckdb")
    t = time.time()
    ingest_dir(tmp_path / "s", con)
    assert time.time() - t < 8  # row-by-row inserts took about 17 s here


def test_ingest_works_with_a_half_read_result_pending(tmp_path):
    from synth import write_session
    from tokenwise.db import connect
    from tokenwise.ingest.loader import ingest_dir
    write_session(tmp_path / "s" / "p", "a", [{"tool": "Read", "input": {"file_path": "/f"}, "result": "x"}])
    con = connect(tmp_path / "t.duckdb")
    con.execute("SELECT * FROM range(10)").fetchone()  # leaves an unfinished result, as a caller might
    assert ingest_dir(tmp_path / "s", con).new_rows > 0


def test_backfill_restores_skill_data_for_already_ingested_files(tmp_path):
    from synth import asst_line, listing_line, skill_call_line, slash_line, write_raw
    from tokenwise.db import connect
    from tokenwise.ingest.loader import ingest_dir
    write_raw(tmp_path / "sess" / "proj", "s1", [
        listing_line("2026-01-05T00:00:00.000Z", {"p:a": "d" * 20}), asst_line("2026-01-05T00:00:01.000Z", "m1"),
        skill_call_line("2026-01-05T00:00:02.000Z", "t1", "p:a"), slash_line("2026-01-05T00:00:03.000Z", "/p:a")])
    con = connect(tmp_path / "t.duckdb")
    ingest_dir(tmp_path / "sess", con)
    def skill_rows():
        return con.execute("SELECT type, skill_name FROM raw_events WHERE skill_name IS NOT NULL ORDER BY line_no").fetchall()
    expected = skill_rows()
    assert [t for t, _ in expected] == ["skill_listed", "tool_use", "skill_used"]
    # simulate a database ingested before skill data existed
    con.execute("DELETE FROM raw_events WHERE type IN ('skill_listed', 'skill_used')")
    con.execute("UPDATE raw_events SET skill_name = NULL")
    con.execute("INSERT INTO skill_backfill SELECT path FROM ingest_files")
    con.execute("INSERT INTO skill_backfill VALUES ('/gone/file.jsonl')")  # a deleted session file must not break it
    before = con.execute("SELECT count(*) FROM raw_events").fetchone()[0]
    ingest_dir(tmp_path / "sess", con)
    assert skill_rows() == expected
    assert con.execute("SELECT count(*) FROM raw_events").fetchone()[0] == before + 2  # no duplicated old rows
    assert con.execute("SELECT count(*) FROM skill_backfill").fetchone()[0] == 0
    ingest_dir(tmp_path / "sess", con)  # a second run changes nothing
    assert skill_rows() == expected
