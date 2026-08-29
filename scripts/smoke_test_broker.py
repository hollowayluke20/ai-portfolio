#!/usr/bin/env python3
"""Prove the broker layer works, end to end, against the real Alpaca API.

MANUAL ONLY. Never wired into a workflow.

The problem this solves: `submit_notional_order` and `close_position` cannot be
unit-tested — mocking them only proves the mock works. Until 2026-08-29 the
only evidence they worked was that someone had run them once by hand, and when
they finally ran for real they failed twice: an invalid time_in_force, and a
full exit rejected for insufficient balance because a notional sell converts to
a quantity at submission time.

Crypto is the instrument, not a holding. It trades 24/7, so this runs on a
Saturday with the equity market shut. **Nothing is kept.** The position is
opened, inspected and closed within seconds, and ADR 0003 excludes crypto from
the investable universe entirely — a crypto holding must never survive this
script.

    python scripts/smoke_test_broker.py
    python scripts/smoke_test_broker.py --amount 50
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.portfolio import alpaca                              # noqa: E402
from src.portfolio.state import build_state                   # noqa: E402
from src.portfolio.config import load_rules                   # noqa: E402

PROBE = "BTC/USD"          # order symbol
PROBE_POSITION = "BTCUSD"  # the SAME asset, as positions report it
BENCHMARK = "SPY"

ok = True


def check(label, passed, detail=""):
    global ok
    ok = ok and passed
    print(f"  [{'pass' if passed else 'FAIL'}] {label}{'  ' + detail if detail else ''}")


def _crypto_positions():
    return [p for p in alpaca.get_positions() if p["symbol"] == PROBE_POSITION]


def main(amount: float) -> int:
    print(f"Broker smoke test - {PROBE}, ${amount:.2f}, opened and closed immediately.\n")

    if _crypto_positions():
        print(f"REFUSING TO RUN: a {PROBE_POSITION} position already exists.")
        print("A previous run did not clean up. Close it before testing again,")
        print("so this script never adds to a position it did not create.")
        return 1

    before = alpaca.get_account()
    print(f"cash before : ${before['cash']:,.2f}\n")

    opened = False
    try:
        order = alpaca.submit_notional_order(
            symbol=PROBE, side="buy", notional=amount, time_in_force="gtc")
        opened = True
        check("order accepted", bool(order.get("order_id")), order.get("status", ""))

        for _ in range(20):
            positions = _crypto_positions()
            if positions:
                break
            time.sleep(1)

        check("order filled and became a position", bool(positions))
        if not positions:
            return 1
        position = positions[0]

        check("quantity is fractional", 0 < position["qty"] < 1, f"{position['qty']}")
        check("company name resolved", bool(position.get("name")), position.get("name") or "")
        check("market value is near the amount ordered",
              abs(position["market_value"] - amount) < amount * 0.05,
              f"${position['market_value']:.2f}")

        during = alpaca.get_account()
        spent = before["cash"] - during["cash"]
        check("cash fell by roughly the amount ordered",
              abs(spent - amount) < amount * 0.05, f"${spent:.2f}")

        # The real question: does a live position survive the whole pipeline?
        price, as_of = alpaca.get_latest_price(BENCHMARK)
        state = build_state(
            account=during, positions=alpaca.get_positions(), pending_orders=[],
            spy_price=price, spy_as_of=as_of, rules=load_rules(), inception=None,
            generated_at=as_of, run={"id": "smoke", "trigger": "manual", "workflow": "smoke"},
        )
        weights = sum(p["weight"] for p in state["positions"]) + state["totals"]["cash_weight"]
        check("state builds with a live position", state["totals"]["position_count"] > 0)
        check("weights plus cash sum to 1.0", abs(weights - 1.0) < 0.01, f"{weights:.6f}")
        check("totals reconcile",
              abs(state["totals"]["total_value"]
                  - (during["cash"] + state["totals"]["invested_value"])) < 0.01)
        check("probe has no thesis, so it cannot stamp inception",
              not any(p.get("thesis") for p in state["positions"]
                      if p["ticker"] == PROBE_POSITION))

    finally:
        # Runs even if a check above raised. A leftover crypto position would
        # appear on the public dashboard and in Friday's email as a real
        # holding, and a decision cycle would see an asset it cannot explain.
        if opened:
            print()
            try:
                alpaca.close_position(PROBE_POSITION)
                for _ in range(20):
                    if not _crypto_positions():
                        break
                    time.sleep(1)
                check("position closed and gone", not _crypto_positions())
            except Exception as exc:  # noqa: BLE001
                check("position closed and gone", False, f"{type(exc).__name__}: {exc}")
                print(f"\n  !! CLOSE {PROBE_POSITION} BY HAND in the Alpaca dashboard !!")

    after = alpaca.get_account()
    drift = after["cash"] - before["cash"]
    check("cash returned to roughly where it started",
          abs(drift) < amount * 0.05, f"{drift:+.2f}")

    print(f"\ncash after  : ${after['cash']:,.2f}")
    print("\nALL CHECKS PASSED" if ok else "\nSOMETHING FAILED - read above")
    return 0 if ok else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--amount", type=float, default=25.0)
    args = ap.parse_args()
    try:
        sys.exit(main(args.amount))
    except Exception as exc:  # noqa: BLE001
        print(f"\nsmoke test FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        print(f"CHECK for a stray {PROBE_POSITION} position in Alpaca.", file=sys.stderr)
        sys.exit(1)
