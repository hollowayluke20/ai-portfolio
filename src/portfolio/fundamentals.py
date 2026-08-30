"""SEC company-facts collection and pure fundamental calculations."""

from __future__ import annotations

from datetime import date
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


def compute_ttm(points: list[dict], as_of: str) -> float | None:
    """Sum the four latest public quarterly flow values, or return ``None``."""
    latest: dict[tuple[str, str], dict] = {}
    for point in points:
        if point.get("filed", "") > as_of or not point.get("start"):
            continue
        if (date.fromisoformat(point["end"]) - date.fromisoformat(point["start"])).days >= 110:
            continue
        key = (point["start"], point["end"])
        if key not in latest or point["filed"] > latest[key].get("filed", ""):
            latest[key] = point
    quarters = sorted(latest.values(), key=lambda point: point["end"], reverse=True)[:4]
    return sum(float(point["val"]) for point in quarters) if len(quarters) == 4 else None


def latest_instant(points: list[dict], as_of: str) -> float | None:
    """Return the latest publicly filed instant value, never an aggregate."""
    public = [point for point in points if point.get("filed", "") <= as_of]
    return float(max(public, key=lambda point: (point["end"], point["filed"]))["val"]) if public else None


def pe_ratio(price: float, ttm_eps: float | None) -> float | None:
    """Return a meaningful P/E only for positive earnings."""
    return price / ttm_eps if ttm_eps is not None and ttm_eps > 0 else None


def ticker_ciks() -> dict[str, str]:
    """Fetch the SEC ticker map with its required zero-padded CIKs."""
    response = requests.get(SEC_TICKERS_URL, headers=SEC_HEADERS, timeout=30)
    response.raise_for_status()
    return {entry["ticker"]: f"{int(entry['cik_str']):010d}" for entry in response.json().values()}


def _measure_points(facts: dict, tags: list[str]) -> tuple[str | None, list[dict]]:
    for tag in tags:
        namespace, _, name = tag.partition(":")
        if not name:
            namespace, name = "us-gaap", namespace
        concept = facts.get(namespace, {}).get(name)
        if concept:
            units = concept.get("units", {})
            points = next(iter(units.values()), [])
            return tag, [
                {key: row[key] for key in ("start", "end", "val", "accn", "fy", "fp", "form", "filed", "frame") if key in row}
                for row in points[-12:]
            ]
    return None, []


def refresh_fundamentals(tickers: list[str]) -> dict[str, dict]:
    """Fetch raw SEC series for each ticker; the caller persists the result."""
    ciks = ticker_ciks()
    output: dict[str, dict] = {}
    for index, ticker in enumerate(tickers):
        cik = ciks.get(ticker)
        if cik is None:
            output[ticker] = {"cik": None, "measures": {}}
            continue
        if index:
            time.sleep(0.11)
        response = requests.get(COMPANYFACTS_URL.format(cik=cik), headers=SEC_HEADERS, timeout=60)
        response.raise_for_status()
        facts = response.json().get("facts", {})
        measures = {}
        for name, specification in MEASURES.items():
            concept, points = _measure_points(facts, specification["tags"])
            measures[name] = {"concept": concept, "kind": specification["kind"], "points": points}
        output[ticker] = {"cik": cik, "measures": measures}
    return output
