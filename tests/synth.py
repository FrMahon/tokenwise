"""Synthetic Claude Code session files in the real on-disk shape (no real data)."""
import json
from pathlib import Path

DEFAULT_USAGE = {
    "input_tokens": 2, "output_tokens": 100,
    "cache_creation_input_tokens": 1000, "cache_read_input_tokens": 5000,
}


def write_session(dir: Path, name: str, steps: list[dict]) -> Path:
    """steps: [{"tool", "input", "result", "model", "usage"}]; returns the .jsonl path."""
    dir = Path(dir)
    dir.mkdir(parents=True, exist_ok=True)
    path = dir / f"{name}.jsonl"
    lines = []
    for i, s in enumerate(steps):
        tid = f"toolu_{name}_{i}"
        ts = f"2026-01-01T00:{i // 60:02d}:{i % 60:02d}.000Z"
        lines.append({
            "type": "assistant", "timestamp": ts, "sessionId": name,
            "message": {
                "role": "assistant", "model": s.get("model", "claude-sonnet-5-5"),
                "usage": s.get("usage", DEFAULT_USAGE),
                "content": [{"type": "text", "text": "SECRET-TEXT"},
                            {"type": "tool_use", "id": tid, "name": s["tool"], "input": s["input"]}],
            },
        })
        lines.append({
            "type": "user", "timestamp": ts, "sessionId": name,
            "message": {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": tid, "content": s["result"], "is_error": False}]},
        })
    path.write_text("\n".join(json.dumps(x) for x in lines) + "\n", encoding="utf-8")
    return path
