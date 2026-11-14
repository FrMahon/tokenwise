from datetime import datetime, timezone

import pytest

from synth import asst_line, listing_line, skill_call_line, slash_line, write_raw
from tokenwise.db import connect
from tokenwise.ingest.loader import ingest_dir
from tokenwise.pricing import load_prices, price_for, step_cost
from tokenwise.skills import plugin_of, skill_report
from tokenwise.transform import build_layers

NOW = datetime(2026, 1, 31, tzinfo=timezone.utc)
ENTRIES = {"p:big": "x" * 396, "p:small": "y" * 36, "solo": "z" * 76}


def ts(day, sec=0):
    return f"2026-01-{day:02d}T00:00:{sec:02d}.000Z"


def report(tmp_path, sessions, **kw):
    for name, lines in sessions.items():
        write_raw(tmp_path / "sess" / "proj", name, lines)
    con = connect(tmp_path / "t.duckdb")
    ingest_dir(tmp_path / "sess", con)
    build_layers(con)
    return skill_report(con, load_prices(), now=NOW, **kw)


def by_name(rep):
    return {s.name: s for s in rep.skills}


def test_cost_and_uses(tmp_path):
    s1 = [listing_line(ts(5), ENTRIES), asst_line(ts(5, 1), "a1"), asst_line(ts(5, 2), "a2"),
          skill_call_line(ts(5, 3), "t1", "p:small"), slash_line(ts(5, 4), "/solo"), slash_line(ts(5, 5), "/model")]
    s2 = [listing_line(ts(6), ENTRIES)] + [asst_line(ts(6, i), f"b{i}") for i in (1, 2, 3)]
    rep = report(tmp_path, {"s1": s1, "s2": s2})
    assert [s.name for s in rep.skills] == ["p:big", "solo", "p:small"]
    stats = by_name(rep)
    assert (stats["p:big"].uses, stats["p:small"].uses, stats["solo"].uses) == (0, 1, 1)
    assert rep.sessions == 2 and "model" not in stats
    price = price_for(load_prices(), "claude-sonnet-5-5")
    assert stats["p:big"].cost == pytest.approx(2 * step_cost(price, (len("p:big") + 2 + 396) / 4, 2), abs=1e-9)
    assert stats["p:big"].plugin == "p" and stats["solo"].plugin == "(no plugin)"


def test_description_with_colons_and_newlines_counted_once(tmp_path):
    first = listing_line(ts(5), {"p:a": "Use when x: y\n  second line: more text"})
    second = listing_line(ts(5, 1), {"p:a": "short"})
    rep = report(tmp_path, {"s": [first, second, asst_line(ts(5, 2), "a1")]})
    assert [s.name for s in rep.skills] == ["p:a"]
    assert rep.skills[0].tokens_per_session == pytest.approx(len("p:a: Use when x: y\n  second line: more text") / 4)


def test_command_name_in_tool_result_not_a_use(tmp_path):
    result = {"type": "user", "timestamp": ts(5, 2), "message": {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "u", "content": "<command-name>/p:big</command-name>"}]}}
    rep = report(tmp_path, {"s": [listing_line(ts(5), ENTRIES), asst_line(ts(5, 1), "a1"), result]})
    assert by_name(rep)["p:big"].uses == 0


def test_window_excludes_old_sessions(tmp_path):
    old = [listing_line("2025-11-01T00:00:00.000Z", ENTRIES), asst_line("2025-11-01T00:00:01.000Z", "o1")]
    new = [listing_line(ts(5), ENTRIES), asst_line(ts(5, 1), "n1")]
    assert report(tmp_path, {"old": old, "new": new}, days=30).sessions == 1


def test_unpriced_model_reported(tmp_path):
    lines = [listing_line(ts(5), ENTRIES), asst_line(ts(5, 1), "a1", model="mystery-model")]
    rep = report(tmp_path, {"s": lines})
    assert rep.unpriced == ["mystery-model"]
    assert len(rep.skills) == 3 and all(s.cost == 0.0 for s in rep.skills)


def test_no_listings(tmp_path):
    rep = report(tmp_path, {"s": [asst_line(ts(5), "a1")]})
    assert rep.skills == [] and rep.sessions == 0


def test_plugin_of():
    assert plugin_of("superpowers:brainstorming") == "superpowers"
    assert plugin_of("init") == "(no plugin)"
