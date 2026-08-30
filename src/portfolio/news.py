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
    tickers: list[str], start: str, end: str, per_ticker: int = 5
) -> dict[str, list[Article]]:
    """Return up to ``per_ticker`` articles per requested ticker, newest first."""
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

    return {
        ticker: sorted(articles, key=lambda article: article.created_at, reverse=True)[:per_ticker]
        for ticker, articles in grouped.items()
    }
