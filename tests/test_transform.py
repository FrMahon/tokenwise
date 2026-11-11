import json

from synth import DEFAULT_USAGE, write_session
from tokenwise.db import connect
from tokenwise.ingest.loader import ingest_dir
from tokenwise.transform import build_layers


def step(i, tool="Read", result="abc"):
    return {"tool": tool, "input": {"file_path": f"/f{i}"}, "result": result}


def build(tmp_path, steps, extra_lines=()):
    p = write_session(tmp_path / "proj", "s1", steps)
    if extra_lines:
        with p.open("a", encoding="utf-8") as f:
            f.write("".join(json.dumps(x) + "\n" for x in extra_lines))
    con = connect(":memory:")
    ingest_dir(tmp_path, con)
    build_layers(con)
    return con


def test_steps_join_use_and_result(tmp_path):
    con = build(tmp_path, [step(0, result="x" * 10), step(1, tool="Bash", result="y" * 99)])
    rows = con.execute("SELECT step_idx, tool_name, result_chars FROM steps ORDER BY step_idx").fetchall()
    assert rows == [(1, "Read", 10), (2, "Bash", 99)]


def test_orphan_result_dropped(tmp_path):
    orphan = {"type": "user", "message": {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "nope", "content": "zzz"}]}}
    con = build(tmp_path, [step(0)], [orphan])
    assert con.execute("SELECT count(*) FROM steps").fetchone()[0] == 1


def test_use_without_result_kept_with_null_size(tmp_path):
    lone = {"type": "assistant", "message": {"role": "assistant", "id": "m_lone", "model": "m", "usage": {},
            "content": [{"type": "tool_use", "id": "lone", "name": "Bash", "input": {"command": "ls"}}]}}
    con = build(tmp_path, [step(0)], [lone])
    row = con.execute("SELECT result_chars FROM steps WHERE tool_name = 'Bash'").fetchone()
    assert row == (None,)


def test_turns_remaining_counts_following_turns(tmp_path):
    con = build(tmp_path, [step(0), step(1), step(2)])
    rem = [r[0] for r in con.execute("SELECT turns_remaining FROM steps ORDER BY step_idx").fetchall()]
    assert rem == [2, 1, 0]


def test_totals_match_raw_sum_and_dedupe_repeated_messages(tmp_path):
    dup = {"type": "assistant", "message": {"role": "assistant", "id": "msg_s1_0", "model": "m",
           "usage": DEFAULT_USAGE, "content": [{"type": "text", "text": "again"}]}}
    con = build(tmp_path, [step(0), step(1)], [dup])
    total = con.execute("SELECT sum(cache_read_tokens), count(*) FROM turns").fetchone()
    assert total == (2 * DEFAULT_USAGE["cache_read_input_tokens"], 2)


def test_missing_usage_counts_as_zero(tmp_path):
    no_usage = {"type": "assistant", "message": {"role": "assistant", "id": "m_nu", "model": "m", "content": []}}
    con = build(tmp_path, [step(0)], [no_usage])
    row = con.execute("SELECT output_tokens FROM turns WHERE turn_idx = 2").fetchone()
    assert row == (0,)
