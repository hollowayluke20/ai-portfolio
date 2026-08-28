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
        "committed_cash": 0.0, "available_cash": 100000.0,
    }
    assert state["pending_orders"] == []
    assert state["performance"] is None
    assert state["benchmark"] is None


def test_pending_buys_reduce_available_cash_without_affecting_weights():
    account = {"cash": 100, "equity": 150, "buying_power": 400, "status": "ACTIVE"}
    positions = [{"symbol": "MSFT", "qty": 1, "avg_entry_price": 50,
                  "current_price": 50, "market_value": 50, "unrealized_pl": 0}]
    orders = [
        {"order_id": "buy", "symbol": "NVDA", "side": "buy", "notional": 20,
         "qty": None, "status": "accepted", "submitted_at": "2026-08-28T12:00:00Z"},
        {"order_id": "sell", "symbol": "MSFT", "side": "sell", "notional": 30,
         "qty": None, "status": "accepted", "submitted_at": "2026-08-28T12:00:00Z"},
    ]
    state = build_state(account, positions, 700, "2026-08-28T20:00:00Z", {}, None,
                        "2026-08-28T21:00:00Z", {"id": "r", "trigger": "manual", "workflow": "x"},
                        pending_orders=orders)

    assert state["totals"]["committed_cash"] == 20.0
    assert state["totals"]["available_cash"] == 80.0
    assert state["totals"]["total_value"] == 150.0
    assert state["positions"][0]["weight"] == round(50 / 150, 4)


def test_unknown_quantity_order_warns_instead_of_assuming_zero_commitment():
    state = build_state(
        {"cash": 100, "equity": 100, "buying_power": 400, "status": "ACTIVE"}, [], 700,
        "2026-08-28T20:00:00Z", {}, None, "2026-08-28T21:00:00Z",
        {"id": "r", "trigger": "manual", "workflow": "x"},
        pending_orders=[{"order_id": "buy", "symbol": "NVDA", "side": "buy", "notional": None,
                         "qty": 2, "status": "accepted", "submitted_at": "2026-08-28T12:00:00Z"}],
    )

    assert state["totals"]["committed_cash"] == 0.0
    assert state["health"]["ok"] is False
    assert "Cannot determine committed cash" in state["health"]["warnings"][0]
