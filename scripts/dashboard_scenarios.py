#!/usr/bin/env python3
"""Generate synthetic dashboard states and serve the site against one.

The dashboard has only ever been rendered against today's data, which is a
nearly-empty portfolio. Every other state it will reach - a mature book, a
degraded run, hostile text written by an LLM - is untested until the day it
happens live. This builds those states now.

    python scripts/dashboard_scenarios.py --list
    python scripts/dashboard_scenarios.py mature --serve 8100

Serving copies index.html and assets/ into a temp directory alongside the
scenario's data/, so nothing in the repo is touched.
"""

from __future__ import annotations

import argparse
import functools
import http.server
import json
import shutil
import socketserver
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 9, 30, 20, 30, tzinfo=UTC)


def iso(dt): return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _positions(specs, total):
    out = []
    for tick, name, mv, plpct, thesis, risks, business in specs:
        out.append({
            "ticker": tick, "name": name,
            "qty": round(mv / 100, 6), "avg_entry_price": 100.0,
            "current_price": round(100 * (1 + plpct), 2),
            "market_value": mv, "weight": round(mv / total, 4),
            "unrealized_pl": round(mv * plpct, 2), "unrealized_pl_pct": plpct,
            "opened_at": "2026-09-01T20:05:00Z" if thesis else None,
            "thesis": thesis, "risks": risks, "business": business,
        })
    return out


def _state(positions, cash, *, inception=True, health=None, generated=None, ret=None):
    """Build a state document.

    ``ret`` is the portfolio return the history series ends on. The inception
    value is DERIVED from it, so state and history agree - the first draft
    hardcoded a $100k inception against a $48.6k book and the page dutifully
    reported -51% beside a chart showing +3.66%.
    """
    invested = round(sum(p["market_value"] for p in positions), 2)
    total = round(invested + cash, 2)
    for p in positions:
        p["weight"] = round(p["market_value"] / total, 4)
    ret = 0.0 if ret is None else ret
    inception_value = round(total / (1 + ret), 2)
    bench_ret = round(ret * 0.6, 4)
    return {
        "schema_version": 1,
        "generated_at": iso(generated or NOW),
        "market_data_as_of": iso((generated or NOW) - timedelta(minutes=15)),
        "currency": "USD",
        "run": {"id": "scenario", "trigger": "schedule", "workflow": "update-state"},
        "account": {"cash": cash, "equity": total, "buying_power": round(total * 4, 2),
                    "status": "ACTIVE"},
        "totals": {"total_value": total, "invested_value": invested,
                   "cash_weight": round(cash / total, 4), "position_count": len(positions),
                   "committed_cash": 0.0, "available_cash": cash},
        "positions": positions, "pending_orders": [],
        "performance": ({"inception_date": "2026-07-17", "inception_value": inception_value,
                         "total_return_pct": round(ret, 4)} if inception else None),
        "benchmark": ({"ticker": "SPY", "inception_price": 771.10,
                       "current_price": round(771.10 * (1 + bench_ret), 2),
                       "total_return_pct": bench_ret,
                       "difference_pct": round(ret - bench_ret, 4)} if inception else None),
        "health": health or {"ok": True, "warnings": []},
    }


def _history(days, *, returns=True):
    rows, p, b = [], 0.0, 0.0
    seed = 11
    for i in range(days):
        seed = (seed * 1103515245 + 12345) & 0x7FFFFFFF
        r = seed / 0x7FFFFFFF - 0.47
        p += r * 0.6 + 0.05
        b += r * 0.4 + 0.03
        d = (NOW - timedelta(days=days - i)).date()
        if d.weekday() >= 5:
            continue
        rows.append({"date": d.isoformat(),
                     "portfolio_value": round(100000 * (1 + p / 100), 2),
                     "portfolio_return_pct": round(p / 100, 4) if returns else None,
                     "benchmark_price": round(771.10 * (1 + b / 100), 2),
                     "benchmark_return_pct": round(b / 100, 4) if returns else None,
                     "cash": 5000.0})
    return {"schema_version": 1, "rows": rows}


MATURE_SPECS = [
    ("MSFT", "Microsoft Corporation Common Stock", 6400.0, 0.031,
     "Dominant enterprise software footprint combined with cloud leadership.",
     "Valuation compression during tech pullbacks; Azure deceleration.",
     "Enterprise software and cloud infrastructure, sold to businesses on multi-year contracts."),
    ("NVDA", "NVIDIA Corporation Common Stock", 6800.0, 0.094,
     "Data-centre demand is supply-constrained, and guidance assumes no China contribution.",
     "Customer concentration; any easing of supply compresses pricing fast.",
     "Designs the accelerator chips that train and run AI models."),
    ("BRK.B", "Berkshire Hathaway Inc Class B", 6300.0, 0.008,
     "Insurance float invested at a cost of capital nobody else can match.",
     "Succession; the size of the balance sheet limits what can move the needle.",
     "Insurance, railroads, energy and a large equity portfolio."),
    ("UNH", "UnitedHealth Group Inc", 4700.0, -0.248,
     "Managed-care cost ratios normalising from an elevated base.",
     "Regulatory intervention on pricing is a step change, not a gradual one.",
     "US health insurer, and through Optum also a provider of care."),
    ("XOM", "Exxon Mobil Corporation", 13200.0, 0.121,
     "Low-cost Permian and Guyana barrels underpin free cash flow below strip pricing.",
     "Sustained crude weakness; policy pressure on long-cycle projects.",
     "Integrated oil and gas: extraction, refining and chemicals."),
    ("PG", "Procter & Gamble Company", 6100.0, -0.014, None, None, None),
]

HOSTILE_SPECS = [
    ("EVIL", "<script>alert('name')</script>", 6300.0, 0.02,
     "<img src=x onerror=\"alert('thesis')\">Thesis with an injection attempt.",
     "Risk field with <b>bold</b> and an <a href='#'>anchor</a> that must not render.",
     "<script>document.body.innerHTML='pwned'</script>"),
    ("LONG", "A Company With An Extremely Long Legal Name Incorporated Under The Laws Of Delaware "
             "And Trading Under Several Share Classes Limited", 6300.0, 0.01,
     "A thesis of unreasonable length. " * 40,
     "Risks, similarly overlong. " * 40,
     "Business description that will not stop. " * 40),
    ("TINY", "Rounding Edge Corp", 0.004, -0.9999, "Sub-cent position.", "Rounds to zero.", None),
    ("HUGE", "Very Large Position Inc", 88000.0, 3.5,
     "Deliberately over the 12% concentration threshold to check the bar renders.",
     "This should look wrong, and the page should still be readable.", None),
]


def build(name):
    if name == "mature":
        hist = _history(75)
        r = hist["rows"][-1]["portfolio_return_pct"]
        return (_state(_positions(MATURE_SPECS, 48500), 5100.0, ret=r), hist,
                json.loads(json.dumps(DECISIONS)))
    if name == "hostile":
        hist = _history(30)
        return (_state(_positions(HOSTILE_SPECS, 100000), 5000.0,
                       ret=hist["rows"][-1]["portfolio_return_pct"]), hist, HOSTILE_DECISIONS)
    if name == "degraded":
        hist = _history(75)
        return (_state(_positions(MATURE_SPECS, 48500), 5100.0,
                       ret=hist["rows"][-1]["portfolio_return_pct"],
                       generated=NOW - timedelta(hours=52),
                       health={"ok": False, "warnings": [
                           "Market data is 61.4h old (>26h): SPY last traded 2026-09-28T20:00:00Z",
                           "Alpaca account status is 'ACCOUNT_UPDATED', not ACTIVE"]}),
                hist, DECISIONS)
    if name == "one-day":
        return (_state(_positions(MATURE_SPECS[:2], 13200), 5000.0), _history(1), None)
    if name == "no-history":
        return (_state(_positions(MATURE_SPECS[:2], 13200), 5000.0), {"schema_version": 1, "rows": []}, None)
    raise SystemExit(f"unknown scenario: {name}")


DECISIONS = {
    "schema_version": 1, "cycle_id": "2026-09-25-weekly",
    "decided_at": "2026-09-25T20:30:00Z", "portfolio_value_at_decision": 53600.0,
    "commentary": "Six positions, cash at the floor. UNH is 24.8% below entry and within "
                  "reach of the stop; the thesis has not broken, so it is held rather than "
                  "cut. XOM has run to 24.6% of the book and is trimmed back to target.",
    "decisions": [
        {"ticker": "XOM", "action": "TRIM", "target_weight": 0.063, "notional": 6900.0,
         "thesis": "Trimming a position that outgrew its weight.", "risks": "Selling a winner early.",
         "reason_for_action": "Exceeds the 12% concentration threshold.",
         "trigger": "concentration_trim", "status": "executed",
         "order_id": "abc-123", "rejection_reason": None},
        {"ticker": "PG", "action": "HOLD", "target_weight": 0.063, "notional": None,
         "thesis": "Volume has stopped declining while pricing holds.",
         "risks": "Private-label share gains.", "reason_for_action": "Thesis intact, no action.",
         "trigger": "ai", "status": "skipped", "order_id": None, "rejection_reason": None},
        {"ticker": "TSLA", "action": "BUY", "target_weight": 0.063, "notional": 3400.0,
         "thesis": "Rejected before submission.", "risks": "n/a", "reason_for_action": "n/a",
         "trigger": "ai", "status": "rejected", "order_id": None,
         "rejection_reason": "cash_floor: would leave cash at 3.6%, below the 5% floor"},
        {"ticker": "GME", "action": "BUY", "target_weight": 0.063, "notional": 3400.0,
         "thesis": "Rejected before submission.", "risks": "n/a", "reason_for_action": "n/a",
         "trigger": "ai", "status": "rejected", "order_id": None,
         "rejection_reason": "universe: ticker 'GME' is outside the configured universe"},
    ],
    "considered": [{"ticker": t, "verdict": v} for t, v in [
        ("VOO", "Omitted to avoid duplicate core US large-cap exposure alongside SPY."),
        ("EEM", "Preferred VWO for the emerging market sleeve."),
        ("TLT", "Duration risk not wanted at this point in the cycle."),
    ]],
}

HOSTILE_DECISIONS = {
    "schema_version": 1, "cycle_id": "2026-09-25-weekly",
    "decided_at": "2026-09-25T20:30:00Z", "portfolio_value_at_decision": 100000.0,
    "commentary": "<script>alert('commentary')</script>Commentary containing an injection attempt.",
    "decisions": [
        {"ticker": "<b>XSS</b>", "action": "BUY", "target_weight": 0.063, "notional": 6300.0,
         "thesis": "x", "risks": "x", "reason_for_action": "x", "trigger": "ai",
         "status": "rejected", "order_id": None,
         "rejection_reason": "<img src=x onerror=\"alert('reason')\">malformed"},
    ],
    "considered": [{"ticker": "<i>tag</i>", "verdict": "<script>alert('verdict')</script>"}],
}

SCENARIOS = ["mature", "hostile", "degraded", "one-day", "no-history"]


def serve(name, port):
    state, history, decisions = build(name)
    tmp = Path(tempfile.mkdtemp(prefix=f"dash-{name}-"))
    shutil.copy(REPO / "index.html", tmp)
    shutil.copytree(REPO / "assets", tmp / "assets")
    (tmp / "data" / "decisions").mkdir(parents=True)
    (tmp / "data" / "state.json").write_text(json.dumps(state, indent=2), encoding="utf-8")
    (tmp / "data" / "history.json").write_text(json.dumps(history, indent=2), encoding="utf-8")
    if decisions is not None:
        (tmp / "data" / "decisions" / "latest.json").write_text(
            json.dumps(decisions, indent=2), encoding="utf-8")

    print(f"scenario : {name}")
    print(f"positions: {len(state['positions'])}  history rows: {len(history['rows'])}"
          f"  decisions: {'yes' if decisions else 'none (404 expected)'}")
    print(f"serving  : http://localhost:{port}/   (ctrl-c to stop)")
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(tmp))
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("", port), handler) as httpd:
        httpd.serve_forever()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("scenario", nargs="?", choices=SCENARIOS)
    ap.add_argument("--serve", type=int, default=8100)
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()
    if a.list or not a.scenario:
        print("scenarios:")
        for s in SCENARIOS:
            print("  ", s)
        raise SystemExit(0)
    serve(a.scenario, a.serve)
