#!/usr/bin/env python3
"""Stamp the measurement baseline, once.

`save_inception()` existed in config.py, was unit-tested, and was called by
nothing. So inception was never stamped, `performance` and `benchmark` stayed
null forever, the dashboard would have said "not yet trading" after a year of
trading, and brief section 10's benchmark comparison would never have
activated.

Normally this runs automatically: `run_triggers.py` stamps the baseline the
first time it sees holdings that the SYSTEM opened. This script is the manual
override, for when that judgement is wrong or needs redoing.

    python scripts/stamp_inception.py            # show what would be stamped
    python scripts/stamp_inception.py --confirm  # write it
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.portfolio import alpaca                                    # noqa: E402
from src.portfolio.config import INCEPTION_PATH, load_inception, save_inception  # noqa: E402

BENCHMARK = "SPY"


def main(confirm: bool) -> int:
    existing = load_inception()
    if existing:
        print("Inception is already stamped and is never rewritten (ADR 0004):")
        for key, value in existing.items():
            print(f"  {key:<28} {value}")
        print("\nA baseline that can be silently changed is worse than no baseline.")
        print(f"To redo it deliberately, delete {INCEPTION_PATH} first.")
        return 0

    account = alpaca.get_account()
    positions = alpaca.get_positions()
    price, as_of = alpaca.get_latest_price(BENCHMARK)
    total = account["cash"] + sum(p["market_value"] for p in positions)

    baseline = {
        "inception_date": as_of[:10],
        "inception_value": round(total, 2),
        "benchmark_ticker": BENCHMARK,
        "benchmark_inception_price": price,
    }

    print("Would stamp:")
    for key, value in baseline.items():
        print(f"  {key:<28} {value}")
    print(f"\n  positions held             {len(positions)}")

    if not positions:
        print("\nWARNING: the portfolio holds nothing. Stamping now measures from a")
        print("100% cash position, so every day before the first trade counts as")
        print("cash drag against the benchmark, permanently.")

    if not confirm:
        print("\nNothing written. Re-run with --confirm to stamp it.")
        return 0

    save_inception(baseline)
    print(f"\nStamped. {INCEPTION_PATH} is now permanent.")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--confirm", action="store_true", help="actually write the baseline")
    args = ap.parse_args()
    try:
        sys.exit(main(confirm=args.confirm))
    except Exception as exc:  # noqa: BLE001
        print(f"stamp_inception FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(1)
