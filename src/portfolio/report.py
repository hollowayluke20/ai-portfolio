"""Pure plain-text rendering of the committed portfolio records."""

from datetime import date


def _money(value):
    return f"${value:,.0f}" if float(value).is_integer() else f"${value:,.2f}"


def _percent(value):
    """A CHANGE, signed. Use for returns and P&L."""
    return f"{float(value):+.2%}"


def _share(value):
    """A PROPORTION, unsigned. Use for weights.

    A weight is not a change, so "+0.02% weight" is wrong - the sign implies
    the position grew by that much rather than being that size.
    """
    return f"{float(value):.2%}"


def _weekly_change(history):
    rows = history.get("rows", [])
    if len(rows) < 5:
        return None
    current, baseline = rows[-1], rows[-5]
    if not baseline.get("portfolio_value"):
        return None
    return current["portfolio_value"] / baseline["portfolio_value"] - 1


def build_report(state, history, decisions):
    """Build a subject and plain-text report without reading external state."""
    total = state["totals"]["total_value"]
    performance = state.get("performance")
    decision_items = (decisions or {}).get("decisions", [])
    if performance is None:
        subject_return = "not yet trading"
    else:
        subject_return = _percent(performance["total_return_pct"])
    subject = f"AI Portfolio — {_money(total)} ({subject_return}) — {len(decision_items)} decisions"

    lines = []
    health = state.get("health", {"ok": True, "warnings": []})
    if not health.get("ok", True):
        lines.extend(["HEALTH WARNINGS"])
        lines.extend(f"- {warning}" for warning in health.get("warnings", []))
        lines.append("")

    lines.extend(["AI PORTFOLIO WEEKLY REPORT", f"Market data as of: {state['market_data_as_of']}", ""])
    lines.append(f"Headline: {_money(total)} total portfolio value")
    if performance is None:
        lines.append("The system has not yet started trading; return tracking begins at inception.")
    else:
        benchmark = state["benchmark"]
        lines.append(f"Since inception: {_percent(performance['total_return_pct'])}")
        lines.append(f"SPY benchmark: {_percent(benchmark['total_return_pct'])}")
        lines.append(f"Difference: {_percent(benchmark['difference_pct'])}")

    weekly = _weekly_change(history)
    if weekly is not None:
        lines.extend(["", f"This week: {_percent(weekly)} since the comparable history row."])

    positions = sorted(state.get("positions", []), key=lambda item: item.get("weight", 0), reverse=True)
    lines.extend(["", "Holdings"])
    if positions:
        for position in positions:
            lines.append(f"- {position['ticker']}: {_share(position['weight'])} weight, "
                         f"{_percent(position['unrealized_pl_pct'])} since entry")
    else:
        lines.append("- No holdings")

    lines.extend(["", "Notable"])
    if positions:
        largest = positions[0]
        best = max(positions, key=lambda item: item.get("unrealized_pl_pct", 0))
        worst = min(positions, key=lambda item: item.get("unrealized_pl_pct", 0))
        lines.extend([
            f"Largest position: {largest['ticker']} ({_share(largest['weight'])})",
            f"Best performer: {best['ticker']} ({_percent(best['unrealized_pl_pct'])})",
            f"Worst performer: {worst['ticker']} ({_percent(worst['unrealized_pl_pct'])})",
        ])
    else:
        lines.append("- No holdings")

    # Rejected orders belong ONLY in the Blocked section. Listing them here too
    # reads as though the system acted on them - "BUY TSLA" above a line saying
    # the same buy was blocked, which is the opposite of what happened.
    blocked = [item for item in decision_items if item.get("status") == "rejected"]
    acted = [item for item in decision_items if item.get("status") != "rejected"]

    lines.extend(["", "Decisions this cycle"])
    if decisions is None:
        lines.append("No cycle has run yet.")
    elif acted:
        for decision in acted:
            lines.append(f"- {decision['action']} {decision['ticker']}: "
                         f"{decision.get('reason_for_action') or 'No reason recorded.'}")
    elif blocked:
        lines.append("Nothing was executed - every proposal was blocked, see below.")
    else:
        lines.append("No decisions this cycle.")
    lines.extend(["", "Blocked"])
    if blocked:
        lines.extend(f"- {item['action']} {item['ticker']}: {item.get('rejection_reason')}" for item in blocked)
    else:
        lines.append("none this cycle")

    lines.extend(["", "AI commentary"])
    lines.append((decisions or {}).get("commentary") or "No cycle has run yet.")
    lines.extend(["", "Detail: https://hollowayluke20.github.io/ai-portfolio/"])
    return subject, "\n".join(lines) + "\n"
