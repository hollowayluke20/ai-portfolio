#!/usr/bin/env python3
"""One fixed scorecard per backtest, so runs can be compared rather than
described.

Without this, each run gets summarised by whatever caught the reader's eye,
and Tuesday's observation cannot be set against Thursday's. The measures here
are deliberately the same every time and deliberately NOT about returns.

    python scripts/scorecard.py data/backtests/<dir> [more dirs...]

Returns are printed but must not be read as skill: the model's training
covers every window available here, so it may simply remember how they ended.
What IS testable is behaviour - whether the allocation moves, whether the
guardrails hold, whether it churns, and whether it reasons from evidence.
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
BONDS = set(json.loads((REPO / "config" / "rules.json").read_text(
    encoding="utf-8"))["sleeves"]["bond"]["tickers"])

NUMERIC = tuple("0123456789")


def sleeves_at(cycle):
    """Bond and risk weight the cycle was steering towards."""
    bond = risk = 0.0
    for d in cycle.get("decisions") or []:
        if d.get("action") in {"BUY", "TRIM", "HOLD"} and d.get("status") != "rejected":
            w = d.get("target_weight")
            if isinstance(w, (int, float)):
                (bond if d["ticker"] in BONDS else risk).__class__  # noqa
                if d["ticker"] in BONDS:
                    bond += w
                else:
                    risk += w
    return bond, risk


def score(out_dir: Path) -> dict:
    log = json.loads((out_dir / "log.json").read_text(encoding="utf-8"))
    hist = json.loads((out_dir / "history.json").read_text(encoding="utf-8"))

    executed = [d for c in log for d in (c.get("decisions") or [])
                if d.get("status") == "executed"]
    rejected = [d for c in log for d in (c.get("decisions") or [])
                if d.get("status") == "rejected"]

    sells = [d for d in executed if d["action"] in {"SELL", "TRIM"}]
    stop_sells = [d for d in sells if d.get("trigger")]
    judged = [d for d in sells if not d.get("trigger")]

    theses = [d.get("thesis") or "" for d in executed if d["action"] == "BUY"]
    cited = sum(1 for t in theses if any(ch in t for ch in NUMERIC))

    allocs = [sleeves_at(c) for c in log if c.get("decisions")]
    allocs = [(b, r) for b, r in allocs if b + r > 0.2]     # ignore empty cycles

    values = [h["value"] for h in hist]
    peak, dd = values[0], 0.0
    for v in values:
        peak = max(peak, v)
        dd = min(dd, v / peak - 1)
    spy = [h["spy"] for h in hist if h.get("spy")]
    speak, sdd = (spy[0], 0.0) if spy else (1, 0.0)
    for v in spy:
        speak = max(speak, v)
        sdd = min(sdd, v / speak - 1)

    weeks = max(1, len(log))
    return {
        "window": f"{hist[0]['date']} -> {hist[-1]['date']}",
        "cycles": len(log),
        "alloc_first": allocs[0] if allocs else None,
        "alloc_last": allocs[-1] if allocs else None,
        "bond_range": (min(b for b, _ in allocs), max(b for b, _ in allocs)) if allocs else None,
        "trades_per_week": len(executed) / weeks,
        "sells_judged": len(judged),
        "sells_forced": len(stop_sells),
        "sell_basis": Counter(d.get("basis") or "?" for d in judged),
        "rejections": Counter((d.get("rejection_reason") or "?").split(" -")[0][:46]
                              for d in rejected),
        "theses_citing_a_figure": f"{cited}/{len(theses)}" if theses else "0/0",
        "return_pct": (values[-1] / values[0] - 1) * 100,
        "spy_pct": (spy[-1] / spy[0] - 1) * 100 if spy else None,
        "max_drawdown_pct": dd * 100,
        "spy_drawdown_pct": sdd * 100,
    }


def show(name, s):
    print(f"\n{'=' * 78}\n{name}   {s['window']}   {s['cycles']} cycles\n{'=' * 78}")
    fa, la = s["alloc_first"], s["alloc_last"]
    if fa and la:
        print(f"  allocation     bonds {fa[0]:.0%} -> {la[0]:.0%}    "
              f"risk {fa[1]:.0%} -> {la[1]:.0%}    "
              f"bond range {s['bond_range'][0]:.0%}-{s['bond_range'][1]:.0%}")
    print(f"  selling        {s['sells_judged']} on judgement, "
          f"{s['sells_forced']} forced by a trigger    {dict(s['sell_basis'])}")
    print(f"  churn          {s['trades_per_week']:.1f} trades per cycle")
    print(f"  theses citing a figure   {s['theses_citing_a_figure']}")
    print(f"  drawdown       portfolio {s['max_drawdown_pct']:+.1f}%   "
          f"SPY {s['spy_drawdown_pct']:+.1f}%")
    print(f"  return         portfolio {s['return_pct']:+.1f}%   "
          f"SPY {s['spy_pct']:+.1f}%   (contaminated - behaviour only)")
    if s["rejections"]:
        print("  guardrails fired:")
        for reason, n in s["rejections"].most_common(4):
            print(f"     {n:>3}x  {reason}")


def main(dirs):
    for d in dirs:
        p = Path(d)
        if not (p / "log.json").exists():
            print(f"skipping {d}: no log.json")
            continue
        show(p.name, score(p))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:] or ["data/backtests/drawdown25b"]))
