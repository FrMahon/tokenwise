from synth import write_session
from tokenwise.cli import main


def make_sessions(root, model="claude-sonnet-5-5", n=6):
    for i in range(n):
        steps = []
        for j in range(20):
            steps.append({"tool": "Read", "input": {"file_path": f"/f{j % 4}"}, "result": "x" * 40_000, "model": model})
        write_session(root / "proj", f"s{i}", steps)


def run(tmp_path, capsys, *extra):
    code = main(["report", "--sessions-dir", str(tmp_path / "sess"), "--db", str(tmp_path / "t.duckdb"), *extra])
    out = capsys.readouterr()
    return code, out.out, out.err


def test_report_end_to_end_on_synthetic_sessions(tmp_path, capsys):
    make_sessions(tmp_path / "sess")
    code, out, _ = run(tmp_path, capsys)
    assert code == 0
    assert "Sessions analyzed: 6" in out
    assert "Estimated spend:" in out and "Avoidable:" in out
    assert "Top leaks" in out and "repeat" in out
    assert "Model:" in out


def test_missing_sessions_dir_exits_1_with_message(tmp_path, capsys):
    code, out, err = run(tmp_path, capsys)
    assert code == 1 and "not found" in err and "Traceback" not in err


def test_empty_sessions_dir_exits_1_with_message(tmp_path, capsys):
    (tmp_path / "sess").mkdir()
    code, out, err = run(tmp_path, capsys)
    assert code == 1 and "No sessions" in err


def test_unknown_model_warning_shown(tmp_path, capsys):
    make_sessions(tmp_path / "sess", model="mystery-model")
    code, out, _ = run(tmp_path, capsys)
    assert code == 0 and "no price" in out and "mystery-model" in out
