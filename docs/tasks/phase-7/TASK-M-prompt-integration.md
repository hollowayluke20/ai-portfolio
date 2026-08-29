# Task M — putting the market in front of the AI

Read `INTERFACE.md` first. Task L is building `src/portfolio/marketdata.py` to
the contract written there. Code against that contract; do not wait for it and
do not reimplement any of it.

**You own:** `config/prompt.md`, `src/portfolio/ai.py`,
`scripts/refresh_universe.py`, `config/universe.json`, and the affected tests.
**You must not touch:** `src/portfolio/marketdata.py`, `validator.py`,
`executor.py`, `triggers.py`, `rules.json`.

## 1. Stop throwing away the company names

`scripts/refresh_universe.py:35` currently does:

```python
return [row["Symbol"].strip() for row in reader if row.get("Symbol")]
```

The CSV it just parsed also carries `Security` (company name) and
`GICS Sector`, and both are discarded on that line. Verified live on
2026-08-29 — the columns are `Symbol, Security, GICS Sector,
GICS Sub-Industry, Headquarters Location, Date added, CIK, Founded`, 503 rows.
Take `Security` and `GICS Sector`; ignore the rest. Meanwhile
`candidates.py`'s docstring defends showing the whole index on the grounds that
*"the entire S&P 500 with company names and sectors is about 4,800 tokens"* —
describing data that has never reached the prompt.

Keep them. `config/universe.json` gains a `metadata` map:

```json
"metadata": {
  "MPWR": {"name": "Monolithic Power Systems", "sector": "Information Technology"}
}
```

Bump `schema_version`. ETFs are not in the CSV — give them a short hand-written
name and an asset-class label (`"GLD": {"name": "Gold", "sector": "Commodity"}`)
so the sleeve is legible too. Consumers must tolerate a missing entry rather
than raising: the file on disk was written by the old script.

## 2. `{CANDIDATES}` becomes a table

Replace `", ".join(candidates)` in `render_prompt`. One line per ticker, ETF
sleeve first (as now), then the rest:

```
AAPL  Apple Inc.  Information Technology  $319.70  1m +3.2%  12m +18.9%  4.1% off high  vol 24%  above 200d
```

- Decimal fractions become percentages **for display only**. The rules block
  still says `0.063` and the AI still answers in decimals — say so plainly in
  the prompt, because this table now shows it percent signs and that is exactly
  the kind of inconsistency that produces a `6.3` where `0.063` was wanted.
- `None` renders as `n/a`, never `0`. Append `(listed recently)` when
  `bars_available < 253` so a wall of `n/a` has a visible cause.

## 3. A market context block, above the candidates

New `{MARKET_CONTEXT}` placeholder in `config/prompt.md`. The same fields for
the 15 ETFs in `rules.json`'s `etf_universe`, plus:

```
Market breadth: 71.4% of the 518-name universe is above its 200-day average.
```

Explain that line in the prompt in one sentence. Breadth is the difference
between "the index rose" and "most shares rose", and the AI has no idea what
the number means unless told.

State in this section that these figures are **as of the last close**, and that
orders fill at the *next* open at an unknown price — the existing prompt
already makes that point about fill prices and it must not now be contradicted
by a table of exact numbers.

## 4. One new field on every decision: `basis`

Add to the decision schema, required, one of:

`momentum` · `mean_reversion` · `allocation` · `thesis_change` · `other`

**This is a three-line change, verified against the current file.** Add
`"basis"` to the `_DECISION_FIELDS` tuple at `ai.py:39`, and add its property
to `RESPONSE_SCHEMA`:

```python
"basis": {
    "type": "string",
    "enum": ["momentum", "mean_reversion", "allocation",
             "thesis_change", "other"],
},
```

`"required": list(_DECISION_FIELDS)` at `ai.py:64` and the validation loop at
`ai.py:261` both read that tuple, so both pick the field up with no further
edit. Do not add it in three places by hand — that is how the two drift.

And in the prompt: *state which of these your action rests on. If you are
buying because it has gone up, say `momentum`. If you are buying because it has
fallen, say `mean_reversion`.*

**Why this exists.** Hand a language model a column of 12-month returns and it
will buy whatever went up most, while producing fluent prose about why. This
field does not prevent that. It makes it **countable** — after twenty cycles
the decision log answers "is it just chasing winners?" arithmetically instead
of by reading twenty essays. It is one enum and it is the cheapest measurement
instrument in the project.

Carry it into `data/decisions/*.json` and surface it in the dashboard. **This
is safe and additive** — checked: `report.py`, `decisions.py` and
`dashboard.js` all read decision fields with `.get()` / null-guards, so an
extra key breaks nothing and no consumer needs restructuring. Show it as a
small label beside the action, not a new column.

## 5. Wire it up

In the cycle, before rendering: fetch bars for the universe over a **400
calendar day** lookback (252 trading bars needs ~365 days; 400 gives room for
holidays), compute features `as_of` the last close, pass them to
`render_prompt`.

Measured cost: 16 requests, ~16 seconds. No caching. If it ever needs caching,
that is a decision with a reason, not a precaution.

**Failure policy — decide it, do not default into it.** If the bar fetch fails,
the cycle must **abort**, not fall back to the old blind prompt. A cycle that
silently reverts to picking stocks from memory while the decision log looks
normal is precisely the failure this project's `what-broke.md` exists to catch.
Log it and exit non-zero.

## Tests

- `render_prompt` leaves no unfilled placeholder (the existing guard covers
  this — make sure it still fires with the two new tokens).
- A `None` feature renders `n/a`, never `0` or `0.0%`.
- A ticker missing from `metadata` renders without raising.
- A decision without `basis` is rejected by the schema.
- Token sanity: render with the full 518-ticker universe and assert the prompt
  is under 60,000 characters. Not a hard limit — a tripwire, so that a future
  change adding two more columns per row is noticed rather than discovered as
  a bill.

## Done when

A dry run produces a prompt containing real prices, and a decision carrying a
`basis`. Save that prompt to `data/dry-runs/` as usual and read it yourself
before anything goes live — the point of this phase is what the AI can see, so
look at what it can now see.
