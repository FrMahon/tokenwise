import json
import shutil

import pytest

from synth import write_session
from tokenwise.db import connect
from tokenwise.ingest.loader import ingest_dir
from tokenwise.ingest.parser import parse_line
from tokenwise.pricing import ModelPrice, blended_step_price, step_cost, turn_cost
from tokenwise.transform import build_layers

P = ModelPrice(input=3.0, output=15.0, cache_write=6.0, cache_read=0.3)


def steps(n=3):
    return [{"tool": "Read", "input": {"file_path": f"/f{i}"}, "result": "x" * 100} for i in range(n)]


def layers(root, tmp_path):
    con = connect(tmp_path / "t.duckdb")
    ingest_dir(root, con)
    build_layers(con)
    return con


def test_resumed_session_copy_is_not_double_counted(tmp_path):
    root = tmp_path / "sess"
    a = write_session(root / "proj", "a", steps())
    shutil.copy(a, root / "proj" / "b.jsonl")  # a resumed session replays the old history
    con = layers(root, tmp_path)
    assert con.execute("SELECT count(*) FROM turns").fetchone()[0] == 3
    assert con.execute("SELECT count(*) FROM steps").fetchone()[0] == 3
    assert con.execute("SELECT count(DISTINCT session_id) FROM turns").fetchone()[0] == 1


def test_new_work_in_the_resumed_session_is_kept(tmp_path):
    root = tmp_path / "sess"
    a = write_session(root / "proj", "a", steps(2))
    b = write_session(root / "proj", "b", steps(2))
    # b = a's history followed by its own two steps
    (root / "proj" / "b.jsonl").write_text(a.read_text(encoding="utf-8") + b.read_text(encoding="utf-8"),
                                           encoding="utf-8")
    con = layers(root, tmp_path)
    assert con.execute("SELECT count(*) FROM turns").fetchone()[0] == 4
    assert con.execute("SELECT count(*) FROM steps WHERE session_id = 'b'").fetchone()[0] == 2


def usage_line(cc=None):
    usage = {"input_tokens": 1, "output_tokens": 1, "cache_creation_input_tokens": 1000,
             "cache_read_input_tokens": 0}
    if cc is not None:
        usage["cache_creation"] = cc
    return json.dumps({"type": "assistant", "timestamp": "t", "message": {"role": "assistant", "model": "m",
                                                                          "usage": usage, "content": []}})


def test_parser_reads_5_minute_cache_writes():
    r = parse_line(usage_line({"ephemeral_5m_input_tokens": 400, "ephemeral_1h_input_tokens": 600}), "s", "p", 1)[0]
    assert r["cache_write_5m_tokens"] == 400
    assert parse_line(usage_line(), "s", "p", 1)[0]["cache_write_5m_tokens"] is None


def test_turn_cost_bills_5_minute_writes_at_the_cheaper_rate():
    turn = {"input_tokens": 0, "output_tokens": 0, "cache_write_tokens": 1_000_000,
            "cache_write_5m_tokens": 1_000_000, "cache_read_tokens": 0}
    assert turn_cost(P, turn) == pytest.approx(3.0 * 1.25)           # default 5m rate: 1.25 x input
    assert turn_cost(ModelPrice(3.0, 15.0, 6.0, 0.3, cache_write_5m=3.5), turn) == pytest.approx(3.5)
    half = dict(turn, cache_write_5m_tokens=500_000)
    assert turn_cost(P, half) == pytest.approx(0.5 * 3.75 + 0.5 * 6.0)
    assert turn_cost(P, dict(turn, cache_write_5m_tokens=0)) == pytest.approx(6.0)  # old rows: all 1-hour
    assert turn_cost(P, {k: v for k, v in turn.items() if k != "cache_write_5m_tokens"}) == pytest.approx(6.0)


def test_step_price_blends_by_the_share_of_5_minute_writes():
    assert blended_step_price(P, 0.0).cache_write == pytest.approx(6.0)
    assert blended_step_price(P, 1.0).cache_write == pytest.approx(3.75)
    assert blended_step_price(P, 0.5).cache_write == pytest.approx(4.875)
    assert step_cost(blended_step_price(P, 1.0), 1_000_000, 0) == pytest.approx(3.75)


def test_old_database_gets_the_new_column(tmp_path):
    import duckdb
    path = tmp_path / "old.duckdb"
    old = duckdb.connect(str(path))
    old.execute("CREATE TABLE raw_events (session_id VARCHAR, project VARCHAR, line_no BIGINT, type VARCHAR, "
                "ts VARCHAR, message_id VARCHAR, model VARCHAR, input_tokens BIGINT, output_tokens BIGINT, "
                "cache_write_tokens BIGINT, cache_read_tokens BIGINT, tool_name VARCHAR, tool_use_id VARCHAR, "
                "input_hash VARCHAR, result_chars BIGINT, result_hash VARCHAR, is_error BOOLEAN)")
    old.execute("INSERT INTO raw_events (session_id, type) VALUES ('keep', 'assistant')")
    old.close()
    con = connect(path)
    cols = [r[0] for r in con.execute("DESCRIBE raw_events").fetchall()]
    assert cols[-1] == "cache_write_5m_tokens"
    assert con.execute("SELECT count(*) FROM raw_events").fetchone()[0] == 1  # history is kept
