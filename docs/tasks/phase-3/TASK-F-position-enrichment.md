# Task F — position enrichment

**Read first:** the two sections dated 2026-08-29 in
`docs/decisions/0004-data-contract.md` ("Positions carry their own reasoning"
and "`data/decisions/latest.json`"). They define exactly what is required.

## Why this exists

The dashboard needs each holding's thesis and risks. Those live in the decision
records, not in `state.json`. Joining them in the browser would mean a static
page fetching an unknown number of files and matching them itself — in the part
of the system with the least error handling.

So the pipeline does the join. **The dashboard must compute nothing.**

## Files you own — edit or create ONLY these

```
src/portfolio/decisions.py
src/portfolio/state.py
scripts/run_cycle.py
tests/test_decisions.py
tests/test_state.py
```

Do not touch `index.html`, anything under `assets/`, `alpaca.py`, `validator.py`,
`executor.py`, `storage.py`, `config/`, or any ADR. **Do not commit or push.**

## 1. `decisions.py` — widen the existing lookup

`read_active_theses` already does almost all of this. It walks decision files
newest-first looking for an executed BUY per held ticker, and returns the thesis
string. **Keep that logic; widen the return.**

```python
read_active_records(decisions_dir, held_tickers) -> dict[str, dict]
# ticker -> the whole opening decision record, plus the cycle's decided_at
```

Keep `read_active_theses` working — `run_cycle.py` calls it to build the prompt,
and that caller wants only the thesis string. Implement it in terms of the new
function rather than duplicating the traversal.

## 2. `state.py` — merge onto each position

`build_state` takes a new `active_records` argument (default `None`) and merges
onto each position:

| Field | From |
|---|---|
| `thesis` | `record["thesis"]` |
| `risks` | `record["risks"]` |
| `business` | `record.get("business")` — **`None` until the AI schema provides it** |
| `opened_at` | the record's `decided_at` |

**`build_state` stays a pure function.** No file reads — the records arrive as
an argument, exactly like `rules` and `inception` do.

**A position with no matching record keeps `null` in all four fields.** This is
not an error: Luke's manual NVDA and MSTR trades were bought outside the system
and will never have a record. Do not invent placeholder text — the dashboard
decides how to present an absent thesis.

## 3. `run_cycle.py` — write the known path

After a **live** cycle writes `data/decisions/<date>.json`, also write
`data/decisions/latest.json` as a copy. A dry run must not write it.

A static page cannot list a directory, so this fixed path is the only way the
dashboard can find the current cycle.

Also pass the active records through to `build_state`, and do the same in
`scripts/update_state.py` if it needs no other change to do so.

## Tests

- `read_active_records` returns the full record, not just the thesis
- `read_active_theses` still returns plain strings for its existing caller
- Enrichment merges all four fields onto the matching position
- **A position with no record yields four nulls and does not raise**
- A position whose opening BUY was `rejected` rather than `executed` is not
  matched — only executed buys open a position
- `build_state` still performs no I/O

## Success criteria

```
pytest tests/ -q
python scripts/update_state.py
```

Tests pass, and `data/state.json` shows both current holdings carrying
`"thesis": null` — the honest result, since neither was bought by the system.
