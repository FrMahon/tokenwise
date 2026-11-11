from dataclasses import dataclass, replace
from datetime import date
from importlib import resources
from pathlib import Path

from platformdirs import user_config_dir

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib

STALE_AFTER_DAYS = 90
CHARS_PER_TOKEN = 4  # rough estimate used to turn result sizes into tokens


@dataclass(frozen=True)
class ModelPrice:
    input: float
    output: float
    cache_write: float
    cache_read: float
    cache_write_5m: float | None = None  # default: 1.25 x input, the published 5-minute write rate

    @property
    def write_5m(self) -> float:
        return self.cache_write_5m if self.cache_write_5m is not None else self.input * 1.25


def load_prices(path: Path | None = None) -> dict[str, ModelPrice]:
    if path is None:
        text = resources.files("tokenwise").joinpath("pricing.toml").read_text(encoding="utf-8")
    else:
        text = Path(path).read_text(encoding="utf-8")
    models = tomllib.loads(text).get("models", {})
    return {name: ModelPrice(**vals) for name, vals in models.items()}


def bundled_prices_date() -> date:
    text = resources.files("tokenwise").joinpath("pricing.toml").read_text(encoding="utf-8")
    return tomllib.loads(text)["as_of"]


def stale_note(as_of: date, today: date | None = None) -> str | None:
    """A one-line warning when the bundled prices were last checked a long time ago."""
    age = ((today or date.today()) - as_of).days
    if age <= STALE_AFTER_DAYS:
        return None
    return (f"Note: bundled prices were last checked on {as_of.isoformat()} ({age} days ago) and may be out of date; "
            f"check the official pricing page and override with --pricing FILE or {default_user_pricing_path()}.")


def turn_cost(price: ModelPrice | None, turn: dict) -> float | None:
    if price is None:
        return None
    # Writes with a known 5-minute TTL are cheaper; the rest (1 hour, or unknown in older rows) bill at the 1-hour rate.
    short = min(turn.get("cache_write_5m_tokens") or 0, turn["cache_write_tokens"])
    return (turn["input_tokens"] * price.input + turn["output_tokens"] * price.output
            + short * price.write_5m + (turn["cache_write_tokens"] - short) * price.cache_write
            + turn["cache_read_tokens"] * price.cache_read) / 1e6


def blended_step_price(price: ModelPrice | None, share_5m: float) -> ModelPrice | None:
    """Price whose cache_write is the average of the 5-minute and 1-hour rates, weighted by usage."""
    if price is None:
        return None
    return replace(price, cache_write=share_5m * price.write_5m + (1 - share_5m) * price.cache_write)


def step_cost(price: ModelPrice | None, result_tokens: float, turns_remaining: int) -> float | None:
    """Cost of carrying a tool result: written once, then re-read on every later turn."""
    if price is None:
        return None
    return (result_tokens * price.cache_write + result_tokens * turns_remaining * price.cache_read) / 1e6


def default_user_pricing_path() -> Path:
    return Path(user_config_dir("tokenwise")) / "pricing.toml"


def load_effective_prices(explicit: Path | None = None, user_config: Path | None = None) -> dict[str, ModelPrice]:
    """Bundled prices, overridden by the user config file, overridden by an explicit file."""
    prices = load_prices()
    cfg = user_config if user_config is not None else default_user_pricing_path()
    if cfg.is_file():
        prices.update(load_prices(cfg))
    if explicit is not None:
        prices.update(load_prices(explicit))
    return prices


def price_for(prices: dict[str, ModelPrice], model: str | None) -> ModelPrice | None:
    """Exact match, else the longest listed id that prefixes the model (dated ids)."""
    if not model:
        return None
    if model in prices:
        return prices[model]
    hits = [k for k in prices if model.startswith(k)]
    return prices[max(hits, key=len)] if hits else None
