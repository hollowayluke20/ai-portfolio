from src.portfolio import news


def _article(created_at, symbols, headline="headline", **extra):
    return {"created_at": created_at, "symbols": symbols, "headline": headline, "source": "wire", "url": "https://example.test", **extra}


def test_fetch_news_groups_sorts_and_enforces_end_boundary(monkeypatch):
    def request(method, url, params):
        return {"news": [
            _article("2026-01-04T12:00:00Z", ["AAPL", "NVDA"], "shared", summary="present"),
            _article("2026-01-03T12:00:00Z", ["AAPL"], "older"),
            _article("2026-01-05T00:00:00Z", ["AAPL"], "future"),
        ]}

    monkeypatch.setattr(news.alpaca, "_request", request)
    result = news.fetch_news(["AAPL", "NVDA", "NONE"], "2026-01-01", "2026-01-04")

    assert [article.headline for article in result["AAPL"]] == ["shared", "older"]
    assert [article.headline for article in result["NVDA"]] == ["shared"]
    assert result["AAPL"][1].summary == ""
    assert "NONE" not in result


def test_fetch_news_trims_after_grouping_and_follows_pages(monkeypatch):
    calls = []

    def request(method, url, params):
        calls.append(dict(params))
        if "page_token" not in params:
            return {"news": [
                _article("2026-01-04T12:00:00Z", ["AAPL"], "aapl 1"),
                _article("2026-01-04T11:00:00Z", ["AAPL", "NVDA"], "shared"),
                _article("2026-01-04T10:00:00Z", ["AAPL"], "aapl 2"),
            ], "next_page_token": "next"}
        return {"news": [_article("2026-01-04T09:00:00Z", ["NVDA"], "nvda 2")]}

    monkeypatch.setattr(news.alpaca, "_request", request)
    result = news.fetch_news(["AAPL", "NVDA"], "2026-01-01", "2026-01-04", per_ticker=2)

    assert [article.headline for article in result["AAPL"]] == ["aapl 1", "shared"]
    assert [article.headline for article in result["NVDA"]] == ["shared", "nvda 2"]
    assert [call.get("page_token") for call in calls] == [None, "next"]
