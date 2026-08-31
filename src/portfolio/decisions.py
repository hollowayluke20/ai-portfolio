"""Immutable decision-cycle records and retrieval of active theses."""

import json
from pathlib import Path


def write_cycle(path, cycle_id, decided_at, state, ai_output, executed):
    """Write one immutable cycle file and return its document."""
    requested = Path(path)
    destination = requested if requested.suffix == ".json" else requested / f"{decided_at[:10]}.json"
    if destination.exists():
        raise FileExistsError(f"decision record already exists: {destination}")
    document = {
        "schema_version": 1,
        "cycle_id": cycle_id,
        "decided_at": decided_at,
        "portfolio_value_at_decision": state["totals"]["total_value"],
        "commentary": ai_output["commentary"],
        # The allocation it said it was steering towards, and why. Kept as a
        # number because that is the whole point: five backtests only revealed
        # a bond sleeve pinned near 0.30 in every regime once it could be
        # counted rather than read out of prose. The first live cycle wrote
        # None here, because these were wired into the backtest log and not
        # into the record that actually matters.
        "target_bond_weight": ai_output.get("target_bond_weight"),
        "allocation_reason": ai_output.get("allocation_reason"),
        "decisions": executed,
        # The weakest-to-strongest ranking. Kept in the record because it is
        # the evidence that every holding was actually re-examined this cycle,
        # not merely left alone - the Jan-Mar 2026 backtest showed four
        # consecutive cycles of HOLD with nothing to show what was considered.
        "review": ai_output.get("review", []),
        "considered": ai_output.get("considered", []),
    }
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("x", encoding="utf-8") as file:
        json.dump(document, file, indent=2)
        file.write("\n")
    return document


def read_active_records(decisions_dir, held_tickers):
    """Find each held ticker's executed opening BUY record and cycle timestamp."""
    remaining = set(held_tickers)
    records = {}
    for path in sorted(Path(decisions_dir).glob("*.json"), reverse=True):
        with path.open(encoding="utf-8") as file:
            document = json.load(file)
        for decision in document.get("decisions", []):
            ticker = decision.get("ticker")
            if ticker in remaining and decision.get("action") == "BUY" and decision.get("status") == "executed":
                records[ticker] = {**decision, "decided_at": document["decided_at"]}
                remaining.remove(ticker)
        if not remaining:
            break
    return records


def read_active_theses(decisions_dir, held_tickers):
    """Return only the opening theses for the prompt-building caller."""
    return {
        ticker: record.get("thesis")
        for ticker, record in read_active_records(decisions_dir, held_tickers).items()
    }
