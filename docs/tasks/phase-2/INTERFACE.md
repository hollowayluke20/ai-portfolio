# Phase 2 — the interface between the two halves

**Neither agent edits this file.**

Task D builds the **decision engine** — what the AI is shown and what it says
back. Task E builds the **validator and executor** — what is allowed and what
actually reaches the broker. They meet here.

Phase 2 is the first code that can spend money. Read ADR 0003 in full,
including both 2026-08-28 amendments, before writing anything.

---

## The shape of a decision

Produced by Task D, consumed by Task E, persisted by Task E.

```python
{
  "ticker": "MSFT",
  "action": "BUY",              # BUY | SELL | TRIM | HOLD
  "target_weight": 0.063,       # decimal fraction, never a percentage
  "thesis": "...",              # why this position should exist
  "risks": "...",               # what would make it wrong
  "reason_for_action": "...",   # why act NOW, distinct from the thesis
}
```

Task E adds, after execution:

```python
  "trigger": "ai",              # ai | stop_loss | concentration_trim
  "status": "executed",         # executed | rejected | skipped
  "notional": 6300.00,          # USD ordered; null for HOLD
  "order_id": "...",            # or null
  "rejection_reason": None,     # which check failed, or null
```

## Module: `src/portfolio/candidates.py` (Task D)

```python
select_candidates(universe: list[str], held: list[str], week_index: int) -> list[str]
# ~30 tickers: every ETF in the sleeve, plus a rotating slice of S&P names.
# Deterministic - the same inputs always give the same list.
```

## Module: `src/portfolio/ai.py` (Task D)

```python
propose(state: dict, rules: dict, candidates: list[str],
        held_theses: dict[str, str]) -> dict
# {"commentary": str, "decisions": [...], "considered": [{"ticker","verdict"}]}
# Raises AIError if output is unusable after one retry.
```

## Module: `src/portfolio/validator.py` (Task E)

```python
validate_static(decisions, state, rules, universe) -> list[dict]
# Annotates each decision with valid / rejection_reason.
# STATIC checks only - nothing that depends on execution order.

check_cash(decision, running_cash, total_value, rules) -> str | None
# The DYNAMIC check. Returns a rejection reason, or None if the trade fits.
# Called immediately before each buy, against cash as it stands at that moment.
```

## Module: `src/portfolio/executor.py` (Task E)

```python
execute(decisions, state, rules, dry_run: bool) -> list[dict]
# Sells and trims first, then buys in the AI's given order.
# Re-checks cash before EACH buy. Returns decisions annotated with outcome.
# dry_run=True does everything except submit to the broker.
```

## Module: `src/portfolio/decisions.py` (Task E)

```python
write_cycle(path, cycle_id, decided_at, state, ai_output, executed) -> dict
# Writes data/decisions/<YYYY-MM-DD>.json per ADR 0004. Immutable once written.
read_active_theses(decisions_dir, held_tickers) -> dict[str, str]
# The ORIGINAL thesis for each currently-held ticker, for the next prompt.
```

---

## Rules both halves obey

- **Decimal fractions everywhere.** `0.063`, never `6.3`.
- **The AI's buy list is a priority order.** When cash runs short the tail is
  dropped, not the head. The AI is told this in the prompt.
- **Cash is the only dependency between decisions.** Do not model trade
  interdependency: sells free cash, buys consume it, and a buy is rejected only
  when the cash is not there at the moment it runs.
- **Sizing uses `totals.available_cash`**, never `cash` and never
  `buying_power` (ADR 0003, both amendments).
- **Malformed AI output means no trades at all**, logged. Never a best guess.
- **`dry_run` must be honoured absolutely.** In dry-run nothing is submitted,
  and the decision file records what *would* have happened.
