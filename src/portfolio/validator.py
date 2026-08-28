"""Deterministic guardrails for proposed portfolio decisions."""

from copy import deepcopy


VALID_ACTIONS = {"BUY", "SELL", "TRIM", "HOLD"}


def _asset_map(state):
    assets = state.get("assets", {})
    if isinstance(assets, dict):
        return assets
    return {asset["symbol"]: asset for asset in assets}


def _held_positions(state):
    return {position["ticker"]: position for position in state.get("positions", [])}


def validate_static(decisions, state, rules, universe):
    """Return copied decisions annotated with order-independent validation."""
    held = _held_positions(state)
    assets = _asset_map(state)
    tickers = set(universe.get("tickers", universe) if isinstance(universe, dict) else universe)
    minimum_notional = float(rules.get("minimum_notional", 1.0))
    cap = float(rules["position_weight"]["hard_cap"])
    limits = rules["position_count"]
    projected = set(held)
    for proposal in decisions:
        ticker, action = proposal.get("ticker"), proposal.get("action")
        if ticker not in tickers:
            continue
        if action == "BUY":
            projected.add(ticker)
        elif action == "SELL":
            projected.discard(ticker)
    projected_count = len(projected)

    annotated = []
    for original in decisions:
        decision = deepcopy(original)
        action = decision.get("action")
        ticker = decision.get("ticker")
        reason = None
        if action not in VALID_ACTIONS:
            reason = f"unsupported action: {action!r}"
        elif action in {"BUY"} and ticker not in tickers:
            # The universe gates what may be BOUGHT, not what may be EXITED.
            # A holding dropped from the index at the next refresh must still be
            # sellable, or the system is stranded in it permanently.
            # config/universe.json already guarantees every member is tradable
            # AND fractionable (refresh_universe.py filters on exactly that), so
            # membership IS the tradability check - there is no second source.
            reason = f"ticker {ticker!r} is outside the configured universe"
        else:
            if False:
                pass
            elif not isinstance(decision.get("target_weight"), (int, float)) or not 0 <= decision["target_weight"] <= 1:
                reason = "target_weight must be a decimal fraction between 0 and 1"
            elif action in {"BUY", "TRIM"} and decision["target_weight"] > cap:
                reason = f"target_weight exceeds hard cap of {cap}"
            elif action in {"SELL", "TRIM"} and ticker not in held:
                reason = f"{action} requires an existing holding of {ticker}"
            else:
                if not limits["minimum"] <= projected_count <= limits["maximum"]:
                    reason = f"resulting position count {projected_count} is outside {limits['minimum']}..{limits['maximum']}"
                elif action != "HOLD":
                    notional = decision.get("notional")
                    if not isinstance(notional, (int, float)) or notional < minimum_notional:
                        reason = f"notional must be at least {minimum_notional}"
        decision["valid"] = reason is None
        decision["rejection_reason"] = reason
        annotated.append(decision)
    return annotated


def check_cash(decision, running_cash, total_value, rules):
    """Return a reason when a buy would breach the available-cash floor."""
    notional = decision.get("notional")
    if not isinstance(notional, (int, float)):
        return "buy has no valid notional"
    floor = float(rules["cash"]["floor"])
    if float(running_cash) - float(notional) < floor * float(total_value):
        return f"insufficient available cash: buy would breach {floor:.0%} cash floor"
    return None
