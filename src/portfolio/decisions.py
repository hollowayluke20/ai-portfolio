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
        "decisions": executed,
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
