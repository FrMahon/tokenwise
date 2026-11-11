-- turns: one row per assistant message (repeated lines of the same message.id are collapsed;
-- usage comes from the last line, position from the first).
CREATE OR REPLACE TABLE turns AS
WITH ranked AS (
    SELECT *,
           min(line_no) OVER w AS first_line,
           row_number() OVER (w ORDER BY line_no DESC) AS rn
    FROM raw_events
    WHERE type = 'assistant'
    WINDOW w AS (PARTITION BY session_id, coalesce(message_id, 'line' || line_no))
)
SELECT session_id, project, first_line AS line_no, ts, model,
       row_number() OVER (PARTITION BY session_id ORDER BY first_line) AS turn_idx,
       coalesce(input_tokens, 0) AS input_tokens,
       coalesce(output_tokens, 0) AS output_tokens,
       coalesce(cache_write_tokens, 0) AS cache_write_tokens,
       coalesce(cache_read_tokens, 0) AS cache_read_tokens
FROM ranked
WHERE rn = 1;

-- steps: one row per tool_use joined to its tool_result (orphan results are dropped).
CREATE OR REPLACE TABLE steps AS
WITH uses AS (
    SELECT *, row_number() OVER (PARTITION BY session_id ORDER BY line_no, rowid) AS step_idx
    FROM raw_events
    WHERE type = 'tool_use'
),
results AS (
    SELECT session_id, tool_use_id, any_value(result_chars) AS result_chars,
           any_value(result_hash) AS result_hash
    FROM raw_events
    WHERE type = 'tool_result'
    GROUP BY session_id, tool_use_id
)
SELECT u.session_id, u.step_idx, u.project, u.ts, u.line_no, u.tool_name, u.input_hash,
       r.result_chars, r.result_hash, u.model,
       (SELECT count(*) FROM turns t
         WHERE t.session_id = u.session_id AND t.line_no > u.line_no) AS turns_remaining
FROM uses u
LEFT JOIN results r ON r.session_id = u.session_id AND r.tool_use_id = u.tool_use_id;
