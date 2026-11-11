"""Waste labels derived from the data itself (no human labels exist)."""
from .pricing import CHARS_PER_TOKEN

EDIT_TOOLS = ("Edit", "Write", "NotebookEdit")


def build_labels(con, *, bulky_tokens: int = 4000, lookahead: int = 10) -> None:
    """Create `step_labels(session_id, step_idx, repeat, bulky_unused, wasted)` from `steps`.

    repeat: same tool + input + identical result already seen earlier in the session.
    bulky_unused: result >= bulky_tokens and no Edit/Write on the same target within the next
    `lookahead` steps.
    """
    edit_list = ",".join(f"'{t}'" for t in EDIT_TOOLS)
    con.execute(f"""
        CREATE OR REPLACE TABLE step_labels AS
        WITH base AS (
            SELECT s.*,
                   coalesce(count(*) OVER (
                       PARTITION BY session_id, tool_name, input_hash, result_hash
                       ORDER BY step_idx ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) > 0
                       AND result_hash IS NOT NULL, false) AS repeat,
                   coalesce(result_chars IS NOT NULL
                       AND result_chars / {CHARS_PER_TOKEN} >= {int(bulky_tokens)}, false) AS bulky
            FROM steps s
        )
        SELECT b.session_id, b.step_idx, b.repeat,
               (b.bulky AND NOT EXISTS (
                   SELECT 1 FROM steps n
                   WHERE n.session_id = b.session_id
                     AND n.step_idx > b.step_idx AND n.step_idx <= b.step_idx + {int(lookahead)}
                     AND n.tool_name IN ({edit_list}) AND n.input_hash = b.input_hash)) AS bulky_unused
        FROM base b
    """)
    con.execute("ALTER TABLE step_labels ADD COLUMN wasted BOOLEAN")
    con.execute("UPDATE step_labels SET wasted = (repeat OR bulky_unused)")
