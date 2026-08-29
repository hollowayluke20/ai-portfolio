"""Pure transformations from broker responses to the persisted state contract."""


def _money(value):
    """Round a monetary value for JSON output."""
    return round(float(value), 2)


def _fraction(value):
    """Keep stored weights and returns readable without turning them into percents."""
    return round(float(value), 4)


def build_state(account, positions, spy_price, spy_as_of,
                rules, inception, generated_at, run, pending_orders=None,
                health=None, active_records=None):
    """Build an ADR 0004 state document without reading external state.

    ``rules`` is deliberately accepted as part of the pipeline interface even
    though the current state schema has no rules-derived fields.
    """
    del rules

    cash = _money(account["cash"])
    output_positions = []
    invested_value = 0.0

    for position in positions:
        record = (active_records or {}).get(position["symbol"])
        market_value = _money(position["market_value"])
        invested_value += market_value
        qty = float(position["qty"])
        avg_entry_price = _money(position["avg_entry_price"])
        current_price = _money(position["current_price"])
        unrealized_pl = _money(position["unrealized_pl"])
        cost_basis = qty * float(position["avg_entry_price"])
        unrealized_pl_pct = unrealized_pl / cost_basis if cost_basis else 0.0
        output_positions.append({
            "ticker": position["symbol"],
            "name": position.get("name"),
            "qty": qty,
            "avg_entry_price": avg_entry_price,
            "current_price": current_price,
            "market_value": market_value,
            "unrealized_pl": unrealized_pl,
            "unrealized_pl_pct": _fraction(unrealized_pl_pct),
            "thesis": record.get("thesis") if record else None,
            "risks": record.get("risks") if record else None,
            "business": record.get("business") if record else None,
            "opened_at": record.get("decided_at") if record else None,
        })

    invested_value = _money(invested_value)
    total_value = _money(cash + invested_value)
    for position in output_positions:
        position["weight"] = _fraction(
            position["market_value"] / total_value if total_value else 0.0
        )
    cash_weight = _fraction(cash / total_value if total_value else 0.0)

    output_orders = []
    warnings = list((health or {}).get("warnings", []))
    prices = {position["symbol"]: float(position["current_price"]) for position in positions}
    committed_cash = 0.0
    for order in pending_orders or []:
        notional = order.get("notional")
        qty = order.get("qty")
        output_orders.append({
            "symbol": order["symbol"],
            "side": order["side"],
            "notional": _money(notional) if notional is not None else None,
            "qty": float(qty) if qty is not None else None,
            "status": order["status"],
            "submitted_at": order["submitted_at"],
            "order_id": order["order_id"],
        })
        if order["side"].lower() != "buy":
            continue
        if notional is not None:
            committed_cash += float(notional)
        elif qty is not None and order["symbol"] in prices:
            committed_cash += float(qty) * prices[order["symbol"]]
        else:
            warnings.append(
                f"Cannot determine committed cash for pending buy {order['symbol']} "
                "because it has quantity but no current position price"
            )

    committed_cash = _money(committed_cash)
    available_cash = _money(cash - committed_cash)

    if inception is None:
        performance = None
        benchmark = None
    else:
        inception_value = float(inception["inception_value"])
        inception_price = float(inception["benchmark_inception_price"])
        portfolio_return = total_value / inception_value - 1 if inception_value else 0.0
        benchmark_return = float(spy_price) / inception_price - 1 if inception_price else 0.0
        performance = {
            "inception_date": inception["inception_date"],
            "inception_value": _money(inception_value),
            "total_return_pct": _fraction(portfolio_return),
        }
        benchmark = {
            "ticker": inception["benchmark_ticker"],
            "inception_price": _money(inception_price),
            "current_price": _money(spy_price),
            "total_return_pct": _fraction(benchmark_return),
            "difference_pct": _fraction(portfolio_return - benchmark_return),
        }

    return {
        "schema_version": 1,
        "generated_at": generated_at,
        "market_data_as_of": spy_as_of,
        "currency": account.get("currency", "USD"),
        "run": run,
        "account": {
            "cash": cash,
            "equity": _money(account["equity"]),
            "buying_power": _money(account["buying_power"]),
            "status": account["status"],
        },
        "totals": {
            "total_value": total_value,
            "invested_value": invested_value,
            "cash_weight": cash_weight,
            "position_count": len(output_positions),
            "committed_cash": committed_cash,
            "available_cash": available_cash,
        },
        "positions": output_positions,
        "pending_orders": output_orders,
        "performance": performance,
        "benchmark": benchmark,
        # The dashboard reads this to decide whether to trust the numbers,
        # so a degraded run must be able to say so (ADR 0004).
        "health": {"ok": not warnings, "warnings": warnings},
    }


def build_history_row(state, benchmark_price=None):
    """Extract the one-per-day history record from a state document.

    ``benchmark_price`` is passed explicitly so the benchmark price series
    stays unbroken BEFORE inception, when ``state["benchmark"]`` is still
    null. History cannot be reconstructed after the fact (ADR 0004) - a day
    whose benchmark price is not recorded is lost permanently.
    """
    performance = state["performance"]
    benchmark = state["benchmark"]
    return {
        # Dated by when the PRICES are from, not when the file was written.
        # A run before the market's data for the day exists would otherwise
        # file yesterday's prices under today's date and shift the chart.
        "date": state["market_data_as_of"][:10],
        "portfolio_value": state["totals"]["total_value"],
        "portfolio_return_pct": (
            performance["total_return_pct"] if performance is not None else None
        ),
        "benchmark_price": (
            benchmark["current_price"] if benchmark is not None
            else (_money(benchmark_price) if benchmark_price is not None else None)
        ),
        "benchmark_return_pct": (
            benchmark["total_return_pct"] if benchmark is not None else None
        ),
        "cash": state["account"]["cash"],
    }
