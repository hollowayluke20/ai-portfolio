# Phase 1 — the interface between the two halves

**Neither agent edits this file.** It is the contract that lets Task A and
Task B be built at the same time without either waiting for the other.

Task A builds the **broker layer** — everything that talks to the outside
world. Task B builds the **state layer** — everything that turns data into
`data/state.json`. They meet here.

---

## Module: `src/portfolio/alpaca.py` (built by Task A)

Raw HTTP via `requests`. No SDK. Every function returns plain Python types
with **numeric strings already coerced to `float`** — Alpaca returns numbers as
strings and no caller should have to remember that.

```python
get_account() -> dict
# {"cash": 100000.0, "equity": 100000.0, "buying_power": 400000.0,
#  "status": "ACTIVE", "currency": "USD"}

get_positions() -> list[dict]
# [{"symbol": "MSFT", "qty": 14.8231, "avg_entry_price": 425.50,
#   "current_price": 431.02, "market_value": 6389.11,
#   "unrealized_pl": 81.83}]
# Empty list when there are no positions. This is the Phase 1 case.

get_latest_price(symbol: str) -> tuple[float, str]
# (431.02, "2026-09-11T20:00:00Z")  -- price and the timestamp it is FROM.
# Uses the market data host, not the trading host.

list_assets() -> list[dict]
# [{"symbol": "MSFT", "tradable": True, "fractionable": True,
#   "exchange": "NASDAQ", "name": "Microsoft Corporation"}]

is_trading_day(day: datetime.date) -> bool
# True if US equity markets were open. Uses /v2/calendar.
```

## Module: `src/portfolio/config.py` (built by Task A)

```python
load_rules() -> dict          # parsed config/rules.json
load_universe() -> list[str]  # tickers from config/universe.json
load_inception() -> dict | None
# {"inception_date": "2026-09-11", "inception_value": 100000.0,
#  "benchmark_ticker": "SPY", "benchmark_inception_price": 771.10}
# None until the first trade is placed. Phase 1 always sees None.

save_inception(d: dict) -> None   # writes config/inception.json, refuses to overwrite
```

## Module: `src/portfolio/state.py` (built by Task B)

```python
build_state(account, positions, spy_price, spy_as_of,
            rules, inception, generated_at, run) -> dict
# PURE FUNCTION. No network, no file access, no clock reads.
# Returns a dict matching ADR 0004's state.json schema.
# Everything it needs is an argument, which is what makes it testable.

build_history_row(state: dict) -> dict
# {"date","portfolio_value","portfolio_return_pct",
#  "benchmark_price","benchmark_return_pct","cash"}
```

## Module: `src/portfolio/storage.py` (built by Task B)

```python
write_json_atomic(path, data) -> None
# Write to a temp file in the same directory, then os.replace().
# A crash mid-write must never leave a partial or empty state.json.

append_history_row(path, row) -> None
# Idempotent by date: a row for a date that already exists REPLACES it.
# Never appends a duplicate. Rows stay sorted by date ascending.

read_json(path, default=None)
```

---

## Rules both halves obey

- **Money is `float`, rounded to 2dp on output.** Share quantities keep full
  precision.
- **Weights and percentages are decimal fractions.** `0.0636`, never `6.36`.
- **Timestamps are ISO 8601 UTC ending in `Z`.** Dates are `YYYY-MM-DD`.
- **`inception` may be `None`.** In Phase 1 it always is, because inception is
  stamped at the first trade (ADR 0003). When it is `None`, `performance` and
  `benchmark` in `state.json` are `null` — not zero, not omitted.

## Not in Phase 1

No orders, no AI, no trading of any kind. Phase 1 can only read. If a task
seems to require placing an order, the task has been misread.
