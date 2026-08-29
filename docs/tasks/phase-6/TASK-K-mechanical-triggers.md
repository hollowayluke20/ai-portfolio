# Task K — the guardrails that exit positions

**Read first:** the 2026-08-29 sections in
`docs/decisions/0003-investment-rules.md` — "Told is not enforced",
"Mechanical triggers run before the AI", "The broad-US-equity cap is a
validation check", and "The cash floor drifts". They define exactly what is
required.

## Why this exists

Simulating a year found that **four configured rules were never enforced in
code**. The stop loss, both halves of the concentration trim, the broad-equity
cap and the cash ceiling all appear in `config/rules.json`, in the ADR, in the
README, and in the AI's prompt — and nothing checked any of them.

In the crash simulation the portfolio fell 28.6% with holdings well past −20%
and **no stop ever fired**, because no code existed to fire one.

The guardrails that *reject* bad orders work and fire often. The ones that
*exit* a position do not exist. This builds them.

## Files you own — create or edit ONLY these

```
src/portfolio/triggers.py      (new)
src/portfolio/validator.py     (one added check)
scripts/run_cycle.py           (wire triggers in)
sim/run.py                     (wire triggers in, so the simulation exercises them)
tests/test_triggers.py         (new)
tests/test_validator.py        (extend)
```

Do not touch `alpaca.py`, `state.py`, `storage.py`, `executor.py`,
`decisions.py`, `report.py`, `ai.py`, anything under `sim/` except `run.py`,
`index.html`, `assets/`, `config/`, `data/`, or any ADR.
**Do not commit or push.**

## 1. `src/portfolio/triggers.py`

```python
mechanical_decisions(state, rules) -> list[dict]
```

**A pure function.** State in, decisions out. No I/O, no clock, no network —
same discipline as `build_state` and `build_report`, and the reason this is
testable at all.

Returns decisions in the shape defined by `docs/tasks/phase-2/INTERFACE.md`,
with `trigger` set to `stop_loss` or `concentration_trim`.

| Condition | Emit |
|---|---|
| `unrealized_pl_pct <= rules["sell_triggers"]["stop_loss_pct"]` | `SELL`, `target_weight: 0.0`, trigger `stop_loss` |
| `weight > rules["sell_triggers"]["concentration_trim_threshold"]` | `TRIM` to `concentration_trim_target`, trigger `concentration_trim` |

A position can only produce **one** decision. If it is both down past the stop
and oversized, the **stop wins** — exiting entirely makes trimming moot.

Write real `thesis`, `risks` and `reason_for_action` text. These land in the
permanent decision record and the weekly email, and "trigger fired" tells a
reader nothing in six weeks. State the threshold, the actual value, and what
the rule is for.

`unrealized_pl_pct` or `weight` being `None` means **do not fire** — a missing
number is not a breach. Never treat absent data as a trigger condition.

## 2. `src/portfolio/validator.py` — the broad-equity cap

Add one check: a `BUY` whose resulting combined weight in
`rules["broad_us_equity_cap"]["tickers"]` would exceed
`rules["broad_us_equity_cap"]["limit"]` is rejected.

**Gates buys only.** An existing overweight position must stay sellable — the
same principle that already lets the universe gate buys but not exits.

Reason string must name the actual combined weight and the limit.

## 3. `scripts/run_cycle.py` and `sim/run.py`

```
state → mechanical_decisions(state, rules) → AI proposals → combined → execute
```

Mechanical decisions go **first** in the list. The executor already runs sells
and trims before buys, so this needs no change there.

**Tell the AI what is already being exited**, so it does not propose buying
back something the stop is selling. Pass the triggered tickers into `propose`.

Also: if `cash_weight` exceeds `rules["cash"]["ceiling"]`, add a health warning.
It is guidance, not a rejection — there is no sensible order to refuse for
holding too much cash.

## Tests

- A position at exactly the stop threshold fires; one a hair above does not
- A position past the trim threshold produces a `TRIM` to the target weight,
  not a full exit
- A position both stopped and oversized produces **one** decision, the stop
- `unrealized_pl_pct: None` fires nothing
- **A stop-loss decision survives validation from a portfolio of 8 positions**,
  where a discretionary sell would be blocked by the minimum position count
- The broad-equity cap rejects a buy that would breach it, and permits a sell
  from an already-breaching position
- `mechanical_decisions` performs no I/O

## Success criteria

```
pytest tests/ -q
python -m sim.run --days 250 --scenario crash --seed 1
python -m sim.run --days 250 --scenario meltup --seed 1
```

The crash run must report **stop_loss** decisions in its outcome counts, and
the meltup run must report **concentration_trim** decisions. If either is
absent the triggers are not wired in, whatever the tests say — a green suite
with a silent simulation is exactly how this gap survived the first time.
