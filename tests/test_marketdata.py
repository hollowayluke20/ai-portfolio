from src.portfolio import marketdata
from src.portfolio.marketdata import compute_features, compute_breadth
def test_features_filter_future_and_short_history():
    bars={"A":[{"t":f"2026-01-{i:02d}T04:00:00Z","c":i} for i in range(1,23)]+[{"t":"2026-02-01T04:00:00Z","c":999}]}
    f=compute_features(bars,"2026-01-22")["A"]
    assert f.price==22 and f.ret_1m==21 and f.ret_12m is None
def test_breadth():
    class F:
        def __init__(self,x): self.above_200d_ma=x
    assert compute_breadth({"a":F(True),"b":F(False),"c":F(None)})==.5


def test_fetch_bars_chunks_518_symbols(monkeypatch):
    calls = []

    def request(method, url, params):
        calls.append(params)
        return {"bars": {}}

    monkeypatch.setattr(marketdata.alpaca, "_request", request)
    marketdata.fetch_bars([f"T{i}" for i in range(518)], "2025-01-01", "2026-01-01")

    assert len(calls) == 3
    assert [len(call["symbols"].split(",")) for call in calls] == [200, 200, 118]


def test_fetch_bars_follows_page_token_and_merges(monkeypatch):
    calls = []

    def request(method, url, params):
        calls.append(dict(params))
        if "page_token" not in params:
            return {"bars": {"AAPL": [{"t": "2026-01-01", "c": 1}]}, "next_page_token": "next"}
        return {"bars": {"AAPL": [{"t": "2026-01-02", "c": 2}], "NVDA": [{"t": "2026-01-02", "c": 3}]}}

    monkeypatch.setattr(marketdata.alpaca, "_request", request)
    result = marketdata.fetch_bars(["AAPL", "NVDA"], "2025-01-01", "2026-01-01")

    assert [call.get("page_token") for call in calls] == [None, "next"]
    assert result["AAPL"] == [{"t": "2026-01-01", "c": 1}, {"t": "2026-01-02", "c": 2}]
    assert result["NVDA"] == [{"t": "2026-01-02", "c": 3}]


def test_fetch_bars_always_requests_adjusted_prices(monkeypatch):
    calls = []

    def request(method, url, params):
        calls.append(params)
        return {"bars": {}}

    monkeypatch.setattr(marketdata.alpaca, "_request", request)
    marketdata.fetch_bars([f"T{i}" for i in range(201)], "2025-01-01", "2026-01-01")

    assert calls
    assert all(call["adjustment"] == "all" for call in calls)
