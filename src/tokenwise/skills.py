"""Cost of carrying skill descriptions in every session, and how often each skill is actually used."""
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from .pricing import CHARS_PER_TOKEN, blended_step_price, price_for, step_cost

SYNTHETIC = "<synthetic>"  # Claude Code placeholder for messages it writes itself (no tokens, no price)
NO_PLUGIN = "(no plugin)"


@dataclass
class SkillStat:
    name: str
    plugin: str
    tokens_per_session: float  # estimated, averaged over the sessions where the skill was listed
    sessions: int
    uses: int
    cost: float


@dataclass
class SkillReport:
    skills: list[SkillStat]  # cost descending, ties by name
    sessions: int  # sessions in the window that loaded a skill listing
    unpriced: list[str]  # model ids without a price; their sessions add no cost
    days: int


def plugin_of(name: str) -> str:
    return name.split(":", 1)[0] if ":" in name else NO_PLUGIN


def skill_report(con, prices: dict, *, days: int = 30, now: datetime | None = None) -> SkillReport:
    now = now or datetime.now(timezone.utc)
    cutoff = (now - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S")  # ISO strings sort like times

    listed = con.execute("""
        WITH first AS (SELECT session_id, min(ts) AS t FROM raw_events WHERE type = 'skill_listed' GROUP BY session_id)
        SELECT e.session_id, e.skill_name, max(e.result_chars)
        FROM raw_events e JOIN first f USING (session_id)
        WHERE e.type = 'skill_listed' AND f.t >= ? AND e.skill_name IS NOT NULL
        GROUP BY e.session_id, e.skill_name""", [cutoff]).fetchall()
    per_session: dict[str, dict[str, int]] = defaultdict(dict)
    for session, name, chars in listed:
        per_session[session][name] = chars or 0

    info = {s: (turns, model) for s, turns, model in con.execute(
        "SELECT session_id, count(*), arg_min(model, turn_idx) FILTER (WHERE model <> ?) "
        "FROM turns GROUP BY session_id", [SYNTHETIC]).fetchall()}
    share_5m = {m: (cw5 / cw) if cw else 0.0 for m, cw5, cw in con.execute(
        "SELECT model, sum(cache_write_5m_tokens), sum(cache_write_tokens) FROM turns GROUP BY model").fetchall()}

    tokens: dict[str, list[float]] = defaultdict(list)
    cost: dict[str, float] = defaultdict(float)
    unpriced: set[str] = set()
    sessions = 0
    for session, entries in per_session.items():
        turns, model = info.get(session, (0, None))
        if turns == 0:
            continue
        sessions += 1
        price = blended_step_price(price_for(prices, model), share_5m.get(model, 0.0))
        if price is None:
            unpriced.add(model or "unknown")
        for name, chars in entries.items():
            est = chars / CHARS_PER_TOKEN
            tokens[name].append(est)
            cost[name] += step_cost(price, est, turns - 1) or 0.0

    uses = dict(con.execute("""
        SELECT skill_name, count(*) FROM raw_events
        WHERE skill_name IS NOT NULL AND ts >= ?
          AND (type = 'skill_used' OR (type = 'tool_use' AND tool_name = 'Skill'))
        GROUP BY skill_name""", [cutoff]).fetchall())

    stats = [SkillStat(name, plugin_of(name), sum(t) / len(t), len(t), uses.get(name, 0), cost[name])
             for name, t in tokens.items()]
    stats.sort(key=lambda s: (-s.cost, s.name))
    return SkillReport(stats, sessions, sorted(unpriced), days)
