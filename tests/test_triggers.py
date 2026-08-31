from src.portfolio.triggers import mechanical_decisions

RULES={"sell_triggers":{"stop_loss_pct":-.2,"concentration_trim_threshold":.12},
       "sleeves":{"bond":{"tickers":["IEF","AGG","TLT"]}}}
def test_stop_wins_over_trim():
    out=mechanical_decisions({"positions":[{"ticker":"X","unrealized_pl_pct":-.2,"weight":.13}]},RULES)
    assert len(out)==1 and out[0]["action"]=="SELL"
def test_trim_and_missing_values():
    assert mechanical_decisions({"positions":[{"ticker":"X","unrealized_pl_pct":-.1,"weight":.13}]},RULES)[0]["action"]=="TRIM"
    assert not mechanical_decisions({"positions":[{"ticker":"X","unrealized_pl_pct":None,"weight":None}]},RULES)


def test_trim_targets_the_sleeve_weight_not_a_constant():
    """The trim used to cut everything back to a fixed 0.063.

    That number was the old one-size-fits-all position weight and stopped
    existing when sizing became derived. A bond fund at 14% would have been
    cut to 6.3% - not its target, and enough to pull the bond sleeve toward
    its floor.
    """
    state = {"positions": [
        {"ticker": "TLT", "weight": .14, "unrealized_pl_pct": .4},
        {"ticker": "IEF", "weight": .09, "unrealized_pl_pct": .0},
        {"ticker": "AGG", "weight": .09, "unrealized_pl_pct": .0},
    ]}
    trim = mechanical_decisions(state, RULES)[0]
    assert trim["action"] == "TRIM"
    # bond sleeve is 32% across three funds -> 10.67% each, not 6.3%
    assert round(trim["target_weight"], 3) == round(0.32 / 3, 3)
    assert trim["target_weight"] > 0.10


def test_trim_target_differs_between_sleeves():
    """A risk holding and a bond fund must not be trimmed to the same number."""
    state = {"positions": [
        {"ticker": "TLT", "weight": .13, "unrealized_pl_pct": .0},
        {"ticker": "IEF", "weight": .13, "unrealized_pl_pct": .0},
        {"ticker": "SPY", "weight": .13, "unrealized_pl_pct": .0},
        {"ticker": "GLD", "weight": .03, "unrealized_pl_pct": .0},
        {"ticker": "AAPL", "weight": .03, "unrealized_pl_pct": .0},
    ]}
    by_ticker = {d["ticker"]: d["target_weight"] for d in mechanical_decisions(state, RULES)}
    assert by_ticker["TLT"] != by_ticker["SPY"]
