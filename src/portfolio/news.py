"""Historical news evidence fetched from Alpaca's data API."""

from __future__ import annotations

from dataclasses import dataclass

from . import alpaca


DATA_HOST = "https://data.alpaca.markets"


@dataclass(frozen=True)
class Article:
    headline: str
    summary: str
    created_at: str
    source: str
    url: str


def fetch_news(
    tickers: list[str], start: str, end: str, per_ticker: int = 8,
    per_day: int = 2
) -> dict[str, list[Article]]:
    """Up to ``per_ticker`` articles per ticker, spread across the window.

    The cap is applied PER DAY first, then overall. Taking the newest few
    outright looked like it covered the week and did not: a busy Thursday and
    Friday silently deleted Monday to Wednesday, so a story that broke early
    and mattered all week vanished the moment anything louder happened later.

    A thesis breaks over days, not in the last twelve hours before a cycle.
    Capping by day means a quiet Tuesday still gets its say."""
    if per_ticker <= 0:
        return {}

    requested = set(tickers)
    grouped: dict[str, list[Article]] = {}
    for offset in range(0, len(tickers), 50):
        params: dict[str, object] = {
            "symbols": ",".join(tickers[offset:offset + 50]),
            "start": start,
            "end": end,
            "limit": 50,
            "sort": "desc",
        }
        while True:
            data = alpaca._request("GET", f"{DATA_HOST}/v1beta1/news", params=params)
            for row in data.get("news", []):
                created_at = row["created_at"]
                # The remote end parameter is not sufficient for honest replay.
                if created_at[:10] > end:
                    continue
                article = Article(
                    headline=row.get("headline", ""),
                    summary=row.get("summary") or "",
                    created_at=created_at,
                    source=row.get("source", ""),
                    url=row.get("url", ""),
                )
                for ticker in requested.intersection(row.get("symbols", [])):
                    grouped.setdefault(ticker, []).append(article)
            if all(len(grouped.get(ticker, [])) >= per_ticker for ticker in requested):
                break
            token = data.get("next_page_token")
            if not token:
                break
            params = {**params, "page_token": token}

    def spread(articles):
        by_day: dict[str, list[Article]] = {}
        for a in sorted(articles, key=lambda x: x.created_at, reverse=True):
            day = a.created_at[:10]
            if len(by_day.setdefault(day, [])) < per_day:
                by_day[day].append(a)
        picked = [a for day in sorted(by_day, reverse=True) for a in by_day[day]]
        return picked[:per_ticker]

    return {ticker: spread(articles) for ticker, articles in grouped.items()}
