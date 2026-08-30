"""Drive a fake market through the real pipeline, checking invariants daily.

Never imports src.portfolio.alpaca. Only the market and broker are fake -
every rule, validation and state transition is production code.

    python -m sim.run --days 250 --scenario crash --seed 7
    python -m sim.run --days 250 --scenario calm --out sim-out/
"""

from __future__ import annotations

import argparse
import collections
import datetime
import json
from pathlib import Path

from sim.ai_stub import propose
from sim.broker import FakeBroker
from sim.invariants import check
from sim.market import Market
from src.portfolio.decisions import read_active_records, write_cycle
from src.portfolio.executor import execute
from src.portfolio.report import build_report
from src.portfolio.state import build_history_row, build_state
from src.portfolio.storage import append_history_row, write_json_atomic
from src.portfolio.triggers import mechanical_decisions

REPO = Path(__file__).resolve().parents[1]

# The REAL rules. A simulation against invented rules tests nothing: an earlier
# draft hardcoded position_count.minimum = 0, which silently disabled the very
# guardrail the run was supposed to exercise.
RULES = json.loads((REPO / "config" / "rules.json").read_text(encoding="utf-8"))

# Wide enough that the target position count is actually reachable. An earlier
# draft used 8 tickers against a 15-position target, so the portfolio could
# never be built and the run "passed" by never doing anything.
TICKERS = [
    # The bond sleeve must exist here or nothing can be bought at all: a buy
    # into the risk sleeve is rejected while bonds sit below their floor, so a
    # shares-only universe makes the portfolio impossible to build. The
    # simulator found that itself the first time the sleeve rule ran - 750
    # rejections, all the same reason, nothing ever executed.
    "IEF", "AGG", "TLT",
    "MSFT", "NVDA", "AAPL", "GOOGL", "AMZN", "META", "JPM", "XOM", "PG", "KO",
    "V", "HD", "CAT", "MRK", "CVX", "ABT", "LIN", "MCD", "COST", "LLY",
    "ADBE", "ORCL", "CRM", "PEP", "TMO",
]
BENCHMARK = "SPY"


def simulate(days, scenario, seed, out=None, verbose=False):
    market = Market(TICKERS + [BENCHMARK], seed, scenario)
    broker = FakeBroker(100000.0, market)
    history = {"schema_version": 1, "rows": []}
    decisions_dir = Path(out) / "decisions" if out else None
    if decisions_dir:
        decisions_dir.mkdir(parents=True, exist_ok=True)

    inception = None
    submitted = filled_before = 0
    reasons = collections.Counter()
    notes = set()
    triggers = collections.Counter()
    actions = collections.Counter()
    cycles = 0
    state = None

    for _ in range(days):
        day = market.advance()
        broker.settle()

        account, positions = broker.account(), broker.positions()
        pending = [{
            "symbol": o["symbol"], "side": o["side"], "notional": o["notional"],
            "qty": None, "status": o["status"],
            "submitted_at": f"{day}T00:00:00Z", "order_id": o["order_id"],
        } for o in broker.open_orders()]

        bench = market.price(BENCHMARK) or 1.0
        records = read_active_records(decisions_dir, [p["symbol"] for p in positions]) \
            if decisions_dir else {}

        state = build_state(
            account, positions, bench, f"{day}T20:00:00Z", RULES, inception,
            f"{day}T21:00:00Z",
            {"id": str(day), "trigger": "simulation", "workflow": "sim"},
            pending_orders=pending, active_records=records,
        )
        row = build_history_row(state, bench)
        history["rows"] = [r for r in history["rows"] if r["date"] != row["date"]] + [row]

        problems, day_notes = check(state, history, RULES, day)
        notes.update(n.split(': ', 1)[1] for n in day_notes)
        _guard(problems, day, state, None)

        if day.weekday() != 4:          # decisions run weekly, after Friday's close
            continue

        cycles += 1
        triggered = mechanical_decisions(state, RULES)
        ai = propose(state, RULES, [t for t in TICKERS if t not in {d['ticker'] for d in triggered}], {t: r.get("thesis") for t, r in records.items()}, "valid")

        def submit(*, ticker, side, notional):
            nonlocal submitted
            submitted += 1
            return broker.submit(ticker, side, notional)

        def close(*, ticker):
            # Close the position, as production does with DELETE /v2/positions.
            #
            # This used to submit a notional sell of the position's market
            # value. The comment here said that always worked in the fake
            # broker because it has no price drift - which was wrong. Market
            # value is rounded to the cent, so the sell settled into slightly
            # fewer shares than were held and left fractional dust that never
            # died. A 2025 replay sold Apple five times before this was found.
            return broker.close(ticker)

        result = execute(triggered + ai["decisions"], state, RULES, TICKERS, False,
                         submit=submit, close=close)

        for item in result:
            actions[item["status"]] += 1
            if item.get("trigger") in ("stop_loss", "concentration_trim"):
                triggers[(item["trigger"], item["status"])] += 1
            if item["status"] == "rejected":
                reasons[(item.get("rejection_reason") or "unknown").split(":")[0]] += 1

        if decisions_dir:
            write_cycle(decisions_dir / f"{day}.json", cycle_id=f"{day}-weekly",
                        decided_at=f"{day}T21:00:00Z", state=state,
                        ai_output=ai, executed=result)

        # Inception is stamped the first time the system's OWN orders leave it
        # holding something - matching the production rule, and the reason
        # Luke's manual test trades must never trigger it.
        if inception is None and any(i["status"] == "executed" for i in result):
            filled_before = len(positions)
        if inception is None and filled_before is not None and positions and len(positions) > 0 \
                and any(i["status"] == "executed" for i in result):
            inception = {"inception_date": str(day), "inception_value": state["totals"]["total_value"],
                         "benchmark_ticker": BENCHMARK, "benchmark_inception_price": bench}

        problems, day_notes = check(state, history, RULES, day)
        notes.update(n.split(': ', 1)[1] for n in day_notes)
        _guard(problems, day, state, result)

    subject, body = build_report(state, history, None)

    print(f"days simulated : {days}   scenario: {scenario}   seed: {seed}")
    print(f"decision cycles: {cycles}")
    print(f"orders submitted: {submitted}")
    print(f"outcomes       : {dict(actions)}")
    print(f"final positions: {state['totals']['position_count']}   "
          f"cash {state['totals']['cash_weight']:.1%}   "
          f"value ${state['totals']['total_value']:,.2f}")
    print(f"inception      : {'stamped ' + inception['inception_date'] if inception else 'NOT STAMPED'}")
    print("mechanical triggers:")
    if triggers:
        for (trig, status), count in sorted(triggers.items()):
            print(f"   {trig + ' (' + status + ')':<44} {count}")
    else:
        print("   none")
        print("   WARNING: neither the stop loss nor the concentration trim fired.")
        print("   Either the market was too gentle, or they are not wired in.")
    print("rejections by reason:")
    if reasons:
        for reason, count in reasons.most_common():
            print(f"   {reason:<44} {count}")
    else:
        print("   none")
        print("   WARNING: no guardrail rejected anything in "
              f"{cycles} cycles. This run is not evidence that they work.")
    if not actions.get("executed"):
        print("   WARNING: nothing was ever executed. The trading path was not exercised.")
    if notes:
        print("observations (not failures):")
        for n in sorted(notes)[:5]:
            print(f"   {n}")
    print(f"report subject : {subject}")

    if out:
        dest = Path(out)
        write_json_atomic(dest / "state.json", state)
        write_json_atomic(dest / "history.json", history)
        print(f"written        : {dest}/")
    return 0


def _guard(violations, day, state, result):
    if not violations:
        return
    print(f"\nINVARIANT VIOLATION on {day}")
    for v in violations:
        print(f"  - {v}")
    print("\nstate:")
    print(json.dumps(state, indent=2)[:2000])
    if result:
        print("\ndecisions that led here:")
        print(json.dumps(result, indent=2)[:2000])
    raise SystemExit(1)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=250)
    ap.add_argument("--scenario", default="calm")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--out")
    a = ap.parse_args()
    raise SystemExit(simulate(a.days, a.scenario, a.seed, a.out))
