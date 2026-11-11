"""Call-time features: only what is known when the tool is invoked (no result info)."""
import pandas as pd

CATEGORICAL = ["tool_name", "model", "prev_tool_name"]
NUMERIC = ["step_idx", "steps_since_same_tool", "same_input_seen_before", "hour"]
FEATURES = CATEGORICAL + NUMERIC
KEYS = ["session_id", "step_idx", "ts"]
TARGET = "wasted"
NEVER_SEEN = 999
# Built-in tools only; anything else (MCP servers, plugins) is bucketed so the model stays portable.
STANDARD_TOOLS = frozenset({
    "Agent", "Task", "AskUserQuestion", "Bash", "Edit", "Glob", "Grep", "NotebookEdit", "PowerShell",
    "Read", "Skill", "TodoWrite", "ToolSearch", "WebFetch", "WebSearch", "Write",
})


def build_features(con) -> pd.DataFrame:
    df = con.execute("""
        SELECT s.session_id, s.step_idx, s.ts, s.tool_name, s.input_hash,
               coalesce(s.model, 'unknown') AS model, l.wasted
        FROM steps s JOIN step_labels l USING (session_id, step_idx)
        ORDER BY s.session_id, s.step_idx
    """).df()
    if df.empty:
        return df.assign(prev_tool_name=[], steps_since_same_tool=[], same_input_seen_before=[], hour=[])
    df["tool_name"] = df["tool_name"].where(df["tool_name"].isin(STANDARD_TOOLS), "other")
    g = df.groupby("session_id", sort=False)
    df["prev_tool_name"] = g["tool_name"].shift(1).fillna("none")
    pos = g.cumcount()
    prev_pos = pos.groupby([df["session_id"], df["tool_name"]]).shift(1)
    df["steps_since_same_tool"] = (pos - prev_pos).fillna(NEVER_SEEN).astype(int)
    df["same_input_seen_before"] = df.groupby(["session_id", "input_hash"]).cumcount() > 0
    df["hour"] = pd.to_datetime(df["ts"], errors="coerce", utc=True).dt.hour.fillna(-1).astype(int)
    df["wasted"] = df["wasted"].astype(bool)
    return df.drop(columns=["input_hash"])
