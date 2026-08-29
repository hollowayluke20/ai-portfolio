"""Execute validated decisions while preserving cash-priority ordering."""

from copy import deepcopy

from src.portfolio.validator import validate_static, check_cash


def submit_order(*, ticker, side, notional):
    """Submit a live order. The only path in this module that spends money."""
    from src.portfolio.alpaca import submit_notional_order
    return submit_notional_order(symbol=ticker, side=side, notional=notional)


def _planned_notional(decision, state):
    action = decision["action"]
    if action == "HOLD":
        return None
    total = float(state["totals"]["total_value"])
    held = {p["ticker"]: p for p in state.get("positions", [])}
    current = float(held.get(decision["ticker"], {}).get("market_value", 0))
    target = float(decision["target_weight"]) * total
    if action == "BUY":
        return round(max(0.0, target - current), 2)
    if action == "SELL":
        return round(current, 2)
    return round(max(0.0, current - target), 2)


def _submit_or_skip(decision, dry_run, submit):
    if dry_run:
        decision.update(status="skipped", order_id=None, rejection_reason="dry run")
        return
    side = "sell" if decision["action"] in ("SELL", "TRIM") else "buy"
    result = submit(ticker=decision["ticker"], side=side,
                          notional=decision["notional"])
    decision.update(status="executed", order_id=result.get("order_id"), rejection_reason=None)


def execute(decisions, state, rules, universe, dry_run: bool, submit=None):
    """Validate, sell/trim first, then buy in the supplied priority order."""
    submit = submit_order if submit is None else submit
    prepared = []
    for decision in decisions:
        item = deepcopy(decision)
        item["notional"] = _planned_notional(item, state)
        prepared.append(item)
    # universe is passed in explicitly. It was previously derived from `state`,
    # which has no such key (ADR 0004), so it silently resolved to an empty set
    # and every buy was rejected as "not in universe".
    validated = validate_static(prepared, state, rules, universe)
    total_value = float(state["totals"]["total_value"])
    running_cash = float(state["totals"]["available_cash"])

    results = []
    for action in ("SELL", "TRIM", "HOLD", "BUY"):
        for decision in (d for d in validated if d.get("action") == action):
            if not decision["valid"]:
                decision.update(status="rejected", order_id=None)
            elif action == "HOLD":
                decision.update(status="skipped", order_id=None, rejection_reason="hold")
            elif action == "BUY":
                reason = check_cash(decision, running_cash, total_value, rules)
                if reason:
                    decision.update(status="rejected", order_id=None, rejection_reason=reason)
                else:
                    _submit_or_skip(decision, dry_run, submit)
                    running_cash -= float(decision["notional"])
            else:
                # SELL / TRIM. Deliberately does NOT credit the proceeds to
                # running_cash. These are market orders placed after the close;
                # they do not fill until the next open, so the money is not
                # there yet. Crediting it would let a later buy be submitted
                # against cash that does not exist - which Alpaca would accept
                # using the 4x margin ADR 0003 declines to use.
                # Consequence: a sell-to-fund-a-buy rebalance takes two cycles.
                _submit_or_skip(decision, dry_run, submit)
            results.append(decision)
    return results
