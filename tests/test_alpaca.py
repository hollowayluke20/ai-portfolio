"""Pure-logic tests for the broker layer. No network."""

import subprocess
import sys
import textwrap

import pytest

from src.portfolio import alpaca


class FakeResp:
    def __init__(self, status_code, json_body=None):
        self.status_code = status_code
        self._json = json_body if json_body is not None else {"ok": True}
        self.text = str(self._json)

    def json(self):
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            raise AssertionError("raise_for_status should not be reached here")


def _patch_transport(monkeypatch, status_sequence):
    calls = {"n": 0}

    def fake_request(method, url, headers=None, params=None, timeout=None):
        i = calls["n"]
        calls["n"] += 1
        return FakeResp(status_sequence[min(i, len(status_sequence) - 1)])

    monkeypatch.setattr(alpaca.requests, "request", fake_request)
    monkeypatch.setattr(alpaca.time, "sleep", lambda *_: None)
    return calls


def test_to_float_coerces_numeric_string():
    result = alpaca._to_float("431.02")
    assert result == 431.02
    assert isinstance(result, float)


def test_retry_recovers_after_500(monkeypatch):
    calls = _patch_transport(monkeypatch, [500, 500, 200])
    out = alpaca._request("GET", "https://paper-api.alpaca.markets/v2/account")
    assert out == {"ok": True}
    assert calls["n"] == 3  # two failures then success


def test_retry_exhausted_raises(monkeypatch):
    _patch_transport(monkeypatch, [500])
    with pytest.raises(alpaca.BrokerError):
        alpaca._request("GET", "https://paper-api.alpaca.markets/v2/account")


def test_no_retry_on_403(monkeypatch):
    calls = _patch_transport(monkeypatch, [403])
    with pytest.raises(alpaca.BrokerError):
        alpaca._request("GET", "https://paper-api.alpaca.markets/v2/account")
    assert calls["n"] == 1  # a wrong key is not fixed by retrying


def test_get_orders_preserves_nullable_notional_and_qty(monkeypatch):
    payload = [{
        "id": "order-1", "symbol": "NVDA", "side": "buy", "notional": None,
        "qty": "2.5", "status": "accepted",
        "submitted_at": "2026-08-28T12:43:25.123Z", "filled_qty": "0",
    }]
    monkeypatch.setattr(alpaca, "_request", lambda *args, **kwargs: payload)

    assert alpaca.get_orders() == [{
        "order_id": "order-1", "symbol": "NVDA", "side": "buy", "notional": None,
        "qty": 2.5, "status": "accepted", "submitted_at": "2026-08-28T12:43:25Z",
        "filled_qty": 0.0,
    }]


def test_import_rejects_live_endpoint():
    """The paper-endpoint assertion (ADR 0001) must raise on a live URL.

    Run in a subprocess so a failed import cannot corrupt this test session.
    """
    script = textwrap.dedent(
        """
        import os
        os.environ["APCA_API_BASE_URL"] = "https://api.alpaca.markets"
        os.environ["APCA_API_KEY_ID"] = "x"
        os.environ["APCA_API_SECRET_KEY"] = "y"
        try:
            import src.portfolio.alpaca  # noqa
        except Exception as exc:
            assert "paper" in str(exc).lower()
            print("REJECTED")
        else:
            raise SystemExit("import should have failed on a live URL")
        """
    )
    proc = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True
    )
    assert proc.returncode == 0, proc.stderr
    assert "REJECTED" in proc.stdout
