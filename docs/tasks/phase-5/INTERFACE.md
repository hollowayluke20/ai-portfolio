# Phase 5 — the market simulator: interface

**Neither agent edits this file.**

Task I builds the **fakes** — a synthetic market and a fake broker. Task J
builds the **runner and the invariants**. They meet here.

## The point

The trading path is the least-tested code in this system. `submit_order` has
never run, the −20% stop has never fired, the 12% trim has never triggered, and
inception has never been stamped. Waiting for those to happen live means
waiting months and finding one bug at a time.

This runs the system through a simulated year in seconds, checking after every
step that things which must be true still are.

## Two rules that decide whether this is worth anything

**1. The simulator must never import `src/portfolio/alpaca.py`.**

ADR 0001's protection is that live trading is *structurally impossible*. A
"pretend mode" flag inside the broker layer would create a switch that could be
wrong in either direction. The simulator supplies its own account and prices to
the pure functions instead.

**2. The simulator reuses production logic. It never reimplements it.**

`validate_static`, `check_cash`, `execute`, `build_state`,
`build_history_row`, `append_history_row`, `write_json_atomic`,
`read_active_records`, `build_report` are all called for real. Only the
**market** and the **broker** are fake.

A simulator that reimplements the executor's ordering proves only that the
simulator works.

---

## Module: `sim/market.py` (Task I)

```python
class Market:
    def __init__(self, tickers: list[str], seed: int, scenario: str): ...
    def advance(self) -> datetime.date:      # next TRADING day; skips weekends
    def price(self, ticker: str) -> float | None   # None = halted or delisted
    def is_delisted(self, ticker: str) -> bool
    def today(self) -> datetime.date
```

Scenarios, all seeded and reproducible:

| Scenario | What it does |
|---|---|
| `calm` | Mild drift and noise |
| `crash` | −40% across the market over ~10 sessions, then a partial recovery |
| `gap` | One held name gaps −50% overnight, no warning |
| `zero` | One name declines to near zero over weeks |
| `halt` | One name returns `None` for 5 sessions, then resumes |
| `delist` | One name disappears permanently mid-position |
| `meltup` | One name triples, dragging it far past the 12% threshold |

## Module: `sim/broker.py` (Task I)

A fake account that behaves like Alpaca's, including the parts that caused real
bugs.

```python
class FakeBroker:
    def __init__(self, cash: float, market: Market): ...
    def account(self) -> dict          # same shape as alpaca.get_account()
    def positions(self) -> list[dict]  # same shape as alpaca.get_positions()
    def open_orders(self) -> list[dict]
    def submit(self, symbol, side, notional) -> dict   # queues, does NOT fill
    def settle(self) -> None           # fills queued orders at today's price
```

Behaviours that must be modelled, because each corresponds to something real:

- **Orders queue and fill on the NEXT session**, at that session's price — not
  at the price when submitted. This is the real behaviour that made fill prices
  unknown at decision time.
- **`cash` does not move for a queued order.** Only `buying_power` does. This
  is the bug that produced ADR 0003's `available_cash` rule.
- **A halted ticker cannot be traded**, and a position in it keeps its last
  known price.
- **A delisted ticker's position is removed** and its last value credited to
  cash.
- Fractional quantities, like notional orders really produce.

## Module: `sim/ai_stub.py` (Task I)

```python
def propose(state, rules, candidates, held_theses, mode="valid") -> dict
```

Same return shape as `src/portfolio/ai.py`. Deterministic given the state.

Modes: `valid` (sensible proposals toward the target position count),
`malformed` (returns unparseable output), `overweight` (proposes a 40% position),
`bad_ticker` (proposes something outside the universe), `overspend` (proposes
more than available cash).

The last four exist to prove the guardrails **reject** rather than to be
realistic.

## Module: `sim/invariants.py` (Task J)

```python
check(state, history, rules, day) -> list[str]    # violations; empty is a pass
```

Every one of these must hold after **every** step:

| Invariant |
|---|
| Position weights plus `cash_weight` sum to 1.0 (±0.01) |
| `total_value` equals cash plus the sum of position market values |
| `available_cash` equals `cash` minus pending buy notional |
| Cash is at or above the floor after any completed cycle |
| Position count within min/max once trading has begun |
| No position exceeds the trim threshold on leaving a cycle |
| Nothing is `NaN`, `Infinity`, or negative where it cannot be |
| History has one row per trading day: sorted, no duplicate dates |
| Inception is stamped exactly once and never changes |
| Every executed decision corresponds to a real position change |

## Module: `sim/run.py` (Task J)

```
python -m sim.run --days 250 --scenario crash --seed 7
python -m sim.run --days 250 --scenario calm --out sim-output/
```

Advances day by day. Refreshes state daily, runs a decision cycle weekly,
checks invariants after each. On violation: **stop, print the day, the
violated invariant, the state, and the decisions that led there.**

`--out` writes the resulting `state.json`, `history.json` and decision records
so the **dashboard can be pointed at a simulated year** — a mature portfolio
produced by real pipeline code rather than hand-written fixtures.

## Not in scope

Returns, strategy quality, or whether the AI picks well. This measures whether
the system stays internally consistent and refuses illegal trades. A simulated
portfolio that loses 60% while never breaking an invariant is a **pass**.
