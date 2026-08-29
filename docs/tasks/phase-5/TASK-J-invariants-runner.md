# Task J — the invariants and the runner

**Read first:** `docs/tasks/phase-5/INTERFACE.md`. Then ADR 0003 (the rules
being enforced) and ADR 0004 (the shape of state and history).

You build the part that drives a simulated year and checks that nothing has
gone wrong.

**If Task I has already been completed**, `sim/market.py`, `sim/broker.py`
and `sim/ai_stub.py` exist — read them, but treat `INTERFACE.md` as the
contract. Where the code and the interface disagree, say so rather than
quietly following the code.

**If they do not exist yet**, code against `INTERFACE.md` and test with your
own fixtures. Do not create them: they belong to Task I.

## Files you own — create ONLY these

```
sim/invariants.py
sim/run.py
tests/test_invariants.py
src/portfolio/executor.py    (ONE narrow change, described below)
```

Do not touch `sim/market.py`, `sim/broker.py`, `sim/ai_stub.py`, `alpaca.py`,
`state.py`, `validator.py`, `decisions.py`, `config/`, `data/`, or any ADR.
**Do not commit or push.**

## The one production change you may make

`executor.execute()` calls a module-level `submit_order`, which imports
`alpaca`. The simulator must supply its own submitter without the executor ever
reaching a broker.

Add an optional parameter:

```python
def execute(decisions, state, rules, universe, dry_run, submit=None):
    # submit defaults to the real submit_order
```

Nothing else in that file. This is dependency injection, and it also makes the
submission path testable for the first time — currently nothing covers it.

## The rule that makes this worth building

**Reuse production logic. Never reimplement it.**

`validate_static`, `check_cash`, `execute`, `build_state`,
`build_history_row`, `append_history_row`, `write_json_atomic`,
`read_active_records` and `build_report` are all called for real. Only the
market and broker are fake.

If the runner reimplements the executor's sell-then-buy ordering, a passing run
proves only that your reimplementation agrees with itself.

## `sim/invariants.py`

```python
check(state, history, rules, day) -> list[str]
```

Returns violation descriptions; empty means pass. Implement every invariant in
`INTERFACE.md`.

Each message must name **the day, the invariant, and the actual numbers** —
"weights sum to 0.9994 on 2026-11-04, expected 1.0" is investigable;
"invariant failed" is not.

Tolerances belong only where floating point requires them (±0.01 on a weight
sum). **A cash floor breach has no tolerance** — it is either above the floor
or it is a bug.

## `sim/run.py`

```
python -m sim.run --days 250 --scenario crash --seed 7
python -m sim.run --days 250 --scenario calm --out sim-output/
```

Each simulated day:

1. `market.advance()`
2. `broker.settle()` — yesterday's orders fill at today's prices
3. Build state from the broker, exactly as `update_state.py` does
4. Append a history row
5. **Check invariants. On violation, stop.**
6. On decision days (weekly): candidates → AI stub → `execute` with the fake
   submitter → write the decision record → check invariants again

**Stamp inception** the first time a cycle's own orders result in holdings,
matching the production rule.

On failure, print the day, the violated invariant, the state, and the decision
record that produced it — then exit non-zero.

At the end print a summary: days simulated, cycles run, orders submitted,
filled, and rejected **with a count per rejection reason**. A run where nothing
was ever rejected has not tested the guardrails and should say so loudly.

`--out` writes `state.json`, `history.json` and `data/decisions/` into that
directory so the dashboard can be pointed at a simulated year.

## Tests — `tests/test_invariants.py`

Feed `check()` deliberately broken states and confirm it **catches** them.
An invariant checker that never fails is worse than none, because it is
trusted.

- Weights summing to 0.98 is caught
- `total_value` disagreeing with cash plus positions is caught
- Cash below the floor is caught
- A duplicate history date is caught
- An out-of-order history date is caught
- A `NaN` in a numeric field is caught
- A clean state produces **no** violations

## Success criteria

```
pytest tests/ -q
python -m sim.run --days 250 --scenario calm --seed 1
python -m sim.run --days 250 --scenario crash --seed 1
python -m sim.run --days 250 --scenario meltup --seed 1
```

A clean run reports zero violations **and a non-zero count of rejected
orders** — if the guardrails never fired across 250 days, the simulation was
too gentle to be evidence.

`crash` and `meltup` should exercise the stop and the trim respectively. If
they do not fire, say so in the summary rather than reporting a silent pass.
