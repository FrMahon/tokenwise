"""Plain-text terminal report."""
from collections import defaultdict

from .model import THRESHOLD, TrainResult
from .pricing import CHARS_PER_TOKEN, load_prices, step_cost, turn_cost


def _money(x: float) -> str:
    return f"${x:,.2f}"


def render(con, result: TrainResult, probs, *, skipped_lines: int = 0) -> str:
    prices = load_prices()
    sessions = con.execute("SELECT count(DISTINCT session_id) FROM turns").fetchone()[0]

    total, unpriced = 0.0, defaultdict(int)
    for model, i, o, cw, cr in con.execute(
            "SELECT model, sum(input_tokens), sum(output_tokens), sum(cache_write_tokens), "
            "sum(cache_read_tokens) FROM turns GROUP BY model").fetchall():
        c = turn_cost(prices.get(model), {"input_tokens": i, "output_tokens": o,
                                          "cache_write_tokens": cw, "cache_read_tokens": cr})
        if c is None:
            unpriced[model or "unknown"] += 1
        else:
            total += c

    rows = con.execute("""
        SELECT s.model, s.result_chars, s.turns_remaining, l.repeat, l.bulky_unused
        FROM steps s JOIN step_labels l USING (session_id, step_idx)
        ORDER BY s.session_id, s.step_idx""").fetchall()
    avoidable, leaks = 0.0, defaultdict(float)
    for (model, chars, remaining, repeat, bulky), p in zip(rows, probs):
        if p < THRESHOLD or chars is None:
            continue
        c = step_cost(prices.get(model), chars / CHARS_PER_TOKEN, remaining)
        if c is None:
            continue
        avoidable += c
        leaks["repeat" if repeat else "bulky_unused" if bulky else "other patterns"] += c

    pct = f" ({avoidable / total:.0%})" if total > 0 else ""
    lines = [
        f"Sessions analyzed: {sessions}",
        f"Estimated spend: {_money(total)}",
        f"Avoidable: {_money(avoidable)}{pct}",
        "",
        "Top leaks",
    ]
    for i, (name, cost) in enumerate(sorted(leaks.items(), key=lambda kv: -kv[1])[:3], 1):
        lines.append(f"  {i}. {name:<16} {_money(cost)}")
    if not leaks:
        lines.append("  none found")
    auc = result.metrics.get("roc_auc")
    lines += ["", f"Model: {result.source}" + (f" (AUC {auc:.2f})" if auc is not None else "")]
    if unpriced:
        lines.append("Warning: no price for " + ", ".join(sorted(unpriced))
                     + " - their cost is excluded (edit pricing.toml).")
    if skipped_lines:
        lines.append(f"Note: {skipped_lines} lines were skipped (unrecognized or incomplete).")
    return "\n".join(lines)
