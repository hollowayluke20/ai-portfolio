# Task D — the decision engine

**Read first:** `docs/tasks/phase-2/INTERFACE.md`, then ADR 0003 in full
(including both 2026-08-28 amendments) and ADR 0004.

You build what the AI is shown and what it says back. Another agent builds the
validator and executor at the same time. **You never submit an order** — you
produce proposals, nothing more.

## Files you own — create ONLY these

```
src/portfolio/ai.py
src/portfolio/candidates.py
config/prompt.md
tests/test_ai.py
tests/test_candidates.py
```

Do not touch `validator.py`, `executor.py`, `decisions.py`, anything in
`data/`, or any ADR. Do not commit or push.

## 1. `config/prompt.md` — the strategy, as data

This is the most important file in the task. **The strategy must be editable
without touching code**, because Luke intends to iterate on it once the
machinery works.

A markdown template with `{placeholders}` filled in at call time. It must
contain:

- **Role.** A disciplined portfolio manager operating under fixed rules.
- **The rules**, injected from `config/rules.json` — never restated by hand, or
  the prompt and the validator will drift apart. This is the whole reason that
  file exists.
- **Current portfolio state**: total value, available cash, positions with
  weights and unrealised P&L, pending orders.
- **The active thesis for every held position**, and an explicit instruction to
  say whether each still holds.
- **The candidate list.**
- **Explicitly: the buy list is a priority order.** If cash runs short the tail
  is dropped, so the most important buy goes first.
- **Explicitly: fill prices are unknown at decision time.** Orders are placed
  after the close and fill at the next open, at a price nobody yet knows. The
  reasoning must not depend on getting a specific price.
- **A `considered` verdict for every candidate not acted on** — one line each.

## 2. `src/portfolio/candidates.py`

`select_candidates(universe, held, week_index)` returning ~30 tickers:

- **every ETF** in the sleeve from `config/rules.json`
- **plus a rotating slice** of S&P names, so a different slice appears each week
  and the whole universe is seen over time

Deterministic: same inputs, same output, always. Keep it dumb enough to explain
in one sentence — the moment it gets clever it becomes a second, undocumented
strategy nobody reviewed.

## 3. `src/portfolio/ai.py`

Calls Gemini. Key from `GEMINI_API_KEY` (already in `.env`, gitignored).

- **Model name lives in `config/rules.json`**, pinned to `gemini-3.6-flash`.
  Do not hardcode it and do not fall back to another model if it 404s —
  `gemini-2.5-flash` appeared in the account's own model list and then refused
  to run, so a silent fallback would be a silent change of strategy.
- Use `responseMimeType: application/json` **and** a `responseSchema`. This has
  been verified working against this key — it returned `target_weight: 0.063`
  as a float on the first attempt.
- Retry **once** on malformed or schema-invalid output. If the second attempt
  also fails, raise `AIError`. **Never repair, guess at, or partially parse a
  bad response.**
- Network failures reuse the same retry approach as `alpaca.py`. Match house
  style.
- Log the token counts from `usageMetadata` so cost stays visible.

## Tests — no live API calls

- The prompt template renders with every placeholder filled and no `{}` left
- Rules injected into the prompt match `config/rules.json` exactly
- `select_candidates` is deterministic and includes every ETF
- Different `week_index` values give different S&P slices
- A malformed response triggers exactly one retry, then raises `AIError`
- A schema-valid response parses into the interface shape

Use a recorded sample response as a fixture. Do not hit the API in tests.

## Success criteria

```
pytest tests/ -q
python -c "from src.portfolio.candidates import select_candidates; print(len(select_candidates(['SPY','QQQ','MSFT','AAPL'],[],0)))"
```

Tests pass, and the prompt template renders into something a human can read
and immediately understand as an instruction to a portfolio manager.
