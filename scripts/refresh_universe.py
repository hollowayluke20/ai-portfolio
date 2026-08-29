"""Build config/universe.json — the tradable ticker whitelist.

S&P 500 constituents + the ADR 0003 ETF sleeve, each cross-checked against
Alpaca's asset list and kept only if tradable AND fractionable. Fractionable
matters because ADR 0003 places notional (dollar-amount) orders, which Alpaca
only accepts on fractionable assets.

    python scripts/refresh_universe.py
"""

from __future__ import annotations

import csv
import datetime
import io
import json
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.portfolio import alpaca  # noqa: E402
from src.portfolio.config import RULES_PATH, UNIVERSE_PATH  # noqa: E402

SP500_CSV_URL = (
    "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/"
    "main/data/constituents.csv"
)

ETF_METADATA = {
    "SPY": {"name": "S&P 500 ETF", "sector": "Equity"},
    "VOO": {"name": "Vanguard S&P 500 ETF", "sector": "Equity"},
    "QQQ": {"name": "Invesco QQQ Trust", "sector": "Equity"},
    "VEA": {"name": "Vanguard FTSE Developed Markets ETF", "sector": "International Equity"},
    "EFA": {"name": "iShares MSCI EAFE ETF", "sector": "International Equity"},
    "VWO": {"name": "Vanguard FTSE Emerging Markets ETF", "sector": "International Equity"},
    "EEM": {"name": "iShares MSCI Emerging Markets ETF", "sector": "International Equity"},
    "IEF": {"name": "iShares 7-10 Year Treasury Bond ETF", "sector": "Bond"},
    "AGG": {"name": "iShares Core U.S. Aggregate Bond ETF", "sector": "Bond"},
    "TLT": {"name": "iShares 20+ Year Treasury Bond ETF", "sector": "Bond"},
    "GLD": {"name": "Gold", "sector": "Commodity"},
    "VNQ": {"name": "Vanguard Real Estate ETF", "sector": "Real Estate"},
    "REET": {"name": "iShares Global REIT ETF", "sector": "Real Estate"},
    "DBC": {"name": "Invesco DB Commodity Index Tracking Fund", "sector": "Commodity"},
    "USO": {"name": "United States Oil Fund", "sector": "Commodity"},
}


def fetch_sp500() -> tuple[list[str], dict[str, dict[str, str]]]:
    resp = requests.get(SP500_CSV_URL, timeout=30)
    resp.raise_for_status()
    reader = csv.DictReader(io.StringIO(resp.text))
    metadata = {row["Symbol"].strip(): {"name": row.get("Security", "").strip(), "sector": row.get("GICS Sector", "").strip()} for row in reader if row.get("Symbol")}
    return list(metadata), metadata


def main() -> int:
    rules = json.loads(RULES_PATH.read_text(encoding="utf-8"))
    etfs = list(rules["etf_universe"])

    sp500, metadata = fetch_sp500()
    metadata.update({ticker: ETF_METADATA[ticker] for ticker in etfs})
    # Alpaca uses '.' in class tickers (BRK.B); the dataset CSV uses the same.
    requested: list[str] = []
    seen: set[str] = set()
    for ticker in sp500 + etfs:
        if ticker not in seen:
            seen.add(ticker)
            requested.append(ticker)

    assets = {a["symbol"]: a for a in alpaca.list_assets()}

    kept: list[str] = []
    dropped: list[dict] = []
    for ticker in requested:
        asset = assets.get(ticker)
        if asset is None:
            dropped.append({"ticker": ticker, "reason": "not in Alpaca assets"})
        elif not asset["tradable"]:
            dropped.append({"ticker": ticker, "reason": "not tradable"})
        elif not asset["fractionable"]:
            dropped.append({"ticker": ticker, "reason": "not fractionable"})
        else:
            kept.append(ticker)

    output = {
        "schema_version": 2,
        "generated_at": datetime.datetime.now(datetime.timezone.utc)
        .isoformat()
        .replace("+00:00", "Z"),
        "source_url": SP500_CSV_URL,
        "etf_sleeve": etfs,
        "tickers": sorted(kept),
        "metadata": {ticker: metadata[ticker] for ticker in kept if ticker in metadata},
        "dropped": sorted(dropped, key=lambda d: d["ticker"]),
    }
    UNIVERSE_PATH.write_text(
        json.dumps(output, indent=2) + "\n", encoding="utf-8"
    )

    reasons: dict[str, int] = {}
    for d in dropped:
        reasons[d["reason"]] = reasons.get(d["reason"], 0) + 1

    print(f"fetched:  {len(requested)} tickers ({len(sp500)} S&P 500 + {len(etfs)} ETFs)")
    print(f"kept:     {len(kept)}")
    print(f"dropped:  {len(dropped)}")
    for reason, count in sorted(reasons.items()):
        print(f"            {count:>4}  {reason}")
    print(f"written:  {UNIVERSE_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
