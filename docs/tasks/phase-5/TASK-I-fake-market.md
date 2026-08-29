# Task I — the fake market and broker

**Read first:** `docs/tasks/phase-5/INTERFACE.md`. Then ADR 0003 for the rules
the guardrails enforce, and ADR 0004 for the shape of state.

You build the fakes. Another agent builds the runner and the invariants at the
same time, against the same interface.

## Files you own — create ONLY these

```
sim/__init__.py
sim/market.py
sim/broker.py
sim/ai_stub.py
tests/test_sim_fakes.py
```

Do not touch anything under `src/`, `scripts/`, `config/`, `data/`, `.github/`,
`index.html`, `assets/`, or any ADR. **Do not commit or push.**

Standard library only. No new dependency.

## The rule that makes this worth building

**Never import `src/portfolio/alpaca.py`.** Not for constants, not for types,
not for convenience. The whole point is that this cannot reach a real broker,
and an import is how that guarantee erodes.

## `sim/market.py`

Seeded price series for a set of tickers, advancing one **trading day** at a
time — weekends skipped, because the real pipeline skips them and history is
keyed by trading day.

Implement the seven scenarios in `INTERFACE.md`. Each must be **reproducible
from its seed**: the same seed and scenario always produce the same prices, or
a failure cannot be investigated.

Three behaviours matter more than realistic-looking prices:

- **`price()` returns `None` for a halted or delisted ticker.** Not zero, not
  the last price. `None` is what "no price exists" means, and the pipeline
  raises on missing money by design (`_to_float`). Whether that propagates
  sensibly is exactly what we are testing.
- **A delisted ticker stays delisted.** No resurrection.
- Prices are positive floats, rounded to 2dp, and never zero — a genuine zero
  should come from the `zero` scenario approaching it, not from arithmetic.

## `sim/broker.py`

A fake account matching the shape of `alpaca.get_account()` and
`alpaca.get_positions()` — including the fields that caused real bugs:

- `name` on every position (the dashboard's company column)
- `buying_power` at 4× equity (the margin that ADR 0003 refuses to size from)

**Model these exactly. Each corresponds to something that actually happened:**

1. **Orders queue; they do not fill on submission.** `submit()` records an
   order and returns it as `accepted` with `filled_qty: 0`. `settle()` fills it
   at the *next* session's price. This is the behaviour that made fill prices
   unknown at decision time.
2. **`cash` does not move for a queued order.** Only `buying_power` drops. This
   is precisely the bug that produced the `available_cash` rule — if the fake
   moves cash, the simulation cannot reproduce it.
3. **A halted ticker rejects orders** and its position keeps its last known
   price.
4. **A delisted ticker's position is removed**, its last value credited to cash.
5. **Fractional quantities**, as notional orders produce.

## `sim/ai_stub.py`

Same return shape as `src/portfolio/ai.py` — `commentary`, `decisions`,
`considered` — and deterministic for a given state.

`mode="valid"` proposes sensible moves toward the target position count, holds
what it holds, and writes a plausible thesis, risks and business line.

The other four modes exist to prove the guardrails **reject**, not to be
realistic: `malformed`, `overweight`, `bad_ticker`, `overspend`. Each should
produce output that is structurally plausible but breaks exactly one rule.

## Tests

- A seed reproduces an identical price series
- Each scenario does what it claims: `crash` drops ~40%, `gap` moves one name
  ~−50% in a single step, `halt` returns `None` for exactly 5 sessions,
  `delist` never returns
- Weekends never appear
- **A submitted order does not fill until `settle()`**, and fills at the *new*
  price rather than the submission price
- **`cash` is unchanged by a queued buy, while `buying_power` falls**
- A delisted position leaves the book and its value lands in cash
- Each AI stub mode produces the specific defect it claims

## Success criteria

```
pytest tests/test_sim_fakes.py -q
```

Passing, with no import of `src.portfolio.alpaca` anywhere in `sim/` — check
with:

```
grep -r "alpaca" sim/
```

which should return nothing.
