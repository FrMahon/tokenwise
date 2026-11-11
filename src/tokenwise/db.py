from pathlib import Path

import duckdb

SCHEMA = """
CREATE TABLE IF NOT EXISTS raw_events (
    session_id VARCHAR, project VARCHAR, line_no BIGINT, type VARCHAR, ts VARCHAR, message_id VARCHAR,
    model VARCHAR, input_tokens BIGINT, output_tokens BIGINT,
    cache_write_tokens BIGINT, cache_read_tokens BIGINT,
    tool_name VARCHAR, tool_use_id VARCHAR, input_hash VARCHAR,
    result_chars BIGINT, result_hash VARCHAR, is_error BOOLEAN, cache_write_5m_tokens BIGINT
);
CREATE TABLE IF NOT EXISTS ingest_files (path VARCHAR PRIMARY KEY, size BIGINT, lines_read BIGINT);
"""


def connect(path: Path | str) -> duckdb.DuckDBPyConnection:
    if str(path) != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(path))
    con.execute(SCHEMA)
    cols = {r[0] for r in con.execute("DESCRIBE raw_events").fetchall()}
    if "cache_write_5m_tokens" not in cols:  # database from an older version: keep history, add the column
        con.execute("ALTER TABLE raw_events ADD COLUMN cache_write_5m_tokens BIGINT")
    return con
