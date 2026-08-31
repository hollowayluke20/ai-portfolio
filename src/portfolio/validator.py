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


def _projected_sleeves(decisions, held, rules):
    """Sleeve weights the book would carry if every proposal were filled.

    Computed once for the whole cycle, like `projected_count`, because a
    sleeve band is a property of the finished portfolio and cannot be judged
    from one decision in isolation.

    HOLD and anything unmentioned keeps its current weight; BUY and TRIM move
    to their target; SELL goes to zero.
    """
    weights = {t: float(p.get("weight") or 0.0) for t, p in held.items()}
    for proposal in decisions:
        ticker, action = proposal.get("ticker"), proposal.get("action")
        if not ticker or action not in VALID_ACTIONS:
            continue
        if action == "SELL":
            weights[ticker] = 0.0
        elif action in {"BUY", "TRIM"}:
            target = proposal.get("target_weight")
            if isinstance(target, (int, float)):
                weights[ticker] = float(target)
    bond_tickers = set(rules["sleeves"]["bond"]["tickers"])
    bond = sum(w for t, w in weights.items() if t in bond_tickers)
    risk = sum(w for t, w in weights.items() if t not in bond_tickers)
    return bond, risk


def _broad_cap_breach(ticker, target_weight, held, rules):
    """Why this BUY breaches the combined broad-US-equity cap, or None."""
    cap = rules.get("broad_us_equity_cap")
    if not cap or ticker not in cap.get("tickers", []):
        return None
    broad = sum(p.get("weight", 0) for p in held.values()
                if p["ticker"] in cap["tickers"])
    combined = broad + target_weight
    if combined > cap["limit"]:
        return (f"broad US equity weight {combined:.4f} "
                f"exceeds limit {cap['limit']:.4f}")
    return None


def _sleeve_breach(ticker, bond_tickers, sleeves, projected_bond, projected_risk):
    """Why this BUY is refused on allocation grounds, or None."""
    bond, risk = sleeves["bond"], sleeves["risk"]
    buying_bonds = ticker in bond_tickers
    if buying_bonds:
        if projected_bond > bond["max"]:
            return (f"bond sleeve would reach {projected_bond:.4f}, "
                    f"above its maximum of {bond['max']:.4f}")
        if projected_risk < risk["min"]:
            return (f"risk sleeve would sit at {projected_risk:.4f}, below its "
                    f"minimum of {risk['min']:.4f} - raise it before adding bonds")
    else:
        if projected_risk > risk["max"]:
            return (f"risk sleeve would reach {projected_risk:.4f}, "
                    f"above its maximum of {risk['max']:.4f}")
        if projected_bond < bond["min"]:
            return (f"bond sleeve would sit at {projected_bond:.4f}, below its "
                    f"minimum of {bond['min']:.4f} - raise it before adding risk")
    return None


def validate_static(decisions, state, rules, universe):
    """Return copied decisions annotated with order-independent validation."""
    held = _held_positions(state)
    assets = _asset_map(state)
    tickers = set(universe.get("tickers", universe) if isinstance(universe, dict) else universe)
    minimum_notional = float(rules.get("minimum_notional", 1.0))
    weight_caps = rules["position_weight"]
    funds = set(rules.get("etf_universe", []))
    sleeves = rules["sleeves"]
    bond_tickers = set(sleeves["bond"]["tickers"])
    projected_bond, projected_risk = _projected_sleeves(decisions, held, rules)
    limits = rules["position_count"]
    ceiling = rules.get("cash", {}).get("ceiling")
    # Cash AFTER this cycle's proposals, not cash right now.
    #
    # Judging it on the current balance broke the very first live cycle: the
    # book was 99.98% cash because it was starting from scratch, the model
    # sensibly proposed clearing a few dollars of leftover dust, and the
    # ceiling refused it for having too much cash - while the same cycle's
    # fourteen buys were taking cash to 5%.
    #
    # Selling dust does not meaningfully raise cash. What the rule is actually
    # for is stopping the book sell itself into idleness, and that is a
    # property of where the cycle ENDS. The sleeves were already judged that
    # way; cash was not, and the inconsistency was the bug.
    projected_cash = max(0.0, 1.0 - projected_bond - projected_risk)
    cash_weight = projected_cash
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
            elif action in {"BUY", "TRIM"} and decision["target_weight"] > (
                cap := float(weight_caps["hard_cap_fund" if ticker in funds
                                         else "hard_cap_company"])):
                # Two caps, because the cap exists to stop one COMPANY blowing
                # a hole in the book. A bond fund holds thousands of issues;
                # capping it like a single share is the wrong rule. The
                # separate broad_us_equity_cap still stops SPY/VOO/QQQ
                # quietly turning this into an index tracker.
                kind = "fund" if ticker in funds else "company"
                reason = f"target_weight exceeds the {kind} hard cap of {cap}"
            elif action == "BUY" and (
                    _broad_reason := _broad_cap_breach(ticker, decision["target_weight"],
                                                       held, rules)):
                # NB the walrus: this branch must only MATCH when it actually
                # has a complaint. Written as `elif ticker in capped_tickers:`
                # it matched every SPY/VOO/QQQ buy and then fell out of the
                # chain with no reason set - silently skipping the position
                # count, notional and sleeve checks for exactly the three
                # tickers most able to distort the book.
                reason = _broad_reason
            elif action == "BUY" and (
                    _sleeve_reason := _sleeve_breach(ticker, bond_tickers, sleeves,
                                                     projected_bond, projected_risk)):
                # The allocation band, judged on the finished book rather than
                # one buy at a time.
                #
                # Buying INTO an over-full sleeve is blocked. Being under a
                # floor blocks buys in the OTHER sleeve instead - the same
                # principle as the position-count minimum below. Rejecting the
                # buy that would fix a shortfall is backwards: no rejection can
                # ever create a position, so blocking the cure leaves the book
                # stuck out of band forever.
                reason = _sleeve_reason
            elif action in {"SELL", "TRIM"} and ticker not in held:
                reason = f"{action} requires an existing holding of {ticker}"
            else:
                # The MAXIMUM gates buying: it stops the book fragmenting.
                #
                # The MINIMUM does not. Blocking a buy for leaving the book
                # below the target is backwards - it blocks the move TOWARD
                # diversification. Enforced on buys it makes the portfolio
                # impossible to build: from empty, any cycle proposing fewer
                # than `minimum` names has every one rejected, and after a
                # crash stops out most positions the book can never be rebuilt.
                # Found by simulating a year: 250 days, 50 cycles, and the
                # portfolio ended holding ONE position and 93.5% cash.
                #
                # The minimum instead blocks a discretionary SELL that would
                # take the book below it. Stop-losses and trims are never
                # blocked - a safety exit must not be gated by a
                # diversification rule (the same principle that already lets
                # the universe gate buys but not exits).
                if action == "BUY" and projected_count > limits["maximum"]:
                    reason = (f"resulting position count {projected_count} exceeds "
                              f"maximum of {limits['maximum']}")
                elif (action == "SELL" and decision.get("trigger", "ai") == "ai"
                      and projected_count < limits["minimum"]):
                    reason = (f"discretionary sell would leave {projected_count} positions, "
                              f"below the minimum of {limits['minimum']}")
                elif (action == "SELL" and decision.get("trigger", "ai") == "ai"
                      and ceiling is not None and cash_weight > ceiling):
                    # The cash CEILING, and it gates only discretionary sells.
                    #
                    # It exists to stop money sitting idle - a performance
                    # rule, not a safety one. So it must never block a stop
                    # loss or a trim: gating a safety exit on a performance
                    # rule is backwards, exactly as the position-count minimum
                    # above already refuses to.
                    #
                    # It cannot be enforced by rejecting buys either, because
                    # rejecting a buy RAISES cash. The only lever a validator
                    # has is to stop the book selling further while it is
                    # already sitting on too much - redeploy first.
                    #
                    # Found by replaying Feb-Apr 2025: eleven thesis-driven
                    # exits left 32% in cash against a 15% ceiling that was in
                    # the rules file, visible to the model, and enforced by
                    # nothing.
                    reason = (f"cash is {cash_weight:.4f}, above the ceiling of "
                              f"{ceiling:.4f} - redeploy before selling more")
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
