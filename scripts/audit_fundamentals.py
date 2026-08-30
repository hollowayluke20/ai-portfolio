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

from src.portfolio.fundamentals import MEASURES, compute_ttm_pair, latest_instant, pe_ratio, summarise  # noqa: E402


DATA_PATH = Path(__file__).resolve().parents[1] / "data" / "fundamentals.json"
CROSSCHECK_TICKERS = ("AAPL", "MSFT", "NVDA", "JPM", "XOM", "KO", "UNH", "PG")

# These are reporting conventions, not targets to optimise.  Financial firms
# and property trusts legitimately lack gross profit and a classified current
# balance sheet, while the remaining SEC concepts should be broadly available.
COVERAGE_EXPECTATIONS = {
    "EarningsPerShareDiluted": 0.95,
    "Revenues": 0.95,
    "NetIncomeLoss": 0.95,
    "GrossProfit": 0.45,
    "NetCashProvidedByUsedInOperatingActivities": 0.95,
    "Assets": 0.95,
    "AssetsCurrent": 0.80,
    "LiabilitiesCurrent": 0.80,
    "LongTermDebtNoncurrent": 0.88,
    "CommonStockSharesOutstanding": 0.88,
}


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
            or any(
                count / self.companies < COVERAGE_EXPECTATIONS[measure]
                for measure, count in self.coverage.items()
            )
        ) if self.companies else True


def _points(entry: dict, measure: str) -> list[dict]:
    return entry.get("measures", {}).get(measure, {}).get("points", [])


def _ttm_pair(points: list[dict], as_of: str) -> tuple[float | None, float | None]:
    """Return the same two TTM windows used by the production summary."""
    return compute_ttm_pair(points, as_of)


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
            measure: (compute_ttm_pair(_points(entry, measure), as_of)[0]
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
    """Return P/E, revenue growth, and net margin for human comparison."""
    rows: list[tuple[str, float | None, float | None, float | None]] = []
    for ticker in CROSSCHECK_TICKERS:
        entry = document.get("tickers", {}).get(ticker, {})
        summary = summarise(entry, prices.get(ticker), as_of)
        rows.append((ticker, summary["pe"], summary["revenue_growth"], summary["net_margin"]))
    return rows


def format_report(audit: Audit, document: dict, prices: dict[str, float], as_of: str) -> str:
    lines = [f"fundamentals audit as of {as_of}", f"companies: {audit.companies}", "coverage:"]
    for measure, count in audit.coverage.items():
        percentage = count / audit.companies if audit.companies else 0
        expected = COVERAGE_EXPECTATIONS[measure]
        flag = "  BELOW EXPECTATION" if percentage < expected else ""
        lines.append(f"  {measure}: {count}/{audit.companies} ({percentage:.1%}; expect {expected:.0%}){flag}")
    for title, values in (("identity violations", audit.identity_violations), ("P/E outliers", audit.pe_outliers),
                          ("profit-margin outliers", audit.margin_outliers), ("TTM growth outliers", audit.ttm_outliers)):
        lines.append(f"{title}: {len(values)}")
        lines.extend(f"  {value}" for value in values)
    lines.extend(["cross-check (P/E is n/a unless --price is supplied):", "  ticker            P/E   revenue growth    net margin"])
    for ticker, pe, growth, margin in crosscheck_rows(document, prices, as_of):
        lines.append(
            f"  {ticker:<6} {pe if pe is not None else 'n/a':>12} "
            f"{f'{growth:.1%}' if growth is not None else 'n/a':>16} "
            f"{f'{margin:.1%}' if margin is not None else 'n/a':>13}"
        )
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
