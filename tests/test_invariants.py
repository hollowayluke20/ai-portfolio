from sim.invariants import check


RULES={"cash":{"floor":.05}}
BASE={"account":{"cash":50},"totals":{"total_value":100,"cash_weight":.5,"available_cash":50},"positions":[{"market_value":50,"weight":.5}],"pending_orders":[],"performance":None}

def test_clean_state_passes(): assert check(BASE,{"rows":[{"date":"2026-01-01"}]},RULES,"2026-01-01") == []
def test_detects_broken_invariants():
    state={**BASE,"totals":{**BASE["totals"],"cash_weight":.48,"total_value":99}}
    messages=check(state,{"rows":[{"date":"2026-01-02"},{"date":"2026-01-01"},{"date":"2026-01-01"}]},RULES,"2026-01-02")
    assert any("weights" in item for item in messages) and any("total_value" in item for item in messages) and any("duplicate" in item for item in messages)
