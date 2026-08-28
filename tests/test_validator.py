from src.portfolio.validator import check_cash, validate_static


RULES = {"position_weight": {"hard_cap": 0.10}, "position_count": {"minimum": 0, "maximum": 20}, "cash": {"floor": 0.05}}
STATE = {"positions": [{"ticker": "MSFT", "market_value": 100}], "assets": {"MSFT": {"tradable": True, "fractionable": True}}}


def test_rejects_percentage_weight_without_mutating_input():
    proposal = {"ticker": "MSFT", "action": "BUY", "target_weight": 6.3, "notional": 10}
    result = validate_static([proposal], STATE, RULES, ["MSFT"])
    assert not result[0]["valid"] and "decimal fraction" in result[0]["rejection_reason"]
    assert "valid" not in proposal


def test_rejects_outside_universe_and_cash_floor_uses_available_cash():
    result = validate_static([{"ticker": "NVDA", "action": "BUY", "target_weight": .05, "notional": 10}], STATE, RULES, ["MSFT"])
    assert not result[0]["valid"]
    assert check_cash({"notional": 10}, 14, 100, RULES)
