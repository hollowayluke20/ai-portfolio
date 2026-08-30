from src.portfolio.fundamentals import compute_ttm, latest_instant, pe_ratio, refresh_fundamentals


def _point(start, end, val, filed="2024-12-31"):
    return {"start": start, "end": end, "val": val, "filed": filed}


APPLE_POINTS = [
    _point("2024-09-29", "2024-12-28", 2.40),
    _point("2024-09-29", "2024-12-28", 2.95),
    _point("2024-12-29", "2025-03-29", 1.57),
    _point("2024-09-29", "2025-03-29", 4.52),
    _point("2025-03-30", "2025-06-28", 2.84),
    _point("2024-09-29", "2025-06-28", 7.36),
    _point("2025-06-29", "2025-09-27", 2.01),
    _point("2024-09-29", "2025-09-27", 9.37),
    _point("2025-09-28", "2025-12-27", 2.02),
]


def test_ttm_uses_quarters_not_cumulative_rows():
    assert compute_ttm(APPLE_POINTS, "2026-02-01") == 8.44


def test_ttm_excludes_not_yet_filed_quarter():
    points = [
        _point("2024-01-01", "2024-03-30", 1),
        _point("2024-04-01", "2024-06-29", 2),
        _point("2024-07-01", "2024-09-28", 3),
        _point("2024-10-01", "2024-12-28", 4),
        _point("2025-01-01", "2025-03-29", 99, "2025-05-01"),
    ]
    assert compute_ttm(points, "2025-04-01") == 10


def test_ttm_uses_later_restatement_and_requires_four_quarters():
    points = [_point("2024-01-01", "2024-03-30", 1), _point("2024-04-01", "2024-06-29", 2), _point("2024-07-01", "2024-09-28", 3), _point("2024-10-01", "2024-12-28", 4), _point("2024-10-01", "2024-12-28", 5, "2025-02-01")]
    assert compute_ttm(points, "2025-03-01") == 11
    assert compute_ttm(points[:3], "2025-03-01") is None


def test_calculations_are_order_independent_and_instants_are_not_summed():
    points = [_point("2024-01-01", "2024-03-30", 1), _point("2024-04-01", "2024-06-29", 2), _point("2024-07-01", "2024-09-28", 3), _point("2024-10-01", "2024-12-28", 4)]
    assert compute_ttm(points, "2025-01-01") == compute_ttm(list(reversed(points)), "2025-01-01") == 10
    instants = [{"end": "2024-12-31", "filed": "2025-02-01", "val": 20}, {"end": "2025-03-31", "filed": "2025-05-01", "val": 30}]
    assert latest_instant(instants, "2025-04-01") == 20
    assert latest_instant(list(reversed(instants)), "2025-06-01") == 30
    assert pe_ratio(319.70, 8.44) == 319.70 / 8.44
    assert pe_ratio(1, None) is None and pe_ratio(1, -1) is None


def test_etf_without_cik_has_no_measures(monkeypatch):
    monkeypatch.setattr("src.portfolio.fundamentals.ticker_ciks", lambda: {})
    assert refresh_fundamentals(["SPY"])["SPY"] == {"cik": None, "measures": {}}
