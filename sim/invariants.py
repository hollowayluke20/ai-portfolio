"""Invariant checks for each simulated trading day."""

import math


def check(state, history, rules, day):
    problems, notes, totals = [], [], state["totals"]
    label = str(day)
    weight = totals["cash_weight"] + sum(item["weight"] for item in state["positions"])
    if abs(weight - 1) > .01: problems.append(f"{label}: weights sum to {weight}, expected 1.0")
    calculated = state["account"]["cash"] + sum(item["market_value"] for item in state["positions"])
    if abs(totals["total_value"] - calculated) > .01: problems.append(f"{label}: total_value {totals['total_value']} != cash plus positions {calculated}")
    pending = sum(order["notional"] or 0 for order in state.get("pending_orders", []) if order["side"] == "buy")
    expected = state["account"]["cash"] - pending
    if abs(totals["available_cash"] - expected) > .01: problems.append(f"{label}: available_cash {totals['available_cash']} != {expected}")
    # NOT an invariant. The cash floor is a PRE-TRADE check: an order that would
    # breach it is rejected. It is not a state that must always hold, because
    # the floor is a PERCENTAGE - a rising market pushes cash under it with no
    # trade at all. The cash did not move; the target did. (ADR 0003, third
    # amendment. Found by this simulation flagging a violation on a day nothing
    # was bought.)
    #
    # It still matters, because below the floor the system cannot buy until
    # something is sold - so it is reported as an observation, not a failure.
    if state.get("performance") and state["account"]["cash"] < rules["cash"]["floor"] * totals["total_value"]:
        notes.append(f"{label}: cash has drifted to "
                     f"{state['account']['cash'] / totals['total_value']:.2%}, below the "
                     f"{rules['cash']['floor']:.0%} floor - buying is blocked until a sell frees cash")
    for value in _numbers(state):
        if not math.isfinite(value): problems.append(f"{label}: non-finite numeric value {value}"); break
    dates=[row["date"] for row in history.get("rows", [])]
    if len(dates) != len(set(dates)): problems.append(f"{label}: duplicate history dates {dates}")
    if dates != sorted(dates): problems.append(f"{label}: history dates out of order {dates}")
    return problems, notes


def _numbers(value):
    if isinstance(value, dict):
        for item in value.values(): yield from _numbers(item)
    elif isinstance(value, list):
        for item in value: yield from _numbers(item)
    elif isinstance(value, (int, float)) and not isinstance(value, bool): yield float(value)
