"""The broker layer — raw HTTP against Alpaca's paper API.

No SDK. Every request Alpaca receives is written here in plain sight, so the
guardrails in ADR 0003 can be reasoned about against the actual wire calls.

Structural protection (ADR 0001): this module refuses to import unless
APCA_API_BASE_URL points at the paper host. Paper keys do not authenticate
against the live endpoint either, so the capability to trade real money is
absent, not merely disabled.
"""

from __future__ import annotations

import datetime
import os
import time
from pathlib import Path

import requests

# --- environment ------------------------------------------------------------

PAPER_HOST = "https://paper-api.alpaca.markets"
DATA_HOST = "https://data.alpaca.markets"

_REQUEST_TIMEOUT = 15  # seconds; a hung call must not hang the workflow
_MAX_RETRIES = 3
_BACKOFF_BASE = 0.5  # seconds: sleeps 0.5, 1.0, 2.0 between attempts


def _load_dotenv() -> None:
    """Minimal .env loader — no dependency, does not overwrite real env vars."""
    env_path = Path(__file__).resolve().parents[2] / ".env"
    if not env_path.is_file():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


_load_dotenv()

API_KEY_ID = os.environ.get("APCA_API_KEY_ID", "")
API_SECRET_KEY = os.environ.get("APCA_API_SECRET_KEY", "")
API_BASE_URL = os.environ.get("APCA_API_BASE_URL", "").rstrip("/")


class BrokerError(RuntimeError):
    """Raised when a broker call fails in a way retrying cannot fix."""


# --- the paper-endpoint assertion (ADR 0001) -------------------------------

if API_BASE_URL != PAPER_HOST:
    raise BrokerError(
        "APCA_API_BASE_URL must be exactly "
        f"{PAPER_HOST!r} (got {API_BASE_URL!r}). "
        "This system is paper-trading only (ADR 0001); refusing to import."
    )

if not API_KEY_ID or not API_SECRET_KEY:
    raise BrokerError(
        "APCA_API_KEY_ID and APCA_API_SECRET_KEY must be set "
        "(put them in a local .env or the environment)."
    )

_HEADERS = {
    "APCA-API-KEY-ID": API_KEY_ID,
    "APCA-API-SECRET-KEY": API_SECRET_KEY,
}


# --- HTTP with retry -------------------------------------------------------

def _request(method: str, url: str, *, params: dict | None = None,
             json_body: dict | None = None) -> object:
    """One Alpaca call with retry on transient failure.

    Retries connection errors, timeouts and 5xx up to _MAX_RETRIES times with
    exponential backoff. Never retries 4xx — a 403 means the key is wrong and
    another attempt cannot fix it.
    """
    last_exc: Exception | None = None
    for attempt in range(_MAX_RETRIES + 1):
        if attempt:
            time.sleep(_BACKOFF_BASE * (2 ** (attempt - 1)))
        try:
            resp = requests.request(
                method, url, headers=_HEADERS, params=params, json=json_body,
                timeout=_REQUEST_TIMEOUT,
            )
        except (requests.ConnectionError, requests.Timeout) as exc:
            last_exc = exc
            continue

        if 500 <= resp.status_code < 600:
            last_exc = BrokerError(
                f"{method} {url} -> {resp.status_code}: {resp.text[:200]}"
            )
            continue
        if 400 <= resp.status_code < 500:
            raise BrokerError(
                f"{method} {url} -> {resp.status_code} (not retryable): "
                f"{resp.text[:200]}"
            )
        resp.raise_for_status()
        return resp.json()

    raise BrokerError(
        f"{method} {url} failed after {_MAX_RETRIES} retries: {last_exc}"
    )


def _to_float(value: object, field: str = "value") -> float:
    """Coerce Alpaca's numeric strings to float. Callers never see a str number.

    A missing value RAISES rather than defaulting to zero. These are monetary
    amounts: an absent price is an unknown price, not a price of nothing. A
    silent 0.0 would flow into weights, totals and the performance chart, and
    would render as a catastrophic loss that never happened.
    """
    if value is None:
        raise BrokerError(
            f"Alpaca returned null for {field!r}; refusing to treat missing "
            "money as zero."
        )
    return float(value)


def _to_optional_float(value: object) -> float | None:
    """Coerce optional Alpaca order quantities and notionals without guessing."""
    return None if value is None else float(value)


# --- the five interface functions ----------------------------------------

def get_account() -> dict:
    data = _request("GET", f"{PAPER_HOST}/v2/account")
    return {
        "cash": _to_float(data["cash"], "account.cash"),
        "equity": _to_float(data["equity"], "account.equity"),
        "buying_power": _to_float(data["buying_power"], "account.buying_power"),
        "status": data["status"],
        "currency": data["currency"],
    }


def get_positions() -> list[dict]:
    """Current holdings, each carrying its company name.

    Costs one extra request per position, because Alpaca's positions endpoint
    returns no name. Bounded by the 20-position maximum in ADR 0003, against a
    200 requests/minute limit, so the cost is not worth optimising away.
    """
    data = _request("GET", f"{PAPER_HOST}/v2/positions")
    return [
        {
            "symbol": p["symbol"],
            "name": get_asset(p["symbol"]).get("name"),
            "qty": _to_float(p["qty"], f"{p['symbol']}.qty"),
            "avg_entry_price": _to_float(p["avg_entry_price"], f"{p['symbol']}.avg_entry_price"),
            "current_price": _to_float(p["current_price"], f"{p['symbol']}.current_price"),
            "market_value": _to_float(p["market_value"], f"{p['symbol']}.market_value"),
            "unrealized_pl": _to_float(p["unrealized_pl"], f"{p['symbol']}.unrealized_pl"),
        }
        for p in data
    ]


def get_asset(symbol: str) -> dict:
    """One asset's metadata. The only place a company NAME is available.

    Alpaca's /v2/positions returns a symbol and no name, so the dashboard's
    company column has nothing to show without this lookup.
    """
    data = _request("GET", f"{PAPER_HOST}/v2/assets/{symbol}")
    return {
        "symbol": data["symbol"],
        "name": data.get("name"),
        "tradable": bool(data["tradable"]),
        "fractionable": bool(data["fractionable"]),
        "exchange": data.get("exchange"),
    }


def get_orders(status: str = "open") -> list[dict]:
    """Return open orders, preserving nullable notional and quantity fields."""
    data = _request("GET", f"{PAPER_HOST}/v2/orders", params={"status": status})
    return [
        {
            "order_id": order["id"],
            "symbol": order["symbol"],
            "side": order["side"],
            "notional": _to_optional_float(order.get("notional")),
            "qty": _to_optional_float(order.get("qty")),
            "status": order["status"],
            "submitted_at": _normalise_ts(order["submitted_at"]),
            "filled_qty": _to_float(order["filled_qty"], f"{order['symbol']}.filled_qty"),
        }
        for order in data
    ]


def _normalise_ts(raw: str) -> str:
    """Trim Alpaca's nanosecond timestamps to whole seconds, ISO 8601 UTC.

    Alpaca returns e.g. '2026-08-27T20:02:22.93899136Z'. Nine fractional
    digits are valid ISO but choke several JSON date parsers, and it is
    inconsistent with every other timestamp we store.
    """
    if "." in raw:
        head, _, _ = raw.partition(".")
        return head + "Z"
    return raw


def get_latest_price(symbol: str) -> tuple[float, str]:
    """Latest trade price and the timestamp it is FROM. Uses the data host."""
    data = _request(
        "GET", f"{DATA_HOST}/v2/stocks/{symbol}/trades/latest"
    )
    trade = data["trade"]
    return _to_float(trade["p"], f"{symbol}.latest_trade_price"), _normalise_ts(trade["t"])


def list_assets() -> list[dict]:
    data = _request(
        "GET", f"{PAPER_HOST}/v2/assets",
        params={"status": "active", "asset_class": "us_equity"},
    )
    return [
        {
            "symbol": a["symbol"],
            "tradable": bool(a["tradable"]),
            "fractionable": bool(a["fractionable"]),
            "exchange": a.get("exchange"),
            "name": a.get("name"),
        }
        for a in data
    ]


def submit_notional_order(symbol: str, side: str, notional: float) -> dict:
    """Submit a NOTIONAL market order. The only function here that spends money.

    Notional (a dollar amount) rather than a share count: Alpaca supports
    fractional shares, which removes the rounding error that otherwise causes
    an order to be rejected for being a few cents short (ADR 0003).

    Regular hours, day time-in-force. No extended-hours trading - the free data
    feed is 15 minutes delayed (ADR 0001), so this system has no business
    trading thin sessions.
    """
    if side not in ("buy", "sell"):
        raise BrokerError(f"side must be 'buy' or 'sell', got {side!r}")
    if not isinstance(notional, (int, float)) or notional <= 0:
        raise BrokerError(f"notional must be a positive number, got {notional!r}")

    payload = {
        "symbol": symbol,
        "notional": round(float(notional), 2),
        "side": side,
        "type": "market",
        "time_in_force": "day",
        "extended_hours": False,
    }
    data = _request("POST", f"{PAPER_HOST}/v2/orders", json_body=payload)
    return {
        "order_id": data["id"],
        "symbol": data["symbol"],
        "side": data["side"],
        "notional": _to_optional_float(data.get("notional")),
        "status": data["status"],
        "submitted_at": _normalise_ts(data["submitted_at"]),
    }


def is_trading_day(day: datetime.date) -> bool:
    """True if US equity markets were open on `day`. Uses /v2/calendar."""
    iso = day.isoformat()
    data = _request(
        "GET", f"{PAPER_HOST}/v2/calendar",
        params={"start": iso, "end": iso},
    )
    return any(entry.get("date") == iso for entry in data)
