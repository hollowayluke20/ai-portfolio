# Task C — pending orders

**Read first:** the two amendments dated 2026-08-28 in
`docs/decisions/0003-investment-rules.md` ("Available cash is not the same as
cash") and `docs/decisions/0004-data-contract.md` ("Pending orders are part of
the state"). They define exactly what is required. Then
`docs/tasks/phase-1/INTERFACE.md` for house style.

## Why this exists

Two orders were placed manually while the US market was closed. Alpaca
reported them as `accepted` with `filled_qty: 0`, and:

```
cash          100000     <- did NOT move
buying_power  399975     <- dropped by exactly the order value
```

Our pipeline correctly reported "0 positions, 100% cash". That is true and
dangerously incomplete: money was already committed and nothing in
`state.json` could say so. A later run would read the full cash balance and
commit it a second time.

## Files you own — edit or create ONLY these

```
src/portfolio/alpaca.py      (add one function)
src/portfolio/state.py       (extend build_state)
scripts/update_state.py      (wire it through)
tests/test_alpaca.py         (extend)
tests/test_state.py          (extend)
```

**Do not touch** `src/portfolio/storage.py`, `src/portfolio/config.py`,
anything in `config/`, `data/`, `.github/`, or any ADR. **Do not commit or
push** — Luke reviews first.

## 1. `alpaca.py` — add `get_orders`

```python
get_orders(status: str = "open") -> list[dict]
# [{"order_id": "...", "symbol": "NVDA", "side": "buy",
#   "notional": 20.0, "qty": None, "status": "accepted",
#   "submitted_at": "2026-08-28T12:43:25Z", "filled_qty": 0.0}]
```

Uses `GET /v2/orders`. Follow the existing house style exactly: same
`_request` helper, same retry behaviour, same timeout.

**Important:** `notional` and `qty` are mutually exclusive on an Alpaca order
— an order specifies one or the other, and the unused one comes back `null`.
So they must stay nullable here. Do **not** run them through the strict
`_to_float`, which now raises on `None`; that behaviour is correct for prices
and wrong for these two fields. Add a nullable variant rather than weakening
the strict one.

Normalise `submitted_at` with the existing `_normalise_ts`.

## 2. `state.py` — extend `build_state`

Add a `pending_orders` argument. `build_state` **stays a pure function** — no
network, no clock, no file access.

Produce, exactly as specified in the ADR 0004 amendment:

- `pending_orders[]` in the state document
- `totals.committed_cash` — total notional of pending **buy** orders only.
  Sells do not consume cash.
- `totals.available_cash` — `cash - committed_cash`

`cash` keeps reporting what Alpaca says, so the raw broker figure is never
lost. Pending orders do **not** count toward position weights, because nothing
has been bought yet — weights and `total_value` are unchanged by this task.

An order with `notional: null` (a quantity-based order) cannot have its cash
cost known without a price. Treat its committed cash as `qty * current_price`
when that position exists, and otherwise record it in `pending_orders` but
add a **health warning** rather than guessing at zero. Silently treating an
unknown commitment as zero is the bug this whole task exists to fix.

## 3. `scripts/update_state.py` — wire it through

Fetch open orders, pass them into `build_state`, and print a line showing the
count and committed cash. If `available_cash` differs from `cash`, say so in
the output — that difference is the thing a human needs to notice.

## Tests

- `committed_cash` counts buys and ignores sells
- `available_cash` equals `cash - committed_cash`
- No pending orders leaves `available_cash == cash` and an empty array
- A `notional: null` order produces a health warning rather than a zero
- Pending orders do not change any position weight or `total_value`
- `get_orders` keeps `notional`/`qty` as `None` rather than raising

## Success criteria

```
pytest tests/ -q
python scripts/update_state.py
```

Tests pass, and the run reports two pending orders with roughly $25 of
committed cash while `cash` still reads 100000. If the orders have filled by
the time you run it, that is also a pass: zero pending orders, and
`available_cash == cash`.
