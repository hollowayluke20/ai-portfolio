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


def test_a_busy_friday_does_not_delete_monday(monkeypatch):
    """The window is a week; the report has to cover it.

    Trimming to the newest few outright looked like week-long coverage and was
    not - a loud Thursday and Friday silently removed Monday to Wednesday, so
    a story that broke early and mattered all week disappeared the moment
    anything noisier happened later. A thesis breaks over days.
    """
    from src.portfolio import news as news_mod
    loud_end = [{"headline": f"friday {i}", "summary": "", "source": "w",
                 "url": "", "created_at": f"2026-08-28T{9 + i:02d}:00:00Z",
                 "symbols": ["AAA"]} for i in range(8)]
    early = [{"headline": "monday, and it mattered", "summary": "", "source": "w",
              "url": "", "created_at": "2026-08-24T09:00:00Z", "symbols": ["AAA"]}]
    monkeypatch.setattr(news_mod.alpaca, "_request",
                        lambda *a, **k: {"news": loud_end + early})

    got = news_mod.fetch_news(["AAA"], "2026-08-24", "2026-08-28")["AAA"]
    days = {a.created_at[:10] for a in got}
    assert "2026-08-24" in days, "the early story was crowded out"
    assert sum(1 for a in got if a.created_at.startswith("2026-08-28")) <= 2
