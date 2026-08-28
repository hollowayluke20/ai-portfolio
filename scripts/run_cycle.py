#!/usr/bin/env python3
"""Run one investment decision cycle.

DRY RUN BY DEFAULT. Nothing is submitted to the broker unless --live is passed
explicitly. The full cycle still runs - real market data, a real AI call, real
validation, a real decision file - so the output can be read by a human before
any money moves.

    python scripts/run_cycle.py           # dry run, submits nothing
    python scripts/run_cycle.py --live    # submits orders

Exit codes: 0 success, 1 failure.
"""

from __future__ import annotations

import argparse
import datetime
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.portfolio import alpaca, decisions as dec, executor, state as state_mod  # noqa: E402
from src.portfolio.ai import propose                                              # noqa: E402
from src.portfolio.candidates import select_candidates                            # noqa: E402
from src.portfolio.config import load_inception, load_rules, load_universe        # noqa: E402
from src.portfolio.storage import read_json                                       # noqa: E402

REPO = Path(__file__).resolve().parents[1]
STATE_PATH = REPO / "data" / "state.json"
DECISIONS_DIR = REPO / "data" / "decisions"
BENCHMARK = "SPY"


def main(live: bool) -> int:
    now = datetime.datetime.now(datetime.UTC)
    decided_at = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    cycle_date = now.date().isoformat()

    # State is rebuilt fresh rather than read from disk: a decision must never
    # be made against a stale file (ADR 0002).
    account = alpaca.get_account()
    positions = alpaca.get_positions()
    pending = alpaca.get_orders(status="open")
    spy_price, spy_as_of = alpaca.get_latest_price(BENCHMARK)
    rules = load_rules()
    universe = load_universe()

    st = state_mod.build_state(
        account=account, positions=positions, pending_orders=pending,
        spy_price=spy_price, spy_as_of=spy_as_of, rules=rules,
        inception=load_inception(), generated_at=decided_at,
        run={"id": "cycle-" + cycle_date, "trigger": "manual" if not live else "live",
             "workflow": "run-cycle"},
    )

    held = [p["ticker"] for p in st["positions"]]
    week_index = now.isocalendar().week
    candidates = select_candidates(universe, held, week_index)
    theses = dec.read_active_theses(DECISIONS_DIR, held)

    print(f"cycle      : {cycle_date}  ({'LIVE' if live else 'DRY RUN'})")
    print(f"portfolio  : ${st['totals']['total_value']:,.2f}  "
          f"available ${st['totals']['available_cash']:,.2f}  "
          f"{st['totals']['position_count']} positions")
    print(f"candidates : {len(candidates)}")

    ai_output = propose(st, rules, candidates, theses)
    proposed = ai_output["decisions"]
    print(f"proposed   : {len(proposed)} decisions, "
          f"{len(ai_output.get('considered', []))} candidates considered")

    executed = executor.execute(proposed, st, rules, universe, dry_run=not live)

    # A dry run is a PREVIEW, not a decision. It must not write to the
    # immutable decision record (ADR 0004), both because nothing was decided
    # and because the immutability guard would block a second preview.
    out_dir = DECISIONS_DIR if live else (REPO / "data" / "dry-runs")
    out_path = out_dir / f"{cycle_date}.json"
    if not live and out_path.exists():
        out_path.unlink()          # previews are overwritable by design

    cycle = dec.write_cycle(
        out_path,
        cycle_id=f"{cycle_date}-weekly", decided_at=decided_at,
        state=st, ai_output=ai_output, executed=executed,
    )

    print()
    for d in executed:
        note = d.get("rejection_reason") or ""
        amount = f"${d['notional']:,.2f}" if d.get("notional") else ""
        print(f"  {d['action']:<5} {d['ticker']:<6} {amount:>12}  {d['status']:<9} {note}")
    print()
    print(f"written    : {out_path.relative_to(REPO)}")

    if not live:
        print()
        print("DRY RUN - nothing was submitted. Re-run with --live to place orders.")
    elif not load_inception() and any(d["status"] == "executed" for d in executed):
        print()
        print("First live orders submitted. Once they FILL, stamp the measurement")
        print("baseline with: python scripts/stamp_inception.py")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true",
                    help="actually submit orders (default is a dry run)")
    args = ap.parse_args()
    try:
        sys.exit(main(live=args.live))
    except Exception as exc:  # noqa: BLE001 - fail loud, place nothing
        print(f"run_cycle FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(1)
