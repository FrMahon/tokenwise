from tokenwise.db import connect

RAW_COLUMNS = {
    "session_id", "project", "line_no", "type", "ts", "message_id", "model",
    "input_tokens", "output_tokens", "cache_write_tokens", "cache_read_tokens",
    "tool_name", "tool_use_id", "input_hash", "result_chars", "result_hash", "is_error",
    "cache_write_5m_tokens", "skill_name",
}


def columns(con, table):
    return {r[0] for r in con.execute(f"DESCRIBE {table}").fetchall()}


def test_connect_creates_tables():
    con = connect(":memory:")
    assert columns(con, "raw_events") == RAW_COLUMNS
    assert columns(con, "ingest_files") == {"path", "size", "lines_read"}


def test_new_database_has_skill_name_column(tmp_path):
    con = connect(tmp_path / "n.duckdb")
    assert "skill_name" in {r[0] for r in con.execute("DESCRIBE raw_events").fetchall()}


def test_old_database_gains_skill_name(tmp_path):
    import duckdb
    old = duckdb.connect(str(tmp_path / "o.duckdb"))
    old.execute("""CREATE TABLE raw_events (
        session_id VARCHAR, project VARCHAR, line_no BIGINT, type VARCHAR, ts VARCHAR, message_id VARCHAR,
        model VARCHAR, input_tokens BIGINT, output_tokens BIGINT, cache_write_tokens BIGINT,
        cache_read_tokens BIGINT, tool_name VARCHAR, tool_use_id VARCHAR, input_hash VARCHAR,
        result_chars BIGINT, result_hash VARCHAR, is_error BOOLEAN, cache_write_5m_tokens BIGINT)""")
    old.execute("INSERT INTO raw_events (session_id, type) VALUES ('s', 'assistant')")
    old.close()
    con = connect(tmp_path / "o.duckdb")
    assert "skill_name" in {r[0] for r in con.execute("DESCRIBE raw_events").fetchall()}
    assert con.execute("SELECT count(*) FROM raw_events").fetchone()[0] == 1


def test_migration_queues_existing_files_for_skill_backfill(tmp_path):
    import duckdb
    old = duckdb.connect(str(tmp_path / "o.duckdb"))
    old.execute("""CREATE TABLE raw_events (
        session_id VARCHAR, project VARCHAR, line_no BIGINT, type VARCHAR, ts VARCHAR, message_id VARCHAR,
        model VARCHAR, input_tokens BIGINT, output_tokens BIGINT, cache_write_tokens BIGINT,
        cache_read_tokens BIGINT, tool_name VARCHAR, tool_use_id VARCHAR, input_hash VARCHAR,
        result_chars BIGINT, result_hash VARCHAR, is_error BOOLEAN, cache_write_5m_tokens BIGINT)""")
    old.execute("CREATE TABLE ingest_files (path VARCHAR PRIMARY KEY, size BIGINT, lines_read BIGINT)")
    old.execute("INSERT INTO ingest_files VALUES ('/a.jsonl', 10, 3)")
    old.close()
    con = connect(tmp_path / "o.duckdb")
    assert con.execute("SELECT path FROM skill_backfill").fetchall() == [("/a.jsonl",)]
    assert connect(tmp_path / "o.duckdb").execute("SELECT count(*) FROM skill_backfill").fetchone()[0] == 1  # not re-queued
    assert connect(tmp_path / "fresh.duckdb").execute("SELECT count(*) FROM skill_backfill").fetchone()[0] == 0
