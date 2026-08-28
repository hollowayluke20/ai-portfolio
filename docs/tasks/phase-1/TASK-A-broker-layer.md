# Task A — the broker layer

**Read first:** `docs/tasks/phase-1/INTERFACE.md`, then ADRs 0001, 0003 and 0004
in `docs/decisions/`.

You are building everything that talks to the outside world. Another agent is
building the state layer at the same time, against the same interface.

## Files you own — create ONLY these

```
requirements.txt
config/rules.json
src/portfolio/__init__.py
src/portfolio/alpaca.py
src/portfolio/config.py
scripts/refresh_universe.py
tests/test_alpaca.py
tests/test_config.py
```

**Do not create, edit or delete any other file.** In particular do not touch
`src/portfolio/state.py`, `src/portfolio/storage.py`, anything under `data/`,
or any ADR. Do not run `git commit` or `git push` — Luke reviews and commits.

## What to build

### src/portfolio/alpaca.py

Raw HTTP with `requests`. No Alpaca SDK — we write the requests ourselves so
that every call made to the broker is visible in our own code.

Implement the five functions in `INTERFACE.md` exactly as specified.

1. **Credentials from environment**: `APCA_API_KEY_ID`, `APCA_API_SECRET_KEY`,
   `APCA_API_BASE_URL`. Load a local `.env` if present (it exists already and
   is gitignored). Never hardcode a credential and never log one.
2. **Assert the paper endpoint at import time.** If `APCA_API_BASE_URL` is not
   the paper host, raise immediately with a clear message. This is the
   structural protection from ADR 0001 and it is not optional.
3. **Market data uses a different host** from trading. Same credentials.
4. **Retry 3 times with exponential backoff** on connection errors, timeouts
   and 5xx responses. Do **not** retry 4xx — a 403 means the key is wrong and
   retrying cannot fix it. Raise clearly when retries are exhausted.
5. **Coerce numeric strings to float** before returning. Callers must never
   see a number as a string.
6. Set a timeout on every request. A hung call must not hang the workflow.

### config/rules.json

Every number from ADR 0003, as data rather than code. This file has **two
consumers**: the validator that enforces the rules, and the prompt that tells
the AI about them. One file, so the two can never drift apart.

Include: target, minimum and maximum position count; per-position weight target
and hard cap; cash floor and ceiling; the stop-loss threshold; the
concentration-trim threshold and its target; the combined broad-US-equity cap
and which tickers it covers; and the ETF universe list from ADR 0003.

### src/portfolio/config.py

The four functions in `INTERFACE.md`. `save_inception` must **refuse to
overwrite** an existing `config/inception.json` — a baseline that can be
silently rewritten is worse than no baseline at all (ADR 0004).

### scripts/refresh_universe.py

Builds `config/universe.json`.

1. Fetch S&P 500 constituents from the maintained CSV at
   `raw.githubusercontent.com/datasets/s-and-p-500-companies/main/data/constituents.csv`
2. Add the ETF list from `config/rules.json`
3. Cross-check **every** ticker against `list_assets()`, keeping only those
   that are tradable **and** fractionable
4. Write `config/universe.json` with the surviving tickers, a `generated_at`
   timestamp, the source URL, and what was dropped with reasons
5. Print a summary: how many fetched, how many dropped, why

Fractionable matters because ADR 0003 uses notional orders, which only work on
fractionable assets.

## Tests — pure logic only, no network

Do not mock the whole Alpaca API; you would only be testing your mocks. Cover:

- Numeric coercion turns a numeric string into a float
- Retry logic retries on 500 and does **not** retry on 403
- The paper-endpoint assertion raises when handed a live URL
- `load_rules()` parses the real `config/rules.json`
- `save_inception()` refuses to overwrite an existing file

## Success criteria

```
pytest tests/ -q
python scripts/refresh_universe.py
python -c "from src.portfolio.alpaca import get_account; print(get_account())"
```

Tests pass; the refresh writes roughly 500 tickers; and that last command
prints an account showing **cash of 100000.0** and **status ACTIVE**. That is
the whole point of Task A.
