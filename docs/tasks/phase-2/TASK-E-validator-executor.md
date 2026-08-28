# Task E — the validator and executor

**Read first:** `docs/tasks/phase-2/INTERFACE.md`, then ADR 0003 in full
(including both 2026-08-28 amendments) and ADR 0004.

You build the part that decides what is allowed and what actually reaches the
broker. **This is the first code in the project that can spend money.** Another
agent is building the decision engine at the same time; `src/portfolio/ai.py`
will not exist while you work. Do not wait for it and do not create it — test
against fixture decisions.

## Files you own — create ONLY these

```
src/portfolio/validator.py
src/portfolio/executor.py
src/portfolio/decisions.py
tests/test_validator.py
tests/test_executor.py
tests/test_decisions.py
```

Do not touch `ai.py`, `candidates.py`, `config/prompt.md`, `alpaca.py`,
`state.py`, `storage.py`, or any ADR. Do not commit or push.

You may **add** an order-submission function to nothing — if you need one,
say so rather than editing `alpaca.py`, which you do not own.

## 1. `src/portfolio/validator.py`

### `validate_static` — checks independent of execution order

1. Ticker is in `config/universe.json`
2. Ticker is tradable and fractionable (the universe file already guarantees
   this; verify rather than assume)
3. Resulting position weight is at or under the hard cap in `rules.json`
4. Resulting position count stays within the min/max
5. `action` is one of BUY / SELL / TRIM / HOLD
6. `target_weight` is a decimal fraction between 0 and 1 — **reject anything
   above 1**, which almost certainly means the AI returned a percentage
7. Notional is positive and above Alpaca's minimum
8. SELL and TRIM reference a ticker actually held

Annotate each decision with `valid` and `rejection_reason`. Never mutate the
input, never silently correct a value.

### `check_cash` — the dynamic check

Returns a rejection reason, or `None` if the trade fits. Called immediately
before each buy, against cash **as it stands at that moment**, not as it stood
when the cycle began.

**Compute against `totals.available_cash`** — cash net of pending buy orders.
Never `cash` alone, and never `buying_power`: Alpaca grants 4x margin, so
sizing from buying power would permit a 400k portfolio on 100k while every
individual check passed.

A buy must leave cash at or above the floor in `rules.json`.

## 2. `src/portfolio/executor.py`

```python
execute(decisions, state, rules, dry_run: bool) -> list[dict]
```

Order of operations, and this ordering is the whole design:

1. Run `validate_static` across everything first
2. Execute **sells and trims** — these free cash
3. Execute **buys in the order given**, calling `check_cash` before each and
   updating the running cash figure after each
4. Annotate every decision with `status`, `order_id`, `rejection_reason`

**Do not model dependencies between trades.** Cash is the only real dependency.
If the AI planned to sell Y to fund X, and Y fails but the cash is there
anyway, **X must still proceed** — dropping it would be wrong. If the cash is
not there, X is rejected for insufficient cash, naming the real cause.

**The AI's buy list is a priority order.** When cash runs out, the tail is
dropped and the head survives.

Orders are **notional** (dollar amounts), market, day, regular hours only
(ADR 0003).

`dry_run=True` does everything — validation, ordering, cash arithmetic, the
full annotated result — **except submitting to the broker**. Status becomes
`skipped` with a reason recording that it was a dry run. This flag must be
honoured absolutely; it is the safety rail for the first live cycle.

## 3. `src/portfolio/decisions.py`

`write_cycle(...)` writes `data/decisions/<YYYY-MM-DD>.json` per ADR 0004:
`schema_version`, `cycle_id`, `decided_at`, `portfolio_value_at_decision`,
`commentary`, `decisions[]`, `considered[]`.

**Two separate arrays.** `decisions[]` carries full thesis, risks and
reason_for_action for things acted on. `considered[]` carries ticker plus a
one-line verdict for candidates looked at and passed over. Keeping them apart
stops thirty declines from drowning three real decisions.

**Immutable once written.** Refuse to overwrite an existing file for the same
date; raise instead.

Rejected decisions are recorded, not discarded — a rejection is evidence the
guardrails worked.

`read_active_theses(decisions_dir, held_tickers)` returns the **original**
thesis for each held ticker, found by searching decision files backwards for
the BUY that opened it. This feeds the next cycle's prompt.

## Tests — no live orders, ever

- A weight above 1.0 is rejected (the percentage-vs-fraction trap)
- A ticker outside the universe is rejected
- A buy breaching the cash floor is rejected, with available_cash as the basis
- **Luke's case**: a sell is rejected but the buy it "funded" still proceeds
  when cash allows
- Buys are dropped from the tail, not the head, when cash runs short
- `dry_run=True` submits nothing and marks everything `skipped`
- Writing a cycle file twice for one date raises
- `read_active_theses` finds the opening BUY thesis for a held ticker

## Success criteria

```
pytest tests/ -q
```

All passing, including a dry-run test proving no order-submission path is
reachable when `dry_run=True`.
