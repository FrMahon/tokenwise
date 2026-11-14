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
                "role": "assistant", "id": f"msg_{name}_{i}", "model": s.get("model", "claude-sonnet-5-5"),
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


def write_raw(dir: Path, name: str, lines: list[dict]) -> Path:
    """Write the given dicts as one session file (already in the on-disk line shape)."""
    dir = Path(dir)
    dir.mkdir(parents=True, exist_ok=True)
    path = dir / f"{name}.jsonl"
    path.write_text("\n".join(json.dumps(x) for x in lines) + "\n", encoding="utf-8")
    return path


def listing_line(ts: str, entries: dict[str, str]) -> dict:
    content = "\n".join(f"- {name}: {desc}" for name, desc in entries.items())
    return {"type": "attachment", "timestamp": ts, "attachment": {"type": "skill_listing", "content": content}}


def asst_line(ts: str, msg_id: str, model: str = "claude-sonnet-5-5") -> dict:
    return {"type": "assistant", "timestamp": ts,
            "message": {"role": "assistant", "id": msg_id, "model": model, "usage": DEFAULT_USAGE, "content": []}}


def skill_call_line(ts: str, tool_id: str, skill: str) -> dict:
    line = asst_line(ts, f"msg_{tool_id}")
    line["message"]["content"] = [{"type": "tool_use", "id": tool_id, "name": "Skill", "input": {"skill": skill}}]
    return line


def slash_line(ts: str, command: str) -> dict:
    return {"type": "user", "timestamp": ts, "message": {"role": "user", "content":
            f"<command-message>{command.lstrip('/')}</command-message>\n<command-name>{command}</command-name>\n"
            "<command-args></command-args>"}}  # the order Claude Code writes for skills
