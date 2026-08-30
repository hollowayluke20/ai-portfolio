"""Fetch SEC company facts and atomically refresh data/fundamentals.json."""

from __future__ import annotations

import datetime
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.portfolio.config import load_universe  # noqa: E402
from src.portfolio.fundamentals import MEASURES, refresh_fundamentals  # noqa: E402


DATA_PATH = Path(__file__).resolve().parents[1] / "data" / "fundamentals.json"


def _coverage(tickers: dict[str, dict]) -> dict[str, int]:
    return {
        name: sum(bool(entry["measures"].get(name, {}).get("points")) for entry in tickers.values())
        for name in MEASURES
    }


def main() -> int:
    requested = load_universe()
    tickers = refresh_fundamentals(requested)
    output = {
        "schema_version": 1,
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z"),
        "tickers": tickers,
    }
    DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = DATA_PATH.with_suffix(".tmp")
    temporary.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    temporary.replace(DATA_PATH)

    no_cik = sum(entry["cik"] is None for entry in tickers.values())
    coverage = _coverage(tickers)
    companies = len(tickers) - no_cik
    print(f"tickers kept: {len(tickers)}")
    print(f"tickers with no CIK: {no_cik}")
    print(f"companies fetched: {companies}")
    print("per-measure coverage:")
    for name, count in coverage.items():
        print(f"  {name}: {count}/{companies} ({count / companies:.1%})")
    print(f"written: {DATA_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
