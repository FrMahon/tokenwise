from synth import write_session
from tokenwise.db import connect
from tokenwise.ingest.loader import ingest_dir
from tokenwise.labels import build_labels
from tokenwise.transform import build_layers

BIG = "x" * 16_000  # 4000 tokens


def s(tool, path, result="small"):
    return {"tool": tool, "input": {"file_path": path}, "result": result}


def labels(tmp_path, steps, **kw):
    write_session(tmp_path / "p", "s1", steps)
    con = connect(":memory:")
    ingest_dir(tmp_path, con)
    build_layers(con)
    build_labels(con, **kw)
    return {r[0]: r[1:] for r in con.execute(
        "SELECT step_idx, repeat, bulky_unused, wasted FROM step_labels ORDER BY step_idx").fetchall()}


def test_repeat_read_labeled(tmp_path):
    out = labels(tmp_path, [s("Read", "/a", "same"), s("Read", "/a", "same")])
    assert out[2] == (True, False, True)


def test_first_read_not_repeat(tmp_path):
    assert labels(tmp_path, [s("Read", "/a", "same"), s("Read", "/a", "same")])[1] == (False, False, False)


def test_changed_result_not_repeat(tmp_path):
    out = labels(tmp_path, [s("Read", "/a", "v1"), s("Read", "/a", "v2")])
    assert out[2][0] is False


def test_bulky_without_followup_labeled(tmp_path):
    out = labels(tmp_path, [s("Read", "/a", BIG), s("Read", "/b"), s("Read", "/c")])
    assert out[1] == (False, True, True)


def test_bulky_followed_by_edit_not_labeled(tmp_path):
    out = labels(tmp_path, [s("Read", "/a", BIG), s("Edit", "/a")])
    assert out[1] == (False, False, False)


def test_null_result_not_labeled(tmp_path):
    out = labels(tmp_path, [s("Read", "/a")])
    assert out[1] == (False, False, False)
    # step with no result at all (orphan use) via direct table edit
    write_session(tmp_path / "q", "s2", [s("Read", "/z", BIG)])
    con = connect(":memory:")
    ingest_dir(tmp_path / "q" / "..", con)
    build_layers(con)
    con.execute("UPDATE steps SET result_chars = NULL, result_hash = NULL")
    build_labels(con)
    assert con.execute("SELECT bool_or(wasted) FROM step_labels").fetchone() == (False,)
