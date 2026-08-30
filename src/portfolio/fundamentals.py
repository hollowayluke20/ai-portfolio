"""SEC company-facts collection and pure fundamental calculations."""

from __future__ import annotations

from datetime import date, timedelta
import time

import requests


SEC_HEADERS = {"User-Agent": "Luke Holloway hollowayluke20@gmail.com"}
SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
COMPANYFACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"

MEASURES: dict[str, dict[str, object]] = {
    "EarningsPerShareDiluted": {"kind": "flow", "tags": ["EarningsPerShareDiluted", "EarningsPerShareBasic", "EarningsPerShareBasicAndDiluted"]},
    "Revenues": {"kind": "flow", "tags": ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "RevenueFromContractWithCustomerIncludingAssessedTax", "SalesRevenueNet"]},
    "NetIncomeLoss": {"kind": "flow", "tags": ["NetIncomeLoss"]},
    "GrossProfit": {"kind": "flow", "tags": ["GrossProfit"]},
    "NetCashProvidedByUsedInOperatingActivities": {"kind": "flow", "tags": ["NetCashProvidedByUsedInOperatingActivities"]},
    "Assets": {"kind": "instant", "tags": ["Assets"]},
    "AssetsCurrent": {"kind": "instant", "tags": ["AssetsCurrent"]},
    "LiabilitiesCurrent": {"kind": "instant", "tags": ["LiabilitiesCurrent"]},
    "LongTermDebtNoncurrent": {"kind": "instant", "tags": ["LongTermDebtNoncurrent", "LongTermDebt"]},
    "CommonStockSharesOutstanding": {"kind": "instant", "tags": ["CommonStockSharesOutstanding", "dei:EntityCommonStockSharesOutstanding"]},
}


def _derive_missing_quarters(rows: list[dict]) -> list[dict]:
    """Reconstruct quarters that are never filed as quarters.

    A US filer reports Q1-Q3 on 10-Qs and then the whole year on a 10-K. **The
    fourth quarter is never a standalone row.** It exists only as the annual
    figure minus the nine-month one, and any method that keeps only rows
    already spanning under 110 days silently drops it.

    That is not a rounding issue. Apple's four most recent "quarters" came out
    as Q3-2025, Q1-2026, Q2-2026, Q3-2026 - a 455-day span with September 2025
    missing entirely. It gave 8.44 where the true trailing year is 8.71, and
    an independent source showed 8.72. That 3% gap was visible in the audit
    from the first run and was explained away as a definitional difference.

    Two rows sharing a `start` differ by exactly the period between their two
    ends, so subtracting the shorter from the longer yields the missing stub.
    """
    by_start: dict[str, list[dict]] = {}
    for row in rows:
        if row.get("start"):
            by_start.setdefault(row["start"], []).append(row)

    derived: list[dict] = []
    for start, group in by_start.items():
        group = sorted(group, key=lambda r: r["end"])
        for shorter, longer in zip(group, group[1:]):
            span = (date.fromisoformat(longer["end"])
                    - date.fromisoformat(shorter["end"])).days
            if 60 <= span <= 110:
                derived.append({
                    "start": shorter["end"],
                    "end": longer["end"],
                    "filed": max(shorter.get("filed", ""), longer.get("filed", "")),
                    "val": float(longer["val"]) - float(shorter["val"]),
                    "derived": True,
                })
    return derived


def compute_ttm(points: list[dict], as_of: str) -> float | None:
    """Sum the four latest public quarterly flow values, or return ``None``."""
    public = [p for p in points if p.get("filed", "") <= as_of and p.get("start")]
    candidates = public + _derive_missing_quarters(public)

    # Keyed on `end` alone, not on the whole period.
    #
    # A derived quarter and the filed one covering the same three months can
    # differ by a day in their start - one runs from the prior period's end,
    # the other from the day after. Keyed on (start, end) both survive, the
    # four "most recent" quarters then contain the same quarter twice, and the
    # span check rejects the lot. One row per period end is what summing four
    # quarters actually means.
    #
    # A filed row always beats a derived one; between two filed rows, the
    # later filing wins, because quarters get restated.
    def better(new, old):
        if old is None:
            return True
        if bool(old.get("derived")) != bool(new.get("derived")):
            return not new.get("derived")
        return new.get("filed", "") > old.get("filed", "")

    latest: dict[str, dict] = {}
    for point in candidates:
        if (date.fromisoformat(point["end"]) - date.fromisoformat(point["start"])).days >= 110:
            continue
        if better(point, latest.get(point["end"])):
            latest[point["end"]] = point
    quarters = sorted(latest.values(), key=lambda point: point["end"], reverse=True)[:4]
    if len(quarters) != 4:
        return None
    earliest_start = min(point["start"] for point in quarters)
    latest_end = max(point["end"] for point in quarters)
    span = (date.fromisoformat(latest_end) - date.fromisoformat(earliest_start)).days
    if not 330 <= span <= 400:
        return None
    return sum(float(point["val"]) for point in quarters)


def latest_instant(points: list[dict], as_of: str) -> float | None:
    """Return the latest publicly filed instant value, never an aggregate."""
    public = [point for point in points if point.get("filed", "") <= as_of]
    return float(max(public, key=lambda point: (point["end"], point["filed"]))["val"]) if public else None


def summarise(entry: dict, price: float | None, as_of: str) -> dict:
    """The few numbers worth putting in front of the model, for one ticker.

    Everything is point-in-time: each figure is computed from filings that
    were public on `as_of`, and the year-ago comparison is what was public a
    year before that. A backtest replaying January must not see April's
    accounts, and must not compare against a restatement filed since.

    Any measure that cannot be computed honestly comes back None. A blank
    tells the model nothing; a wrong number tells it something false, which
    is worse, because a number carries authority a blank does not.
    """
    measures = (entry or {}).get("measures") or {}

    def flow(name, at):
        points = (measures.get(name) or {}).get("points") or []
        return compute_ttm(points, at)

    year_ago = (date.fromisoformat(as_of) - timedelta(days=365)).isoformat()

    eps = flow("EarningsPerShareDiluted", as_of)
    revenue = flow("Revenues", as_of)
    revenue_prior = flow("Revenues", year_ago)
    income = flow("NetIncomeLoss", as_of)

    growth = None
    if revenue and revenue_prior and revenue_prior > 0:
        growth = revenue / revenue_prior - 1

    margin = None
    if revenue and income is not None and revenue > 0:
        margin = income / revenue

    return {
        "pe": pe_ratio(price, eps) if price else None,
        "revenue_growth": growth,
        "net_margin": margin,
    }


def pe_ratio(price: float, ttm_eps: float | None) -> float | None:
    """Return a meaningful P/E only for positive earnings."""
    return price / ttm_eps if ttm_eps is not None and ttm_eps > 0 else None


def ticker_ciks() -> dict[str, str]:
    """Fetch the SEC ticker map with its required zero-padded CIKs."""
    response = requests.get(SEC_TICKERS_URL, headers=SEC_HEADERS, timeout=30)
    response.raise_for_status()
    return {entry["ticker"]: f"{int(entry['cik_str']):010d}" for entry in response.json().values()}


def _measure_points(
    facts: dict, tags: list[str], expected_unit: str
) -> tuple[str | None, list[dict]]:
    candidates: list[tuple[str, list[dict], str]] = []
    for tag in tags:
        namespace, _, name = tag.partition(":")
        if not name:
            namespace, name = "us-gaap", namespace
        concept = facts.get(namespace, {}).get(name)
        if concept:
            units = concept.get("units", {})
            points = units.get(expected_unit, next(iter(units.values()), []))
            if points:
                candidates.append((tag, points, max(row.get("filed", "") for row in points)))
    if not candidates:
        return None, []

    newest_filed = max(candidate[2] for candidate in candidates)
    newest_date = date.fromisoformat(newest_filed) if newest_filed else date.min
    close_candidates = [
        candidate for candidate in candidates
        if candidate[2] and (newest_date - date.fromisoformat(candidate[2])).days <= 90
    ] or candidates

    def quarterly_rows_last_three_years(candidate: tuple[str, list[dict], str]) -> int:
        _, points, _ = candidate
        return sum(
            bool(row.get("start"))
            and (date.fromisoformat(row["end"]) - date.fromisoformat(row["start"])).days < 110
            and (newest_date - date.fromisoformat(row["end"])).days <= 3 * 365
            for row in points
        )

    tag, points, _ = max(
        close_candidates,
        key=lambda candidate: (quarterly_rows_last_three_years(candidate), candidate[2]),
    )
    latest_periods: dict[tuple[str, str], dict] = {}
    for point in points:
        key = (point.get("start", ""), point.get("end", ""))
        if key not in latest_periods or point.get("filed", "") > latest_periods[key].get("filed", ""):
            latest_periods[key] = point
    # 24, not 12. Each period end appears twice - once as the quarter, once
    # inside a year-to-date cumulative row - so 12 periods yields only about
    # six quarters, and they are not consecutive. Apple came out missing its
    # September 2025 quarter entirely, so its four most recent "quarters"
    # spanned 455 days and compute_ttm correctly refused to call that a year.
    # Every fundamental for every company was None.
    #
    # The trailing-year figure needs 4 quarters; the year-on-year comparison
    # in summarise() needs 8. 24 periods leaves room for both plus gaps.
    selected = sorted(
        latest_periods.values(), key=lambda row: (row.get("end", ""), row.get("filed", ""))
    )[-24:]
    return tag, [
        {key: row[key] for key in ("start", "end", "filed", "val") if key in row}
        for row in selected
    ]


def refresh_fundamentals(tickers: list[str]) -> dict[str, dict]:
    """Fetch raw SEC series for each ticker; the caller persists the result."""
    ciks = ticker_ciks()
    output: dict[str, dict] = {}
    for index, ticker in enumerate(tickers):
        if index and index % 25 == 0:
            print(f"fetched {index}/{len(tickers)} tickers", flush=True)
        cik = ciks.get(ticker)
        if cik is None:
            output[ticker] = {"cik": None, "measures": {}}
            continue
        if index:
            time.sleep(0.11)
        response = requests.get(COMPANYFACTS_URL.format(cik=cik), headers=SEC_HEADERS, timeout=60)
        if response.status_code == 404:
            facts = {}
        else:
            response.raise_for_status()
            facts = response.json().get("facts", {})
        measures = {}
        for name, specification in MEASURES.items():
            expected_unit = (
                "USD/shares" if name == "EarningsPerShareDiluted"
                else "shares" if name == "CommonStockSharesOutstanding"
                else "USD"
            )
            concept, points = _measure_points(
                facts, specification["tags"], expected_unit
            )
            measures[name] = {"concept": concept, "kind": specification["kind"], "points": points}
        output[ticker] = {"cik": cik, "measures": measures}
    return output
