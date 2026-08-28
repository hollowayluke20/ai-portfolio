"""Pure-logic tests for the config loaders. No network."""

import json

import pytest

from src.portfolio import config


def test_load_rules_parses_real_file():
    rules = config.load_rules()
    assert rules["position_count"]["target"] == 15
    assert rules["position_count"]["minimum"] == 8
    assert rules["position_count"]["maximum"] == 20
    assert rules["cash"]["floor"] == 0.05
    assert rules["sell_triggers"]["stop_loss_pct"] == -0.20
    assert set(rules["broad_us_equity_cap"]["tickers"]) == {"SPY", "VOO", "QQQ"}
    assert "SPY" in rules["etf_universe"]


def test_save_inception_refuses_to_overwrite(tmp_path, monkeypatch):
    target = tmp_path / "inception.json"
    monkeypatch.setattr(config, "INCEPTION_PATH", target)

    baseline = {
        "inception_date": "2026-09-11",
        "inception_value": 100000.0,
        "benchmark_ticker": "SPY",
        "benchmark_inception_price": 771.10,
    }
    config.save_inception(baseline)
    assert json.loads(target.read_text())["benchmark_ticker"] == "SPY"

    with pytest.raises(FileExistsError):
        config.save_inception({"inception_value": 1.0})

    # the original file is untouched
    assert json.loads(target.read_text())["inception_value"] == 100000.0
