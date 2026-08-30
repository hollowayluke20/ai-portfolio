"""Read-only quality checks for the stored SEC fundamentals series.

This script deliberately performs no network requests and never alters the
fundamentals file.  Supply prices with ``--price TICKER=VALUE`` when a P/E is
needed in the human cross-check table; prices are not part of the SEC dataset.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.portfolio.fundamentals import MEASURES, compute_ttm, latest_instant, pe_ratio  # noqa: E402


DATA_PATH = Path(__file__).resolve().parents[1] / "data" / "fundamentals.json"
CROSSCHECK_TICKERS = ("AAPL", "MSFT", "NVDA", "JPM", "XOM", "KO", "UNH", "PG")


@dataclass(frozen=True)
class Audit:
    companies: int
    coverage: dict[str, int]
    identity_violations: list[str]
    pe_outliers: list[str]
    margin_outliers: list[str]
    ttm_outliers: list[str]

    @property
    def failed(self) -> bool:
        return bool(
            self.identity_violations
            or any(count / self.companies < 0.9 for count in self.coverage.values())
        ) if self.companies else True


def _points(entry: dict, measure: str) -> list[dict]:
    return entry.get("measures", {}).get(measure, {}).get("points", [])


def _ttm_pair(points: list[dict], as_of: str) -> tuple[float | None, float | None]:
    """Return the current and preceding four quarterly values, if complete."""
    latest: dict[tuple[str, str], dict] = {}
    for point in points:
        if point.get("filed", "") > as_of or not point.get("start"):
            continue
        try:
            # ``compute_ttm`` is the authority on accepted rows; selecting its
            # input here keeps this comparison consistent with valuation.
            from datetime import date
            if (date.fromisoformat(point["end"]) - date.fromisoformat(point["start"])).days >= 110:
                continue
        except (KeyError, TypeError, ValueError):
            continue
        key = (point["start"], point["end"])
        if key not in latest or point.get("filed", "") > latest[key].get("filed", ""):
            latest[key] = point
    quarters = sorted(latest.values(), key=lambda point: point["end"], reverse=True)
    current = sum(float(point["val"]) for point in quarters[:4]) if len(quarters) >= 4 else None
    prior = sum(float(point["val"]) for point in quarters[4:8]) if len(quarters) >= 8 else None
    return current, prior


def audit_document(
    document: dict, as_of: str | None = None, prices: dict[str, float] | None = None
) -> Audit:
    """Audit one decoded fundamentals document without I/O or network access."""
    as_of = as_of or str(document.get("generated_at", ""))[:10]
    prices = prices or {}
    entries = document.get("tickers", {})
    companies = {ticker: entry for ticker, entry in entries.items() if entry.get("cik")}
    coverage = {
        measure: sum(bool(_points(entry, measure)) for entry in companies.values())
        for measure in MEASURES
    }
    identities: list[str] = []
    pe_outliers: list[str] = []
    margin_outliers: list[str] = []
    ttm_outliers: list[str] = []

    for ticker, entry in companies.items():
        values = {
            measure: (compute_ttm(_points(entry, measure), as_of)
                      if specification["kind"] == "flow"
                      else latest_instant(_points(entry, measure), as_of))
            for measure, specification in MEASURES.items()
        }
        revenue = values["Revenues"]
        gross_profit = values["GrossProfit"]
        net_income = values["NetIncomeLoss"]
        assets = values["Assets"]
        current_assets = values["AssetsCurrent"]
        shares = values["CommonStockSharesOutstanding"]
        if revenue is not None and gross_profit is not None and gross_profit > revenue:
            identities.append(f"{ticker}: gross profit ({gross_profit:g}) exceeds revenue ({revenue:g})")
        if revenue is not None and net_income is not None and net_income > revenue:
            identities.append(f"{ticker}: net income ({net_income:g}) exceeds revenue ({revenue:g})")
        if assets is not None and current_assets is not None and current_assets > assets:
            identities.append(f"{ticker}: current assets ({current_assets:g}) exceed total assets ({assets:g})")
        for name, value in (("total assets", assets), ("shares outstanding", shares), ("revenue", revenue)):
            if value is not None and value <= 0:
                identities.append(f"{ticker}: {name} is not positive ({value:g})")
        if revenue not in (None, 0) and net_income is not None:
            margin = net_income / revenue
            if not -1 <= margin <= 1:
                margin_outliers.append(f"{ticker}: profit margin {margin:.1%}")
        pe = pe_ratio(prices[ticker], values["EarningsPerShareDiluted"]) if ticker in prices else None
        if pe is not None and not -200 <= pe <= 200:
            pe_outliers.append(f"{ticker}: P/E {pe:.2f}")
        for measure, value in values.items():
            if MEASURES[measure]["kind"] != "flow":
                continue
            _, prior = _ttm_pair(_points(entry, measure), as_of)
            if value is not None and prior not in (None, 0) and abs(value) > 10 * abs(prior):
                ttm_outliers.append(f"{ticker}: {measure} TTM {value:g} is over 10x prior year {prior:g}")
    return Audit(len(companies), coverage, identities, pe_outliers, margin_outliers, ttm_outliers)


def crosscheck_rows(document: dict, prices: dict[str, float], as_of: str) -> list[tuple[str, float | None, float | None, float | None]]:
    """Return the stable human-review set of EPS, revenue, and P/E values."""
    rows = []
    for ticker in CROSSCHECK_TICKERS:
        entry = document.get("tickers", {}).get(ticker, {})
        eps = compute_ttm(_points(entry, "EarningsPerShareDiluted"), as_of)
        revenue = compute_ttm(_points(entry, "Revenues"), as_of)
        rows.append((ticker, eps, revenue, pe_ratio(prices[ticker], eps) if ticker in prices else None))
    return rows


def format_report(audit: Audit, document: dict, prices: dict[str, float], as_of: str) -> str:
    lines = [f"fundamentals audit as of {as_of}", f"companies: {audit.companies}", "coverage:"]
    for measure, count in audit.coverage.items():
        percentage = count / audit.companies if audit.companies else 0
        flag = "  UNDER 90%" if percentage < 0.9 else ""
        lines.append(f"  {measure}: {count}/{audit.companies} ({percentage:.1%}){flag}")
    for title, values in (("identity violations", audit.identity_violations), ("P/E outliers", audit.pe_outliers),
                          ("profit-margin outliers", audit.margin_outliers), ("TTM growth outliers", audit.ttm_outliers)):
        lines.append(f"{title}: {len(values)}")
        lines.extend(f"  {value}" for value in values)
    lines.extend(["cross-check (P/E is n/a unless --price is supplied):", "  ticker       TTM EPS     TTM revenue            P/E"])
    for ticker, eps, revenue, pe in crosscheck_rows(document, prices, as_of):
        lines.append(f"  {ticker:<6} {eps if eps is not None else 'n/a':>11} {revenue if revenue is not None else 'n/a':>15} {pe if pe is not None else 'n/a':>14}")
    return "\n".join(lines)


def _parse_prices(values: list[str]) -> dict[str, float]:
    prices = {}
    for value in values:
        ticker, separator, price = value.partition("=")
        if not separator or not ticker or not price:
            raise ValueError(f"invalid price {value!r}; use TICKER=PRICE")
        prices[ticker.upper()] = float(price)
    return prices


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=DATA_PATH)
    parser.add_argument("--as-of", help="YYYY-MM-DD; defaults to the file generation date")
    parser.add_argument("--price", action="append", default=[], metavar="TICKER=PRICE")
    args = parser.parse_args(argv)
    document = json.loads(args.data.read_text(encoding="utf-8"))
    as_of = args.as_of or str(document["generated_at"])[:10]
    prices = _parse_prices(args.price)
    audit = audit_document(document, as_of, prices)
    print(format_report(audit, document, prices, as_of))
    return 1 if audit.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
