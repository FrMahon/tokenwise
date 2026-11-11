import pytest

from tokenwise.pricing import CHARS_PER_TOKEN, ModelPrice, load_prices, step_cost, turn_cost

P = ModelPrice(input=3.0, output=15.0, cache_write=6.0, cache_read=0.3)


def test_known_model_priced():
    prices = load_prices()
    assert "claude-sonnet-5-5" in prices
    assert prices["claude-sonnet-5-5"].cache_read < prices["claude-sonnet-5-5"].input


def test_unknown_model_returns_none():
    assert load_prices().get("some-future-model") is None
    assert turn_cost(None, {"input_tokens": 1}) is None
    assert step_cost(None, 100, 3) is None


def test_turn_cost_formula():
    turn = {"input_tokens": 1_000_000, "output_tokens": 1_000_000,
            "cache_write_tokens": 1_000_000, "cache_read_tokens": 1_000_000}
    assert turn_cost(P, turn) == pytest.approx(3.0 + 15.0 + 6.0 + 0.3)


def test_step_cost_formula():
    # 1M tokens written once, then read on 4 later turns
    assert step_cost(P, 1_000_000, 4) == pytest.approx(6.0 + 4 * 0.3)


def test_chars_per_token_constant():
    assert CHARS_PER_TOKEN == 4


def test_user_override_path(tmp_path):
    f = tmp_path / "p.toml"
    f.write_text('[models."my-model"]\ninput = 1.0\noutput = 2.0\ncache_write = 3.0\ncache_read = 0.1\n')
    prices = load_prices(f)
    assert prices == {"my-model": ModelPrice(1.0, 2.0, 3.0, 0.1)}
