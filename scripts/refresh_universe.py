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


def fetch_sp500() -> list[str]:
    resp = requests.get(SP500_CSV_URL, timeout=30)
    resp.raise_for_status()
    reader = csv.DictReader(io.StringIO(resp.text))
    return [row["Symbol"].strip() for row in reader if row.get("Symbol")]


def main() -> int:
    rules = json.loads(RULES_PATH.read_text(encoding="utf-8"))
    etfs = list(rules["etf_universe"])

    sp500 = fetch_sp500()
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
        "schema_version": 1,
        "generated_at": datetime.datetime.now(datetime.timezone.utc)
        .isoformat()
        .replace("+00:00", "Z"),
        "source_url": SP500_CSV_URL,
        "etf_sleeve": etfs,
        "tickers": sorted(kept),
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
