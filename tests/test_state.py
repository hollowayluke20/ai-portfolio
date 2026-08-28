import json
from pathlib import Path

from src.portfolio.state import build_history_row, build_state


ROOT = Path(__file__).parents[1]


def test_build_state_reconciles_example_values():
    example = json.loads((ROOT / "data/examples/state.example.json").read_text())
    account = {
        "cash": example["account"]["cash"],
        "equity": example["account"]["equity"],
        "buying_power": example["account"]["buying_power"],
        "status": example["account"]["status"],
        "currency": "USD",
    }
    positions = [
        {
            "symbol": item["ticker"], "qty": item["qty"],
            "avg_entry_price": item["avg_entry_price"],
            "current_price": item["current_price"],
            "market_value": item["market_value"],
            "unrealized_pl": item["unrealized_pl"],
            "opened_at": item["opened_at"],
        }
        for item in example["positions"]
    ]
    inception = {
        "inception_date": "2026-09-01", "inception_value": 100000,
        "benchmark_ticker": "SPY", "benchmark_inception_price": 771.10,
    }
    state = build_state(account, positions, 774.55, example["market_data_as_of"], {}, inception,
                        example["generated_at"], example["run"])

    assert state["totals"]["total_value"] == round(
        state["account"]["cash"] + sum(p["market_value"] for p in state["positions"]), 2
    )
    assert abs(state["totals"]["cash_weight"] + sum(p["weight"] for p in state["positions"]) - 1) < 0.001
    assert build_history_row(state)["date"] == "2026-09-11"


def test_empty_portfolio_is_valid_and_has_no_performance():
    state = build_state(
        {"cash": 100000, "equity": 100000, "buying_power": 400000, "status": "ACTIVE"},
        [], 700.0, "2026-09-11T20:00:00Z", {}, None,
        "2026-09-11T21:17:04Z", {"id": "run_1", "trigger": "manual", "workflow": "daily-state"},
    )

    assert state["positions"] == []
    assert state["totals"] == {
        "total_value": 100000.0, "invested_value": 0.0,
        "cash_weight": 1.0, "position_count": 0,
    }
    assert state["performance"] is None
    assert state["benchmark"] is None
