#!/usr/bin/env python3
"""Attempt to break every guardrail, and report which ones actually fire.

A test suite proves the code that exists is correct. It says nothing about a
rule that was documented and never built - and this project has found five of
those: the stop loss, both halves of the concentration trim, the broad-equity
cap, and the cash ceiling. All were in the rules file, injected into the
prompt, and implemented nowhere.

So this does not test the code. It attacks it, once per rule, and asks a
single question each time: did anything stop me?

    python scripts/break_guardrails.py

Exits non-zero if any attack succeeded.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from src.portfolio.validator import validate_static, check_cash   # noqa: E402
from src.portfolio.triggers import mechanical_decisions           # noqa: E402

RULES = json.loads((REPO / "config" / "rules.json").read_text(encoding="utf-8"))
UNIVERSE = json.loads((REPO / "config" / "universe.json").read_text(encoding="utf-8"))

BONDS = RULES["sleeves"]["bond"]["tickers"]
RISK = ["SPY", "GLD", "DBC", "AAPL", "MSFT", "JPM", "XOM", "LLY", "COST",
        "CAT", "WMT", "JNJ"]


def state(weights: dict[str, float], cash: float | None = None) -> dict:
    """A portfolio holding exactly these weights."""
    invested = sum(weights.values())
    cash_w = 1.0 - invested if cash is None else cash
    return {
        "positions": [
            {"ticker": t, "weight": w, "market_value": 100_000 * w,
             "qty": 10.0, "unrealized_pl_pct": 0.0}
            for t, w in weights.items()
        ],
        "totals": {"total_value": 100_000.0, "cash_weight": cash_w,
                   "available_cash": 100_000.0 * cash_w,
                   "position_count": len(weights)},
    }


def buy(ticker, weight, **extra):
    return {"ticker": ticker, "action": "BUY", "target_weight": weight,
            "notional": 1_000.0, "thesis": "x", "risks": "x",
            "reason_for_action": "x", **extra}


def sell(ticker, **extra):
    return {"ticker": ticker, "action": "SELL", "target_weight": 0.0,
            "notional": 1_000.0, "thesis": "x", "risks": "x",
            "reason_for_action": "x", **extra}


BALANCED = {t: 0.10 for t in BONDS} | {t: 0.05 for t in RISK}   # 30/60/10


def attack(name, decisions, st, expect_ticker, expect_phrase=None):
    """Run one attack. Returns (fired, message).

    `expect_phrase` matters more than it looks. A rejection is not a pass if a
    DIFFERENT rule caught it: the attack was blocked, but the rule under test
    is still unproven, and the report would claim otherwise. Two attacks in
    the first version of this file did exactly that - the bond-maximum and
    position-count attacks were both stopped by a sleeve floor instead, and
    read as green.
    """
    out = validate_static(decisions, st, RULES, UNIVERSE)
    hit = next((d for d in out if d["ticker"] == expect_ticker), None)
    if hit is None:
        return False, "decision vanished from the result"
    if hit["valid"]:
        return False, "ACCEPTED - no guardrail stopped it"
    if expect_phrase and expect_phrase not in (hit["rejection_reason"] or ""):
        return False, (f"WRONG RULE fired - expected {expect_phrase!r}, "
                       f"got: {hit['rejection_reason']}")
    return True, hit["rejection_reason"]


def main() -> int:
    results = []

    # --- position sizing -------------------------------------------------
    results.append(("company weight cap (10%)", *attack(
        "", [*(buy(t, 0.10) for t in BONDS), buy("AAPL", 0.15)],
        state({}), "AAPL")))

    results.append(("fund weight cap (25%)", *attack(
        "", [*(buy(t, 0.10) for t in BONDS), buy("GLD", 0.30)],
        state({}), "GLD")))

    # --- universe --------------------------------------------------------
    results.append(("ticker outside the universe", *attack(
        "", [buy("NOT_A_TICKER", 0.05)], state(BALANCED), "NOT_A_TICKER")))

    # --- the sleeves -----------------------------------------------------
    results.append(("risk sleeve above its 75% max", *attack(
        "", [*(buy(t, 0.05) for t in BONDS), *(buy(t, 0.0667) for t in RISK)],
        state({}), "SPY", "risk sleeve would reach")))

    # The bond maximum cannot be attacked, and that is the finding.
    #
    # There are three bond funds and the fund cap holds each at 25%, so the
    # sleeve tops out at exactly 75% and can never exceed it. A legal book is
    # tighter still: the 25% risk floor and the 5% cash floor leave bonds no
    # more than 70%. The stated band is 25-75%; the reachable band is 25-70%.
    #
    # Not a hole - nothing gets through - but the rule is redundant, and a
    # redundant rule that reads as enforced is worth knowing about. Adding a
    # fourth bond fund would make it bite.
    results.append(("bond sleeve above its 75% max", None,
                    "UNREACHABLE - 3 funds x 25% fund cap tops out AT 75%, "
                    "and the risk+cash floors cap bonds at 70% anyway"))

    results.append(("buying risk while bonds under floor", *attack(
        "", [buy("AAPL", 0.05), buy("MSFT", 0.05)], state({}), "AAPL",
        "bond sleeve would sit")))

    results.append(("buying bonds while risk under floor", *attack(
        "", [*(buy(t, 0.10) for t in BONDS), buy("AAPL", 0.05)],
        state({}), "IEF", "risk sleeve would sit")))

    # --- concentration ---------------------------------------------------
    heavy = {t: 0.10 for t in BONDS} | {"SPY": 0.20, "QQQ": 0.18}
    results.append(("broad US equity cap (40%)", *attack(
        "", [buy("VOO", 0.08)], state(heavy, cash=0.10), "VOO")))

    # --- counts ----------------------------------------------------------
    # 21 positions already held, with the sleeves legal (30/60/10), so the
    # count is the only thing wrong. Buying a 22nd must be the rule that bites.
    fillers = [t for t in UNIVERSE["tickers"]
               if t not in BONDS and t != "AAPL"][:18]
    many = {t: 0.10 for t in BONDS} | {t: 0.60 / 18 for t in fillers}
    results.append(("position count above maximum", *attack(
        "", [buy("AAPL", 0.02)], state(many, cash=0.10), "AAPL",
        "exceeds maximum")))

    thin = {t: 0.10 for t in BONDS} | {t: 0.10 for t in RISK[:5]}
    results.append(("discretionary sell below minimum count", *attack(
        "", [sell("SPY")], state(thin, cash=0.10), "SPY", "below the minimum")))

    # --- cash ------------------------------------------------------------
    # The ceiling judges cash AFTER the cycle, so the attack has to be a sell
    # that LEAVES the book idle - not merely one made while cash happens to be
    # high. Selling dust from an otherwise-cash book was the old attack, and
    # blocking that was the bug: the first live cycle proposed exactly that
    # while its own buys were taking cash from 99.98% to 5%.
    idle = {t: 0.10 for t in BONDS} | {t: 0.05 for t in RISK[:10]}   # 30/50/20
    results.append(("cash ceiling on a discretionary sell", *attack(
        "", [sell(RISK[0])], state(idle), RISK[0], "above the ceiling")))

    fired = check_cash(buy("AAPL", 0.05) | {"notional": 99_000.0},
                       100_000.0, 100_000.0, RULES) is not None
    results.append(("cash floor on a buy", fired,
                    "rejected" if fired else "ACCEPTED - no guardrail stopped it"))

    # --- malformed input -------------------------------------------------
    results.append(("percentage instead of a fraction (6.3)", *attack(
        "", [buy("AAPL", 6.3)], state(BALANCED), "AAPL")))

    results.append(("unsupported action", *attack(
        "", [buy("AAPL", 0.05) | {"action": "YOLO"}], state(BALANCED), "AAPL")))

    results.append(("notional below the minimum", *attack(
        "", [buy("AAPL", 0.05) | {"notional": 0.0001}], state(BALANCED), "AAPL")))

    results.append(("selling something not held", *attack(
        "", [sell("TSLA")], state(BALANCED), "TSLA")))

    # --- mechanical triggers (these must FIRE, not reject) ---------------
    crashed = state(BALANCED)
    crashed["positions"][3]["unrealized_pl_pct"] = -0.25
    stops = [d for d in mechanical_decisions(crashed, RULES)
             if d.get("trigger") == "stop_loss"]
    results.append(("stop loss at -20%", bool(stops),
                    stops[0]["reason_for_action"] if stops else
                    "DID NOT FIRE on a -25% position"))

    fat = state({t: 0.10 for t in BONDS} | {"SPY": 0.18} |
                {t: 0.05 for t in RISK[1:9]})
    trims = [d for d in mechanical_decisions(fat, RULES)
             if d.get("trigger") == "concentration_trim"]
    results.append(("concentration trim at 12%", bool(trims),
                    trims[0]["reason_for_action"] if trims else
                    "DID NOT FIRE on an 18% position"))

    # --- report ----------------------------------------------------------
    width = max(len(n) for n, _, _ in results)
    print(f"attacking {len(results)} guardrails\n")
    failures = 0
    for name, fired, detail in results:
        if fired is None:                       # no attack can be constructed
            mark = "N/A   "
        elif fired:
            mark = "HELD  "
        else:
            mark = "BROKE "
            failures += 1
        print(f"  {mark} {name:<{width}}  {detail[:76]}")
    tested = sum(1 for _, f, _ in results if f is not None)
    print()
    if failures:
        print(f"{failures} of {tested} attempted attacks got through.")
    else:
        print(f"all {tested} attempted attacks were stopped "
              f"({len(results) - tested} rule unreachable, see above).")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
