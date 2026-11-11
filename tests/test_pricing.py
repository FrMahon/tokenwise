import pytest

from tokenwise.pricing import (CHARS_PER_TOKEN, ModelPrice, load_effective_prices, load_prices,
                               price_for, step_cost, turn_cost)

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


def test_effective_prices_merge_explicit_over_bundled(tmp_path):
    f = tmp_path / "p.toml"
    f.write_text('[models."my-model"]\ninput = 1.0\noutput = 2.0\ncache_write = 3.0\ncache_read = 0.1\n')
    prices = load_effective_prices(f, user_config=tmp_path / "missing.toml")
    assert prices["my-model"].input == 1.0 and "claude-sonnet-5-5" in prices


def test_user_config_is_read_when_present(tmp_path):
    cfg = tmp_path / "pricing.toml"
    cfg.write_text('[models."claude-sonnet-5-5"]\ninput = 9.0\noutput = 9.0\ncache_write = 9.0\ncache_read = 9.0\n')
    assert load_effective_prices(None, user_config=cfg)["claude-sonnet-5-5"].input == 9.0


def test_dated_model_id_matches_by_prefix():
    prices = load_prices()
    assert price_for(prices, "claude-sonnet-5-5-20260101") == prices["claude-sonnet-5-5"]
    assert price_for(prices, "claude-sonnet-5-5") == prices["claude-sonnet-5-5"]
    assert price_for(prices, "totally-unknown") is None


def test_bundled_prices_have_a_date():
    from datetime import date
    from tokenwise.pricing import bundled_prices_date
    assert isinstance(bundled_prices_date(), date)


def test_stale_note_only_when_old():
    from datetime import date
    from tokenwise.pricing import stale_note
    as_of = date(2026, 1, 1)
    assert stale_note(as_of, today=date(2026, 3, 1)) is None
    assert stale_note(as_of, today=date(2026, 4, 1)) is None          # exactly 90 days
    note = stale_note(as_of, today=date(2026, 4, 2))
    assert note and "2026-01-01" in note and "--pricing" in note
