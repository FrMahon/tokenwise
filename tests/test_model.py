import numpy as np
import pandas as pd

from synth import write_session
from tokenwise import model as M
from tokenwise.db import connect
from tokenwise.features import FEATURES, build_features
from tokenwise.ingest.loader import ingest_dir
from tokenwise.labels import build_labels
from tokenwise.transform import build_layers


def planted(n_sessions=60, per=50, seed=0):
    """Re-reading an already-seen input is always waste; everything else never is."""
    rng = np.random.default_rng(seed)
    rows = []
    for s in range(n_sessions):
        for i in range(per):
            seen = bool(rng.random() < 0.3)
            rows.append({
                "session_id": f"s{s:03d}", "step_idx": i + 1, "ts": f"2026-01-{1 + s // 2:02d}T00:00:00Z",
                "tool_name": rng.choice(["Read", "Bash", "Grep"]), "model": "claude-sonnet-5-5",
                "steps_since_same_tool": int(rng.integers(0, 20)), "same_input_seen_before": seen,
                "prev_tool_name": rng.choice(["Read", "Bash", "Grep", "none"]),
                "hour": int(rng.integers(0, 24)), "wasted": seen,
            })
    return pd.DataFrame(rows)


def test_features_exclude_result_columns(tmp_path):
    for banned in ("result_chars", "result_hash", "turns_remaining", "wasted"):
        assert banned not in FEATURES
    write_session(tmp_path / "p", "s1", [
        {"tool": "Read", "input": {"file_path": "/a"}, "result": "r"} for _ in range(3)])
    con = connect(":memory:")
    ingest_dir(tmp_path, con)
    build_layers(con)
    build_labels(con)
    df = build_features(con)
    assert set(FEATURES) | {"session_id", "step_idx", "ts", "wasted"} <= set(df.columns)
    assert df.sort_values("step_idx")["same_input_seen_before"].tolist() == [False, True, True]


def test_split_is_temporal():
    train, val = M.temporal_split(planted())
    assert train.groupby("session_id").ts.min().max() <= val.groupby("session_id").ts.min().min()
    assert set(train.session_id).isdisjoint(val.session_id)


def test_enough_steps_trains_personal():
    res = M.train(planted(), min_steps=1000)
    assert res.source == "personal"


def test_model_learns_planted_pattern():
    res = M.train(planted(), min_steps=1000)
    assert res.metrics["roc_auc"] > 0.8
    assert res.metrics["precision_at_threshold"] > 0.8


def test_few_steps_uses_baseline(monkeypatch):
    pipe = M.fit(planted())
    monkeypatch.setattr(M, "load_baseline", lambda: pipe)
    small = planted(n_sessions=4, per=10)
    res = M.train(small, min_steps=2000)
    assert res.source == "baseline" and res.model is pipe


def test_save_load_roundtrip(tmp_path):
    df = planted()
    res = M.train(df, min_steps=1000)
    M.save(res, tmp_path / "m.joblib")
    again = M.load(tmp_path / "m.joblib")
    assert np.allclose(M.predict_proba(res, df), M.predict_proba(again, df))


def test_bundled_baseline_loads_and_predicts():
    pipe = M.load_baseline()
    assert pipe is not None
    probs = M.predict_proba(M.TrainResult(pipe, {}, "baseline"), planted(n_sessions=2, per=5))
    assert len(probs) == 10 and ((probs >= 0) & (probs <= 1)).all()


def test_unreadable_baseline_returns_none(monkeypatch):
    def boom(*a, **k):
        raise ModuleNotFoundError("numpy._core")
    monkeypatch.setattr(M, "_safe_load", boom)
    assert M.load_baseline() is None


def test_nonstandard_tools_are_bucketed_as_other(tmp_path):
    write_session(tmp_path / "p", "s1", [
        {"tool": "mcp__some_server__do_thing", "input": {"x": 1}, "result": "r"},
        {"tool": "Read", "input": {"file_path": "/a"}, "result": "r"},
    ])
    con = connect(":memory:")
    ingest_dir(tmp_path, con)
    build_layers(con)
    build_labels(con)
    df = build_features(con).sort_values("step_idx")
    assert df["tool_name"].tolist() == ["other", "Read"]
    assert df["prev_tool_name"].tolist() == ["none", "other"]


def test_models_are_never_loaded_with_pickle():
    import pathlib
    src = pathlib.Path(__file__).resolve().parent.parent / "src" / "tokenwise"
    for f in src.rglob("*.py"):
        text = f.read_text(encoding="utf-8")
        assert "import pickle" not in text and "joblib.load" not in text, f


def test_load_refuses_unexpected_types(tmp_path):
    import skops.io as sio

    class Sneaky:
        pass

    path = tmp_path / "evil.skops"
    sio.dump({"model": Sneaky(), "metrics": {}, "source": "personal"}, path)
    try:
        M.load(path)
    except ValueError as e:
        assert "refusing" in str(e)
    else:
        raise AssertionError("an unexpected type was loaded")
