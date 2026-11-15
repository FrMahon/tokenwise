"""Plain-text terminal report."""
from collections import defaultdict

from .model import THRESHOLD, TrainResult
from .tokens import CHARS_PER_TOKEN, carried_tokens, fmt as _tok


SYNTHETIC = "<synthetic>"  # Claude Code placeholder for messages it writes itself (no tokens)


def render(con, result: TrainResult, probs, *, skipped_lines: int = 0) -> str:
    sessions = con.execute("SELECT count(DISTINCT session_id) FROM turns").fetchone()[0]

    total = con.execute(
        "SELECT coalesce(sum(input_tokens + output_tokens + cache_write_tokens + cache_read_tokens), 0) "
        "FROM turns WHERE model IS DISTINCT FROM ?", [SYNTHETIC]).fetchone()[0]

    rows = con.execute("""
        SELECT s.result_chars, s.turns_remaining, l.repeat, l.bulky_unused
        FROM steps s JOIN step_labels l USING (session_id, step_idx)
        ORDER BY s.session_id, s.step_idx""").fetchall()
    avoidable, leaks = 0.0, defaultdict(float)
    for (chars, remaining, repeat, bulky), p in zip(rows, probs):
        if p < THRESHOLD or chars is None:
            continue
        c = carried_tokens(chars / CHARS_PER_TOKEN, remaining)
        avoidable += c
        leaks["repeat" if repeat else "bulky_unused" if bulky else "other patterns"] += c

    pct = f" ({avoidable / total:.0%})" if total > 0 else ""
    lines = [
        f"Sessions analyzed: {sessions}",
        f"Tokens processed: {_tok(total)}",
        f"Avoidable: {_tok(avoidable)} tokens{pct}",
        "",
        "Top leaks",
    ]
    for i, (name, cost) in enumerate(sorted(leaks.items(), key=lambda kv: -kv[1])[:3], 1):
        lines.append(f"  {i}. {name:<16} {_tok(cost)}")
    if not leaks:
        lines.append("  none found")
    auc = result.metrics.get("roc_auc")
    lines += ["", f"Model: {result.source}" + (f" (AUC {auc:.2f})" if auc is not None else "")]
    if skipped_lines:
        lines.append(f"Note: {skipped_lines} lines were skipped (metadata or unrecognized format).")
    return "\n".join(lines)
