from dataclasses import dataclass
from importlib import resources
from pathlib import Path

from platformdirs import user_config_dir

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib

CHARS_PER_TOKEN = 4  # rough estimate used to turn result sizes into tokens


@dataclass(frozen=True)
class ModelPrice:
    input: float
    output: float
    cache_write: float
    cache_read: float


def load_prices(path: Path | None = None) -> dict[str, ModelPrice]:
    if path is None:
        text = resources.files("tokenwise").joinpath("pricing.toml").read_text(encoding="utf-8")
    else:
        text = Path(path).read_text(encoding="utf-8")
    models = tomllib.loads(text).get("models", {})
    return {name: ModelPrice(**vals) for name, vals in models.items()}


def turn_cost(price: ModelPrice | None, turn: dict) -> float | None:
    if price is None:
        return None
    return (turn["input_tokens"] * price.input + turn["output_tokens"] * price.output
            + turn["cache_write_tokens"] * price.cache_write
            + turn["cache_read_tokens"] * price.cache_read) / 1e6


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
