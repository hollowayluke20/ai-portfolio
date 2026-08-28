# Task B — the state layer

**Read first:** `docs/tasks/phase-1/INTERFACE.md`, then ADR 0004
(`docs/decisions/0004-data-contract.md`) and the worked examples in
`data/examples/`.

You are building everything that turns broker data into stored state. Another
agent is building the broker layer at the same time. **`src/portfolio/alpaca.py`
will not exist while you work — do not wait for it, and do not create it.**
Code against the documented interface and test with fixtures.

## Files you own — create ONLY these

```
src/portfolio/state.py
src/portfolio/storage.py
tests/test_state.py
tests/test_storage.py
tests/fixtures/          (any fixture files you need)
```

**Do not create, edit or delete any other file.** In particular do not touch
`src/portfolio/alpaca.py`, `src/portfolio/config.py`, anything under `config/`
or `data/examples/`, `requirements.txt`, or any ADR. Do not run `git commit` or
`git push` — Luke reviews and commits.

You need nothing outside the Python standard library.

## What to build

### src/portfolio/state.py

**`build_state` must be a pure function.** No network, no file reads, no clock
reads. Everything it needs arrives as an argument — that is what makes it
testable, and it is the entire reason the signature looks the way it does.

It returns a dict matching ADR 0004's schema exactly. Read that ADR properly;
the field list is not negotiable.

The parts that are easy to get wrong:

- **The `weight` denominator is `total_value`, which includes cash.** All
  position weights plus `cash_weight` must sum to 1.0. ADR 0004 states this
  explicitly because an earlier contract left it ambiguous and nobody noticed.
- **`generated_at` and `market_data_as_of` are different values.** The first is
  when the file was written, the second is when the prices are from. They
  differ because the free data feed is 15 minutes delayed.
- **When `inception` is `None`**, `performance` and `benchmark` are `null` —
  not zero, not omitted, not an empty object. In Phase 1 this is always the
  case, because inception is stamped at the first trade.
- **`buying_power` is recorded but never used in any calculation.** Alpaca
  grants 4x margin by default, so anything derived from it could authorise a
  400k portfolio on 100k.
- Money rounds to 2dp on output. Weights and percentages are decimal fractions,
  so 6.36% is `0.0636` and never `6.36`.

### src/portfolio/storage.py

The three functions in `INTERFACE.md`.

`write_json_atomic` is the important one. `state.json` is **replaced** on every
run, so a crash mid-write destroys the last good copy — and the dashboard then
shows broken data rather than slightly old data. Write to a temp file in the
same directory, then `os.replace()`, which is atomic on both Windows and POSIX.

`append_history_row` must be **idempotent by date**. Running twice on the same
day replaces that row rather than adding a second. A retried workflow must not
corrupt the performance chart. Keep rows sorted by date ascending.

## Tests

Use `data/examples/state.example.json` and `history.example.json` as fixtures —
they exist already and reconcile to the penny.

Cover at minimum:

- Position weights plus `cash_weight` sum to 1.0, within float tolerance
- `totals.total_value` equals cash plus the sum of position market values
- `inception=None` yields `null` for both `performance` and `benchmark`
- An **empty positions list** produces valid state. This is the Phase 1 case:
  the account holds 100,000 in cash and owns nothing
- Appending the same date twice leaves exactly one row, carrying the later values
- `write_json_atomic` leaves the original file untouched if serialisation fails

## Success criteria

```
pytest tests/ -q
```

All passing, including a test that builds state from an empty portfolio of
100,000 cash and produces output that validates against ADR 0004.

You should be able to finish and prove this work without `alpaca.py` ever
existing. If you find that you cannot, the interface is wrong — say so rather
than building around it.
