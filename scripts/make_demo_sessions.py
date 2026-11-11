"""Generate synthetic Claude Code sessions for demos and screenshots (no real data)."""
import argparse
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tests"))
from synth import write_session  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("out", type=Path)
    ap.add_argument("--sessions", type=int, default=40)
    ap.add_argument("--steps", type=int, default=60)
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args()
    rng = random.Random(a.seed)
    for s in range(a.sessions):
        project = f"demo-project-{s % 4}"
        files = [f"/src/module_{i}.py" for i in range(8)]
        model = rng.choice(["claude-opus-5-5", "claude-sonnet-5-5", "claude-sonnet-5-5"])
        steps = []
        for i in range(a.steps):
            r = rng.random()
            if r < 0.55:
                f = rng.choice(files)
                tool, inp, res = "Read", {"file_path": f}, f * rng.choice([60, 200, 500])
            elif r < 0.60:
                tool, inp, res = "Bash", {"command": f"pytest -k case_{s}_{i}"}, "log line " * rng.randint(4000, 9000)
            elif r < 0.80:
                tool, inp, res = "Edit", {"file_path": rng.choice(files)}, "ok"
            elif r < 0.95:
                tool, inp, res = "Grep", {"pattern": f"symbol_{i}"}, "match " * rng.randint(5, 200)
            else:
                tool, inp, res = "Bash", {"command": f"ls dir_{i}"}, "a b c"
            steps.append({"tool": tool, "input": inp, "result": res, "model": model, "usage": {
                "input_tokens": 3, "output_tokens": rng.randint(200, 1500),
                "cache_creation_input_tokens": rng.randint(2000, 8000),
                "cache_read_input_tokens": rng.randint(30000, 120000)}})
        write_session(a.out / project, f"session-{s:03d}", steps)


if __name__ == "__main__":
    main()
