"""Pure mechanical safety exits."""

def mechanical_decisions(state, rules):
    triggers=rules["sell_triggers"]; out=[]
    for p in state.get("positions",[]):
        loss, weight=p.get("unrealized_pl_pct"),p.get("weight")
        if loss is not None and loss <= triggers["stop_loss_pct"]:
            out.append({"ticker":p["ticker"],"action":"SELL","target_weight":0.0,"trigger":"stop_loss","thesis":f"Exit after {loss:.2%} loss breached {triggers['stop_loss_pct']:.2%} stop.","risks":"Loss may reverse, but the stop limits further damage.","reason_for_action":f"Stop-loss threshold breached: {loss:.2%}."})
        elif weight is not None and weight > triggers["concentration_trim_threshold"]:
            out.append({"ticker":p["ticker"],"action":"TRIM","target_weight":triggers["concentration_trim_target"],"trigger":"concentration_trim","thesis":f"Reduce concentration from {weight:.2%} to target.","risks":"Trimming can limit further upside.","reason_for_action":f"Weight {weight:.2%} exceeded {triggers['concentration_trim_threshold']:.2%} threshold."})
    return out
