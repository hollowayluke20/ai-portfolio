#!/usr/bin/env python3
"""Refresh data/state.json and append today's history row.

The Phase 1 entrypoint: the only place the broker layer and the state layer
meet. Read-only with respect to the portfolio — it cannot place an order.

Exit codes: 0 success, 1 failure (Actions marks the run red).
"""

from __future__ import annotations

import datetime
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.portfolio import alpaca, state, storage          # noqa: E402
from src.portfolio.config import load_inception, load_rules  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
STATE_PATH = REPO / "data" / "state.json"
HISTORY_PATH = REPO / "data" / "history.json"
BENCHMARK = "SPY"

# ADR 0004: the dashboard flags data older than this.
STALE_AFTER_HOURS = 26


def _utc_now() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


def _iso(dt: datetime.datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def main() -> int:
    generated_at = _utc_now()
    warnings: list[str] = []

    account = alpaca.get_account()
    positions = alpaca.get_positions()
    pending_orders = alpaca.get_orders()
    spy_price, spy_as_of = alpaca.get_latest_price(BENCHMARK)

    # Warn if the feed itself is stale. Distinct from the dashboard's own
    # staleness check, which measures how old this whole file is.
    as_of_dt = datetime.datetime.strptime(spy_as_of, "%Y-%m-%dT%H:%M:%SZ").replace(
        tzinfo=datetime.UTC
    )
    age_hours = (generated_at - as_of_dt).total_seconds() / 3600
    if age_hours > STALE_AFTER_HOURS:
        warnings.append(
            f"Market data is {age_hours:.1f}h old (>{STALE_AFTER_HOURS}h): "
            f"{BENCHMARK} last traded {spy_as_of}"
        )

    if account["status"] != "ACTIVE":
        warnings.append(f"Alpaca account status is {account['status']!r}, not ACTIVE")

    health = {"ok": not warnings, "warnings": warnings}

    doc = state.build_state(
        account=account,
        positions=positions,
        spy_price=spy_price,
        spy_as_of=spy_as_of,
        rules=load_rules(),
        inception=load_inception(),
        generated_at=_iso(generated_at),
        run={
            "id": uuid.uuid4().hex[:12],
            "trigger": "schedule" if len(sys.argv) > 1 and sys.argv[1] == "--scheduled" else "manual",
            "workflow": "update-state",
        },
        pending_orders=pending_orders,
        health=health,
    )

    # Assemble and validate fully in memory before touching disk (ADR 0004):
    # stale-but-correct beats fresh-but-broken.
    total = doc["totals"]["total_value"]
    weight_sum = sum(p["weight"] for p in doc["positions"]) + doc["totals"]["cash_weight"]
    if abs(weight_sum - 1.0) > 0.01:
        raise SystemExit(f"weights sum to {weight_sum:.4f}, not 1.0 - refusing to write")

    storage.write_json_atomic(STATE_PATH, doc)

    # History is one row per TRADING day, dated by the data (ADR 0004).
    row_date = datetime.date.fromisoformat(doc["market_data_as_of"][:10])
    if alpaca.is_trading_day(row_date):
        storage.append_history_row(
            HISTORY_PATH, state.build_history_row(doc, benchmark_price=spy_price)
        )
        history_note = f"history row written for {row_date}"
    else:
        history_note = f"{row_date} was not a trading day - history row skipped"

    print(f"state      : ${total:,.2f}  ({doc['totals']['position_count']} positions, "
          f"{doc['totals']['cash_weight']:.1%} cash)")
    committed = doc["totals"]["committed_cash"]
    print(f"pending    : {len(doc['pending_orders'])} orders, ${committed:,.2f} committed cash")
    if doc["totals"]["available_cash"] != doc["account"]["cash"]:
        print(f"available  : ${doc['totals']['available_cash']:,.2f} "
              f"(cash is ${doc['account']['cash']:,.2f})")
    print(f"benchmark  : {BENCHMARK} {spy_price} as of {spy_as_of}")
    print(f"{history_note}")
    print(f"health     : {'ok' if doc['health']['ok'] else 'DEGRADED'}")
    for w in doc["health"]["warnings"]:
        print(f"  warning: {w}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:            # noqa: BLE001 - fail loud, leave state intact
        print(f"update_state FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(1)
