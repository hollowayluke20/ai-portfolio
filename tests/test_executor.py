from src.portfolio import executor


UNIVERSE = ["AAPL", "NVDA", "MSFT", "SPY", "QQQ", "GLD"]
RULES = {"position_weight": {"hard_cap": .10}, "position_count": {"minimum": 0, "maximum": 20}, "cash": {"floor": .05}}


def _state(cash=100):
    return {"totals": {"total_value": 100, "available_cash": cash}, "positions": [{"ticker": "MSFT", "market_value": 20}], "universe": ["MSFT", "NVDA", "AAPL"], "assets": {ticker: {"tradable": True, "fractionable": True} for ticker in ("MSFT", "NVDA", "AAPL")}}


def test_rejected_sell_does_not_block_buy(monkeypatch):
    submitted = []
    monkeypatch.setattr(executor, "submit_order", lambda **order: submitted.append(order) or {"order_id": "x"})
    result = executor.execute([{"ticker": "AAPL", "action": "SELL", "target_weight": 0}, {"ticker": "NVDA", "action": "BUY", "target_weight": .10}], _state(), RULES, UNIVERSE, False)
    assert [d["status"] for d in result] == ["rejected", "executed"]
    assert submitted[0]["ticker"] == "NVDA"


def test_tail_buy_drops_and_dry_run_submits_nothing(monkeypatch):
    monkeypatch.setattr(executor, "submit_order", lambda **_: (_ for _ in ()).throw(AssertionError("submitted")))
    decisions = [{"ticker": "NVDA", "action": "BUY", "target_weight": .10}, {"ticker": "AAPL", "action": "BUY", "target_weight": .10}]
    assert [d["status"] for d in executor.execute(decisions, _state(15), RULES, UNIVERSE, True)] == ["skipped", "rejected"]
