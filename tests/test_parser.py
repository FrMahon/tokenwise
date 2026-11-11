import json

from tokenwise.ingest.parser import parse_line


def asst(usage=None, content=None, **extra):
    msg = {"role": "assistant", "model": "claude-sonnet-5-5", "content": content or []}
    if usage is not None:
        msg["usage"] = usage
    return json.dumps({"type": "assistant", "timestamp": "t1", "message": msg, **extra})


def parse(line):
    return parse_line(line, "s1", "proj", 7)


def test_assistant_usage_extracted():
    rows = parse(asst({"input_tokens": 2, "output_tokens": 286,
                       "cache_creation_input_tokens": 55546, "cache_read_input_tokens": 0}))
    assert len(rows) == 1
    r = rows[0]
    assert (r["type"], r["input_tokens"], r["cache_write_tokens"], r["cache_read_tokens"],
            r["output_tokens"], r["model"]) == ("assistant", 2, 55546, 0, 286, "claude-sonnet-5-5")
    assert (r["session_id"], r["project"], r["line_no"]) == ("s1", "proj", 7)


def test_tool_use_hashes_input_not_text():
    line = asst({"input_tokens": 1}, [{"type": "tool_use", "id": "u1", "name": "Bash",
                                       "input": {"command": "echo hunter2"}}])
    rows = parse(line)
    tu = [r for r in rows if r["type"] == "tool_use"][0]
    assert tu["tool_name"] == "Bash" and tu["tool_use_id"] == "u1"
    assert len(tu["input_hash"]) == 40 and "hunter2" not in json.dumps(rows)


def test_path_inputs_share_hash():
    def h(tool, inp):
        rows = parse(asst({}, [{"type": "tool_use", "id": "x", "name": tool, "input": inp}]))
        return [r for r in rows if r["type"] == "tool_use"][0]["input_hash"]
    assert h("Read", {"file_path": "/a/b.py"}) == h("Edit", {"file_path": "/a/b.py", "old_string": "x"})
    assert h("Read", {"file_path": "/a/b.py"}) != h("Read", {"file_path": "/a/c.py"})


def test_tool_result_stores_size_and_hash_only():
    line = json.dumps({"type": "user", "message": {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "u1", "content": "top secret output", "is_error": True}]}})
    rows = parse(line)
    assert len(rows) == 1
    r = rows[0]
    assert (r["type"], r["tool_use_id"], r["result_chars"], r["is_error"]) == ("tool_result", "u1", 17, True)
    assert len(r["result_hash"]) == 40 and "secret" not in json.dumps(r)


def test_tool_result_with_block_list_content():
    line = json.dumps({"type": "user", "message": {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "u1",
         "content": [{"type": "text", "text": "abc"}, {"type": "text", "text": "de"}]}]}})
    assert parse(line)[0]["result_chars"] == 5


def test_malformed_json_returns_empty():
    assert parse("{not json") == []


def test_truncated_last_line_returns_empty():
    assert parse(asst({"input_tokens": 1})[:-10]) == []


def test_unknown_type_returns_empty():
    assert parse(json.dumps({"type": "file-history-snapshot", "snapshot": {}})) == []
    assert parse(json.dumps(["not", "a", "dict"])) == []


def test_missing_usage_gives_null_tokens():
    r = parse(asst(None))[0]
    assert r["input_tokens"] is None and r["cache_read_tokens"] is None
