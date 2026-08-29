#!/usr/bin/env python3
"""Check the mechanical sell triggers, daily.

The stop loss and the concentration trim are pure arithmetic on data we
already fetch - no AI call, no cost, no judgement. Running them only on the
weekly decision cycle made them far weaker than ADR 0003 claims: a holding
could fall 35% on a Tuesday and sit there until Friday evening.

The AI's decisions stay weekly. Thinking does not improve by doing it more
often against a 15-minute-delayed feed. Reacting to a position already past
its stop does.

DRY BY DEFAULT. Submitting requires --live, exactly like run_cycle.py.

    python scripts/run_triggers.py          # report only
    python scripts/run_triggers.py --live   # act

Exit codes: 0 success, 1 failure.
"""

from __future__ import annotations

import argparse
import datetime
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.portfolio import alpaca, decisions as dec, executor, state as state_mod  # noqa: E402
from src.portfolio.config import (load_inception, load_rules, load_universe,      # noqa: E402
                                  save_inception)                                # noqa: E402
from src.portfolio.storage import append_history_row, write_json_atomic           # noqa: E402
from src.portfolio.triggers import mechanical_decisions                           # noqa: E402

REPO = Path(__file__).resolve().parents[1]
STATE_PATH = REPO / "data" / "state.json"
HISTORY_PATH = REPO / "data" / "history.json"
DECISIONS_DIR = REPO / "data" / "decisions"
BENCHMARK = "SPY"
STALE_AFTER_HOURS = 26


def _now():
    return datetime.datetime.now(datetime.UTC)


def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _build(generated_at):
    """Assemble state from the broker. Rebuilt after trading so the file
    reflects the orders just placed rather than the world before them."""
    account = alpaca.get_account()
    positions = alpaca.get_positions()
    pending = alpaca.get_orders(status="open")
    price, as_of = alpaca.get_latest_price(BENCHMARK)
    rules = load_rules()

    warnings = []
    age = (generated_at - datetime.datetime.strptime(
        as_of, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=datetime.UTC)).total_seconds() / 3600
    if age > STALE_AFTER_HOURS:
        warnings.append(f"Market data is {age:.1f}h old (>{STALE_AFTER_HOURS}h)")
    if account["status"] != "ACTIVE":
        warnings.append(f"Alpaca account status is {account['status']!r}, not ACTIVE")

    held = [p["symbol"] for p in positions]
    st = state_mod.build_state(
        account=account, positions=positions, pending_orders=pending,
        spy_price=price, spy_as_of=as_of, rules=rules,
        inception=load_inception(), generated_at=_iso(generated_at),
        run={"id": uuid.uuid4().hex[:12], "trigger": "schedule", "workflow": "run-triggers"},
        active_records=dec.read_active_records(DECISIONS_DIR, held),
        health={"ok": not warnings, "warnings": warnings},
    )
    return st, rules


def _maybe_stamp_inception(state):
    """Stamp the baseline the first time the SYSTEM's own holdings exist.

    save_inception() sat unused for two days: defined, unit-tested, called by
    nothing. Inception would never have been stamped, so `performance` and
    `benchmark` would have stayed null forever - the dashboard saying "not yet
    trading" after a year of trading, and the benchmark comparison never
    activating at all.

    A position only counts if a decision record opened it. Luke's manual NVDA
    and MSTR trades have no record, so they cannot start the clock - measuring
    from a $24 test position would poison every future comparison.
    """
    if load_inception() or not state["positions"]:
        return
    if not any(p.get("thesis") for p in state["positions"]):
        return              # nothing here was opened by a system decision
    save_inception({
        "inception_date": state["market_data_as_of"][:10],
        "inception_value": state["totals"]["total_value"],
        "benchmark_ticker": BENCHMARK,
        "benchmark_inception_price": state["benchmark"]["current_price"]
        if state.get("benchmark") else None,
    })
    print(f"inception  : stamped at ${state['totals']['total_value']:,.2f} "
          f"({state['market_data_as_of'][:10]})")


def main(live: bool) -> int:
    now = _now()
    state, rules = _build(now)

    _maybe_stamp_inception(state)

    fired = mechanical_decisions(state, rules)

    print(f"checked    : {state['totals']['position_count']} positions, "
          f"${state['totals']['total_value']:,.2f}  ({'LIVE' if live else 'DRY RUN'})")

    if not fired:
        print("triggers   : none fired")
        _persist(state, live)
        return 0

    for decision in fired:
        print(f"  {decision['trigger']:<20} {decision['action']:<5} {decision['ticker']}")

    executed = executor.execute(fired, state, rules, load_universe(), dry_run=not live)
    for decision in executed:
        note = decision.get("rejection_reason") or ""
        print(f"  -> {decision['ticker']:<6} {decision['status']:<9} {note}")

    if live:
        # A stop that fires must appear in the permanent record, not only in a
        # log. Recorded under its own cycle id so it is distinguishable from a
        # weekly AI cycle when read back.
        day = now.date().isoformat()
        DECISIONS_DIR.mkdir(parents=True, exist_ok=True)
        path = DECISIONS_DIR / f"{day}-triggers.json"
        if not path.exists():
            dec.write_cycle(path, cycle_id=f"{day}-triggers", decided_at=_iso(now),
                            state=state, ai_output={"commentary":
                                "Mechanical triggers only. No AI decision this run.",
                                "decisions": fired, "considered": []},
                            executed=executed)
            print(f"recorded   : data/decisions/{path.name}")
        # Rebuild so state.json shows the orders just placed.
        state, _ = _build(_now())

    _persist(state, live)
    if not live:
        print("\nDRY RUN - nothing submitted. Re-run with --live to act.")
    return 0


def _persist(state, live):
    write_json_atomic(STATE_PATH, state)
    row_date = datetime.date.fromisoformat(state["market_data_as_of"][:10])
    if alpaca.is_trading_day(row_date):
        append_history_row(HISTORY_PATH, state_mod.build_history_row(
            state, state["benchmark"]["current_price"] if state.get("benchmark") else None))
        print(f"history    : row written for {row_date}")
    else:
        print(f"history    : {row_date} was not a trading day - skipped")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true",
                    help="actually submit the triggered orders (default is a dry run)")
    args = ap.parse_args()
    try:
        sys.exit(main(live=args.live))
    except Exception as exc:  # noqa: BLE001 - fail loud, place nothing
        print(f"run_triggers FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(1)
