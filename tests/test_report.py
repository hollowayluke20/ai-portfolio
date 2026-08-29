from src.portfolio.report import build_report


def _state(performance=None, health=None):
    return {"market_data_as_of": "2026-08-28T20:00:00Z", "totals": {"total_value": 103421},
            "performance": performance, "benchmark": {"total_return_pct": .01, "difference_pct": .0242},
            "positions": [{"ticker": "MSFT", "weight": .1, "unrealized_pl_pct": .05}],
            "health": health or {"ok": True, "warnings": []}}


def test_subject_contains_value_and_return():
    subject, _ = build_report(_state({"total_return_pct": .0342}), {"rows": []}, None)
    assert "$103,421" in subject and "+3.42%" in subject


def test_pre_inception_and_no_decisions_are_honest():
    _, body = build_report(_state(), {"rows": []}, None)
    assert "not yet started trading" in body
    # Must not claim a zero RETURN. Checked precisely: the bare substring
    # "0.00%" also matches inside "+10.00%", so a loose assertion fails on any
    # weight ending in those digits rather than on a real zero return.
    assert "+0.00% since entry" not in body
    assert "Return since inception" not in body
    assert "No cycle has run yet." in body
    assert "none this cycle" in body


def test_warnings_lead_and_short_history_omits_weekly_line():
    _, body = build_report(_state(health={"ok": False, "warnings": ["feed delayed"]}), {"rows": [{"portfolio_value": 1}]}, {"decisions": []})
    assert body.startswith("HEALTH WARNINGS")
    assert "This week:" not in body
