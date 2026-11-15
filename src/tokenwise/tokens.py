CHARS_PER_TOKEN = 4  # rough estimate used to turn result sizes into tokens


def carried_tokens(result_tokens: float, turns_remaining: int) -> float:
    """Tokens spent carrying a tool result: written once, then re-read on every later turn."""
    return result_tokens * (1 + turns_remaining)


def fmt(x: float) -> str:
    return f"{x / 1e6:,.1f}M" if x >= 1e6 else f"{x / 1e3:,.0f}k" if x >= 1e3 else f"{x:,.0f}"
