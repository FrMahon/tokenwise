"""Cost of carrying skill descriptions in every session, and how often each skill is actually used."""
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

from .tokens import CHARS_PER_TOKEN, carried_tokens, fmt

NO_PLUGIN = "(no plugin)"


@dataclass
class SkillStat:
    name: str
    plugin: str
    tokens_per_session: float  # estimated, averaged over the sessions where the skill was listed
    sessions: int
    uses: int
    carried: float  # estimated tokens spent carrying the description: written once, re-read on every later turn


@dataclass
class McpStat:
    group: str  # plugin name, "claude.ai: <connector>", or the MCP server name
    tools: int  # distinct tools seen (listed to the session or called)
    used_tools: int
    uses: int


@dataclass
class SkillReport:
    skills: list[SkillStat]  # carried tokens descending, ties by name
    sessions: int  # sessions in the window that loaded a skill listing
    days: int
    data_from: str | None = None  # first and last day (UTC, YYYY-MM-DD) the data actually covers
    data_to: str | None = None
    mcp: list[McpStat] = field(default_factory=list)  # uses descending, ties by name


def mcp_group(tool: str) -> str:
    """mcp__plugin_<plugin>_<server>__tool -> plugin; mcp__claude_ai_<X>__tool -> "claude.ai: X"; mcp__<server>__tool -> server."""
    server = tool.split("__")[1] if tool.count("__") >= 2 else tool
    if server.startswith("plugin_"):
        return server[7:].split("_", 1)[0]  # shortcut: plugin names containing "_" are cut at it, fix when one shows up
    if server.startswith("claude_ai_"):
        return "claude.ai: " + server[10:].replace("_", " ")
    return server


def plugin_of(name: str) -> str:
    return name.split(":", 1)[0] if ":" in name else NO_PLUGIN


def skill_report(con, *, days: int = 30, now: datetime | None = None) -> SkillReport:
    now = now or datetime.now(timezone.utc)
    cutoff = (now - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S")  # ISO strings sort like times

    listed = con.execute("""
        WITH first AS (SELECT session_id, min(ts) AS t FROM raw_events WHERE type = 'skill_listed' GROUP BY session_id)
        SELECT e.session_id, e.skill_name, max(e.result_chars), min(f.t)
        FROM raw_events e JOIN first f USING (session_id)
        WHERE e.type = 'skill_listed' AND f.t >= ? AND e.skill_name IS NOT NULL
        GROUP BY e.session_id, e.skill_name""", [cutoff]).fetchall()
    per_session: dict[str, dict[str, int]] = defaultdict(dict)
    started: dict[str, str] = {}
    for session, name, chars, t in listed:
        per_session[session][name] = chars or 0
        started[session] = t

    turn_counts = dict(con.execute("SELECT session_id, count(*) FROM turns GROUP BY session_id").fetchall())

    tokens: dict[str, list[float]] = defaultdict(list)
    carried: dict[str, float] = defaultdict(float)
    sessions = 0
    starts: list[str] = []
    for session, entries in per_session.items():
        turns = turn_counts.get(session, 0)
        if turns == 0:
            continue
        sessions += 1
        starts.append(started[session])
        for name, chars in entries.items():
            est = chars / CHARS_PER_TOKEN
            tokens[name].append(est)
            carried[name] += carried_tokens(est, turns - 1)

    uses = dict(con.execute("""
        SELECT skill_name, count(*) FROM raw_events
        WHERE skill_name IS NOT NULL AND ts >= ?
          AND (type = 'skill_used' OR (type = 'tool_use' AND tool_name = 'Skill'))
        GROUP BY skill_name""", [cutoff]).fetchall())

    stats = [SkillStat(name, plugin_of(name), sum(t) / len(t), len(t), uses.get(name, 0), carried[name])
             for name, t in tokens.items()]
    stats.sort(key=lambda s: (-s.carried, s.name))
    last = con.execute("SELECT max(ts) FROM raw_events WHERE ts >= ?", [cutoff]).fetchone()[0]
    mcp_uses = dict(con.execute("""
        SELECT tool_name, count(*) FROM raw_events
        WHERE type = 'tool_use' AND starts_with(tool_name, 'mcp__') AND ts >= ? GROUP BY tool_name""", [cutoff]).fetchall())
    seen = {r[0] for r in con.execute(
        "SELECT DISTINCT tool_name FROM raw_events WHERE type = 'mcp_listed' AND ts >= ?", [cutoff]).fetchall()}
    groups: dict[str, list[tuple[str, int]]] = defaultdict(list)
    for tool in seen | set(mcp_uses):
        groups[mcp_group(tool)].append((tool, mcp_uses.get(tool, 0)))
    mcp = sorted((McpStat(g, len(ts), sum(1 for _, n in ts if n), sum(n for _, n in ts)) for g, ts in groups.items()),
                 key=lambda m: (-m.uses, m.group))
    return SkillReport(stats, sessions, days,
                       min(starts)[:10] if starts else None, last[:10] if last else None, mcp)


def _line(label: str, tokens: float, uses: int, carried: float, extra: str = "") -> str:
    flag = "  unused" if uses == 0 else ""
    return f"  {label}   {extra}~{tokens:,.0f} tokens/session  {uses} uses  ~{fmt(carried)} tokens carried{flag}"


def render_skills(report: SkillReport) -> str:
    if not report.skills:
        return f"No skill listings found in the last {report.days} days." + _render_mcp(report)
    total_tokens = sum(s.tokens_per_session for s in report.skills)
    total_carried = sum(s.carried for s in report.skills)
    plugins: dict[str, list[SkillStat]] = defaultdict(list)
    for s in report.skills:
        plugins[s.plugin].append(s)
    rollup = sorted(((p, ss, sum(x.carried for x in ss)) for p, ss in plugins.items()), key=lambda t: (-t[2], t[0]))
    lines = [f"Skills loaded in {report.sessions} sessions (last {report.days} days)",
             f"Skill descriptions: ~{total_tokens:,.0f} tokens/session, ~{fmt(total_carried)} tokens carried over these sessions. "
             "Token counts are estimates."]
    if report.data_from and report.data_to:
        span = (date.fromisoformat(report.data_to) - date.fromisoformat(report.data_from)).days + 1
        short = f", less than the {report.days} requested" if span < report.days else ""
        lines.append(f"Data covers {report.data_from} to {report.data_to} ({span} days){short}")
    lines += ["", "By plugin"]
    for plugin, ss, carried in rollup:
        lines.append(_line(plugin, sum(x.tokens_per_session for x in ss), sum(x.uses for x in ss), carried,
                           extra=f"{len(ss)} skills  "))
    lines += ["", "All skills"]
    lines += [_line(s.name, s.tokens_per_session, s.uses, s.carried) for s in report.skills]
    lines.append(_render_mcp(report))
    return "\n".join(lines)


def _render_mcp(report: SkillReport) -> str:
    if not report.mcp:
        return ""
    lines = ["", "MCP tools by plugin / server (tool schemas are not in the transcripts, so no size is estimated)"]
    for m in report.mcp:
        flag = "  unused" if m.uses == 0 else ""
        lines.append(f"  {m.group}   {m.tools} tools  {m.used_tools} used  {m.uses} calls{flag}")
    return "\n".join(lines)
