"""Pure mechanical safety exits."""


def _derived_target(position, state, rules):
    """The weight this holding is supposed to sit at, worked out from the book.

    There used to be a fixed `concentration_trim_target` of 0.063 in the rules,
    and the trim cut every outsized position back to it. That number was the
    old one-size-fits-all position weight, and it stopped existing on
    2026-08-31 when sizing became derived: a holding's weight is now its
    sleeve's weight divided by the number of holdings in that sleeve.

    Left alone, the trim would have cut a bond fund from 12% back to 6.3% -
    not its target, and enough to drag the bond sleeve toward its floor. Two
    of them would have breached it. A safety rule aiming at a number nothing
    else in the system uses is a safety rule doing damage.

    So the target is computed the same way every other weight is. If the
    sleeve cannot be measured, fall back to an equal share of the invested
    book rather than to a constant.
    """
    bonds = set(rules["sleeves"]["bond"]["tickers"])
    in_bonds = position["ticker"] in bonds
    peers = [p for p in state.get("positions", [])
             if (p["ticker"] in bonds) == in_bonds
             and isinstance(p.get("weight"), (int, float))]
    sleeve_weight = sum(p["weight"] for p in peers)
    if peers and sleeve_weight > 0:
        return sleeve_weight / len(peers)
    invested = sum(p.get("weight") or 0.0 for p in state.get("positions", []))
    count = len(state.get("positions", [])) or 1
    return invested / count


def mechanical_decisions(state, rules):
    triggers = rules["sell_triggers"]
    out = []
    for p in state.get("positions", []):
        loss, weight = p.get("unrealized_pl_pct"), p.get("weight")
        if loss is not None and loss <= triggers["stop_loss_pct"]:
            out.append({
                "ticker": p["ticker"], "action": "SELL", "target_weight": 0.0,
                "trigger": "stop_loss",
                "thesis": f"Exit after {loss:.2%} loss breached {triggers['stop_loss_pct']:.2%} stop.",
                "risks": "Loss may reverse, but the stop limits further damage.",
                "reason_for_action": f"Stop-loss threshold breached: {loss:.2%}.",
            })
        elif weight is not None and weight > triggers["concentration_trim_threshold"]:
            target = _derived_target(p, state, rules)
            out.append({
                "ticker": p["ticker"], "action": "TRIM",
                "target_weight": round(target, 4),
                "trigger": "concentration_trim",
                "thesis": f"Reduce concentration from {weight:.2%} to {target:.2%}, its sleeve's equal weight.",
                "risks": "Trimming can limit further upside.",
                "reason_for_action": f"Weight {weight:.2%} exceeded {triggers['concentration_trim_threshold']:.2%} threshold.",
            })
    return out
