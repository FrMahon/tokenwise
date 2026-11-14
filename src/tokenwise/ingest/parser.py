"""Tolerant parser: one session line -> zero or more raw_events rows.

Only sizes, token counts and sha1 hashes are kept; conversation text is dropped.
"""
import hashlib
import json
import re

COLUMNS = (
    "session_id", "project", "line_no", "type", "ts", "message_id", "model",
    "input_tokens", "output_tokens", "cache_write_tokens", "cache_read_tokens",
    "tool_name", "tool_use_id", "input_hash", "result_chars", "result_hash", "is_error",
    "cache_write_5m_tokens",  # databases created before it gained the column at the end
    "skill_name",  # keep last: same reason
)


def _sha1(text: str) -> str:
    # Content fingerprint only (never used for security), hence usedforsecurity=False.
    return hashlib.sha1(text.encode("utf-8", errors="replace"), usedforsecurity=False).hexdigest()


def _input_hash(inp) -> str:
    # Inputs that point at a path hash the path alone, so Read/Edit/Write of the same file match.
    if isinstance(inp, dict):
        for key in ("file_path", "path", "notebook_path"):
            if isinstance(inp.get(key), str):
                return _sha1(inp[key])
    try:
        return _sha1(json.dumps(inp, sort_keys=True, default=str))
    except (ValueError, TypeError, RecursionError):
        return _sha1("<unhashable input>")


def _result_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(b.get("text", "") for b in content if isinstance(b, dict) and isinstance(b.get("text"), str))
    return ""


INT64_MIN, INT64_MAX = -(2 ** 63), 2 ** 63 - 1


def _int(v):
    ok = isinstance(v, int) and not isinstance(v, bool) and INT64_MIN <= v <= INT64_MAX
    return v if ok else None


def _row(base: dict, **fields) -> dict:
    row = {c: None for c in COLUMNS}
    row.update(base)
    row.update(fields)
    return row


_ENTRY_START = re.compile(r"^- (\S+): ", re.MULTILINE)
_COMMAND = re.compile(r"<command-name>/?([^<\s]+)</command-name>")


def split_listing(content: str) -> dict[str, int]:
    """Skill name -> length of its `name: description` entry in a skill listing (text itself is not kept)."""
    starts = list(_ENTRY_START.finditer(content))
    out: dict[str, int] = {}
    for i, m in enumerate(starts):
        end = starts[i + 1].start() if i + 1 < len(starts) else len(content)
        entry = content[m.start() + 2:end].rstrip("\n")  # skip the leading "- "
        out[m.group(1)] = len(entry)
    return out


def _user_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(b["text"] for b in content
                       if isinstance(b, dict) and b.get("type") == "text" and isinstance(b.get("text"), str))
    return ""


def parse_line(line: str, session_id: str, project: str, line_no: int) -> list[dict]:
    try:
        d = json.loads(line)
    except (ValueError, TypeError, RecursionError):  # malformed, or nested deeper than Python allows
        return []
    if not isinstance(d, dict):
        return []
    base = {"session_id": session_id, "project": project, "line_no": line_no, "ts": d.get("timestamp")}
    # Compaction: the context restarts from a summary, so earlier tool results are not re-read after it.
    if (d.get("type") == "system" and d.get("subtype") == "compact_boundary") or d.get("isCompactSummary") is True:
        return [_row(base, type="compact")]
    att = d.get("attachment")
    if d.get("type") == "attachment" and isinstance(att, dict) and att.get("type") == "skill_listing":
        text = att.get("content")
        entries = split_listing(text) if isinstance(text, str) else {}
        return [_row(base, type="skill_listed", skill_name=n, result_chars=c) for n, c in entries.items()]
    msg = d.get("message")
    if not isinstance(msg, dict):
        return []
    content = msg.get("content") if isinstance(msg.get("content"), list) else []
    rows: list[dict] = []

    if d.get("type") == "assistant":
        usage = msg.get("usage") if isinstance(msg.get("usage"), dict) else {}
        created = usage.get("cache_creation") if isinstance(usage.get("cache_creation"), dict) else {}
        rows.append(_row(
            base, type="assistant", model=msg.get("model"), message_id=msg.get("id"),
            input_tokens=_int(usage.get("input_tokens")),
            output_tokens=_int(usage.get("output_tokens")),
            cache_write_tokens=_int(usage.get("cache_creation_input_tokens")),
            cache_read_tokens=_int(usage.get("cache_read_input_tokens")),
            cache_write_5m_tokens=_int(created.get("ephemeral_5m_input_tokens")),
        ))
        for b in content:
            if isinstance(b, dict) and b.get("type") == "tool_use":
                inp = b.get("input")
                skill = inp.get("skill") if b.get("name") == "Skill" and isinstance(inp, dict) else None
                rows.append(_row(base, type="tool_use", model=msg.get("model"),
                                 tool_name=b.get("name"), tool_use_id=b.get("id"),
                                 input_hash=_input_hash(inp),
                                 skill_name=skill if isinstance(skill, str) else None))
    elif d.get("type") == "user":
        text = _user_text(msg.get("content"))
        cmd = _COMMAND.match(text.lstrip())  # match anchors at the start: only a message that opens with a command
        if cmd:
            rows.append(_row(base, type="skill_used", skill_name=cmd.group(1)))
        for b in content:
            if isinstance(b, dict) and b.get("type") == "tool_result":
                text = _result_text(b.get("content"))
                rows.append(_row(base, type="tool_result", tool_use_id=b.get("tool_use_id"),
                                 result_chars=len(text), result_hash=_sha1(text),
                                 is_error=bool(b.get("is_error"))))
    return rows
