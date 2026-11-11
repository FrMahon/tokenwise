from tokenwise.db import connect

RAW_COLUMNS = {
    "session_id", "project", "line_no", "type", "ts", "message_id", "model",
    "input_tokens", "output_tokens", "cache_write_tokens", "cache_read_tokens",
    "tool_name", "tool_use_id", "input_hash", "result_chars", "result_hash", "is_error",
    "cache_write_5m_tokens",
}


def columns(con, table):
    return {r[0] for r in con.execute(f"DESCRIBE {table}").fetchall()}


def test_connect_creates_tables():
    con = connect(":memory:")
    assert columns(con, "raw_events") == RAW_COLUMNS
    assert columns(con, "ingest_files") == {"path", "size", "lines_read"}
