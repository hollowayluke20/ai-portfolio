from src.portfolio import executor


UNIVERSE = ["AAPL", "NVDA", "MSFT", "SPY", "QQQ", "GLD"]
RULES = {"position_weight": {"hard_cap_company": .10, "hard_cap_fund": .25},
         "position_count": {"minimum": 0, "maximum": 20}, "cash": {"floor": .05},
         "etf_universe": ["SPY", "IEF", "AGG", "TLT", "GLD"],
         "sleeves": {"bond": {"tickers": [], "min": 0.0, "max": 1.0},
                     "risk": {"min": 0.0, "max": 1.0}}}


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


def test_stop_loss_and_ai_sell_of_same_ticker_closes_once(monkeypatch):
    """The Jan-Mar 2026 backtest found CEG exiting twice on one stop-loss day.

    The mechanical trigger sells it, and the AI - which may act on anything it
    holds - proposes its own SELL for the same position. Both used to reach the
    broker; the second DELETE hits a position that no longer exists, raises,
    and kills the cycle during the SELL phase, before any BUY.
    """
    closed = []
    monkeypatch.setattr(executor, "close_full_position",
                        lambda **kw: closed.append(kw["ticker"]) or {"order_id": "x"})
    monkeypatch.setattr(executor, "submit_order", lambda **_: {"order_id": "y"})
    result = executor.execute(
        [{"ticker": "MSFT", "action": "SELL", "target_weight": 0, "trigger": "stop_loss"},
         {"ticker": "MSFT", "action": "SELL", "target_weight": 0, "basis": "thesis_change"}],
        _state(), RULES, UNIVERSE, False)

    assert closed == ["MSFT"], "the position must be closed exactly once"
    statuses = [d["status"] for d in result]
    assert statuses.count("executed") == 1
    assert statuses.count("rejected") == 1
    assert "superseded by the stop_loss decision" in \
        next(d["rejection_reason"] for d in result if d["status"] == "rejected")
