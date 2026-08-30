"""A deterministic stand-in for the LLM.

Its job is to keep the pipeline busy enough that the guardrails are actually
exercised. An earlier version proposed a single BUY of one ticker every cycle,
so a 250-day run produced 50 identical decisions, bought one company, and
reported a clean pass having tested almost nothing.

The rule this exists to satisfy: after a full run, the summary should show
positions opening, positions closing, and rejections for MORE than one reason.
"""

from __future__ import annotations


def _seed_for(state, candidates):
    """Deterministic per-cycle variation, without a clock or a random module."""
    stamp = state.get("generated_at", "")
    return sum(ord(c) for c in stamp) + len(candidates)


def propose(state, rules, candidates, held_theses, mode="valid"):
    want = rules["position_count"]["target"]
    held = {p["ticker"]: p for p in state.get("positions", [])}
    seed = _seed_for(state, candidates)

    # Sizing is derived now, not read from a fixed target, and the stub has to
    # fill BOTH sleeves or the validator rejects everything it proposes: a buy
    # into the risk sleeve is refused while bonds sit under their floor. That
    # is the rule working - but it means a stub that only ever bought shares
    # would build nothing and the run would test nothing.
    sleeves = rules["sleeves"]
    bond_universe = [t for t in sleeves["bond"]["tickers"]
                     if t in candidates or t in held]
    bond_sleeve, risk_sleeve = 0.30, 0.60          # inside both 25-75% bands
    bond_target = bond_sleeve / max(1, len(bond_universe))
    target = risk_sleeve / max(1, want - len(bond_universe))
    is_bond = set(bond_universe).__contains__

    def size(ticker):
        return bond_target if is_bond(ticker) else target

    if mode == "malformed":
        return {"commentary": "bad", "decisions": "bad", "considered": []}

    def entry(ticker, action, weight, why):
        return {
            "ticker": ticker, "action": action, "target_weight": weight,
            "thesis": f"Simulated thesis for {ticker}.",
            "risks": f"Synthetic market risk on {ticker}.",
            "business": f"{ticker} is a simulated business.",
            "reason_for_action": why,
        }

    if mode == "bad_ticker":
        return {"commentary": "x", "considered": [],
                "decisions": [entry("NOT_A_TICKER", "BUY", target, "outside the universe")]}
    if mode == "overweight":
        return {"commentary": "x", "considered": [],
                "decisions": [entry(candidates[0], "BUY", 0.40, "deliberately oversized")]}
    if mode == "overspend":
        return {"commentary": "x", "considered": [],
                "decisions": [entry(t, "BUY", target, "deliberately unaffordable")
                              for t in candidates[:18]]}

    decisions = []

    # Sell one holding occasionally, so positions close as well as open and the
    # sell path is exercised rather than only ever buying.
    if len(held) >= 4 and seed % 5 == 0:
        victim = sorted(held)[seed % len(held)]
        decisions.append(entry(victim, "SELL", 0.0, "Simulated thesis break."))

    # HOLD anything already at roughly target weight. Proposing BUY for a
    # position already the right size produces a sub-dollar top-up, which the
    # validator then rejects as a malformed notional - a confusing message for
    # what is really "nothing to do here".
    selling = {d["ticker"] for d in decisions}
    for ticker, position in sorted(held.items()):
        if ticker in selling:
            continue
        if position.get("weight", 0) >= size(ticker) * 0.9:
            decisions.append(entry(ticker, "HOLD", size(ticker), "At target weight; thesis intact."))

    # Bonds first. A risk buy is rejected while the bond sleeve is under its
    # floor, so proposing shares before bonds would have every share refused.
    room = want - (len(held) - len(selling))
    for ticker in bond_universe:
        if ticker not in held and room > 0:
            decisions.append(entry(ticker, "BUY", bond_target, "Filling the bond sleeve."))
            room -= 1

    # Then buy toward the target count, rotating so the book is not always the
    # same names.
    fresh = [t for t in candidates if t not in held and not is_bond(t)]
    rotated = fresh[seed % len(fresh):] + fresh[:seed % len(fresh)] if fresh else []
    for ticker in rotated[:max(0, room)]:
        decisions.append(entry(ticker, "BUY", target, "Building toward the target position count."))

    # Top up anything that has drifted well below its derived weight.
    for ticker, position in sorted(held.items()):
        if ticker not in selling and position.get("weight", 0) < size(ticker) * 0.75:
            decisions.append(entry(ticker, "BUY", size(ticker), "Drifted below target weight."))

    considered = [{"ticker": t, "verdict": "Not selected this cycle."}
                  for t in candidates if t not in held][:8]

    return {
        "commentary": (f"Simulated cycle: {len(held)} held, "
                       f"{sum(1 for d in decisions if d['action'] == 'BUY')} buys, "
                       f"{sum(1 for d in decisions if d['action'] == 'SELL')} sells."),
        "decisions": decisions,
        "considered": considered,
    }
