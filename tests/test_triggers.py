from src.portfolio.triggers import mechanical_decisions

RULES={"sell_triggers":{"stop_loss_pct":-.2,"concentration_trim_threshold":.12,"concentration_trim_target":.063}}
def test_stop_wins_over_trim():
    out=mechanical_decisions({"positions":[{"ticker":"X","unrealized_pl_pct":-.2,"weight":.13}]},RULES)
    assert len(out)==1 and out[0]["action"]=="SELL"
def test_trim_and_missing_values():
    assert mechanical_decisions({"positions":[{"ticker":"X","unrealized_pl_pct":-.1,"weight":.13}]},RULES)[0]["action"]=="TRIM"
    assert not mechanical_decisions({"positions":[{"ticker":"X","unrealized_pl_pct":None,"weight":None}]},RULES)
