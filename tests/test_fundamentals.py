from src.portfolio.fundamentals import _measure_points, compute_ttm, latest_instant, pe_ratio, refresh_fundamentals


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


def test_ttm_rejects_four_quarters_with_a_gap():
    points = [
        _point("2024-01-01", "2024-03-30", 1),
        _point("2024-07-01", "2024-09-28", 2),
        _point("2024-10-01", "2024-12-28", 3),
        _point("2025-01-01", "2025-03-29", 4),
    ]
    assert compute_ttm(points, "2025-05-01") is None


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


def test_measure_points_prefers_the_expected_unit_and_keeps_24_rows():
    rows = [{"end": f"2024-01-{day:02d}", "filed": "2024-02-01", "val": day} for day in range(1, 26)]
    facts = {"us-gaap": {"Revenues": {"units": {"shares": [{"val": 999}], "USD": rows}}}}
    concept, points = _measure_points(facts, ["Revenues"], "USD")
    assert concept == "Revenues"
    # 25 rows in, the newest 24 kept, so the oldest survivor is day 2.
    assert len(points) == 24 and points[0]["val"] == 2


def test_measure_points_prefers_the_tag_with_current_filings():
    stale = [{"start": "2009-01-01", "end": "2009-03-31", "filed": "2010-04-01", "val": 1}]
    current = [{"start": "2025-01-01", "end": "2025-03-31", "filed": "2025-05-01", "val": 2}]
    facts = {"us-gaap": {
        "Revenues": {"units": {"USD": stale}},
        "RevenueFromContractWithCustomerExcludingAssessedTax": {"units": {"USD": current}},
    }}
    concept, points = _measure_points(
        facts, ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax"], "USD"
    )
    assert concept == "RevenueFromContractWithCustomerExcludingAssessedTax"
    assert points == current


# Apple's real filing shape: Q1-Q3 arrive as quarters, but the September
# quarter never does - it exists only as the 10-K year minus the nine-month
# cumulative. Keeping only rows already under 110 days drops it, and the four
# "most recent quarters" then span 455 days with a hole in the middle.
#
# That produced 8.44 against a true 8.71, and an outside source showing 8.72.
# The 3% gap was visible in the audit from its first run and was dismissed as
# a definitional difference. It was this.
APPLE_REAL = [
    {"start": "2024-09-29", "end": "2025-06-28", "filed": "2026-07-31", "val": 5.62},
    {"start": "2024-09-29", "end": "2025-09-27", "filed": "2025-10-31", "val": 7.46},
    {"start": "2025-09-28", "end": "2025-12-27", "filed": "2026-01-30", "val": 2.84},
    {"start": "2025-09-28", "end": "2026-03-28", "filed": "2026-05-01", "val": 4.85},
    {"start": "2025-12-28", "end": "2026-03-28", "filed": "2026-05-01", "val": 2.01},
    {"start": "2025-09-28", "end": "2026-06-27", "filed": "2026-07-31", "val": 6.88},
    {"start": "2026-03-29", "end": "2026-06-27", "filed": "2026-07-31", "val": 2.02},
]


def test_ttm_derives_the_quarter_that_is_never_filed():
    ttm = compute_ttm(APPLE_REAL, "2026-08-30")
    assert ttm is not None, "no fourth quarter was derived"
    # 2.84 + 2.01 + 2.02 + (7.46 - 5.62)
    assert round(ttm, 2) == 8.71


def test_a_derived_quarter_never_double_counts_a_filed_one():
    """The derived and filed versions of one quarter start a day apart.

    Keyed on the whole period both survive, the same three months are counted
    twice, and the span check then rejects everything. One row per period end.
    """
    ttm = compute_ttm(APPLE_REAL, "2026-08-30")
    assert ttm is not None and ttm < 10, "a quarter was counted twice"
