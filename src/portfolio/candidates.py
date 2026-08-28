"""Candidate selection — which tickers the AI is allowed to look at this week.

Deliberately dumb. One sentence: **every ETF in the sleeve, every currently-held
name, plus a rotating 15-name slice of the S&P 500 that advances each week so the
whole universe is seen over time.**

The moment this gets clever it becomes a second, undocumented strategy that
nobody reviewed. If selection logic ever needs judgment, that belongs in the AI
prompt, not here.
"""

from __future__ import annotations

from .config import load_rules

SP500_SLICE = 15  # S&P names shown per week


def select_candidates(
    universe: list[str], held: list[str], week_index: int
) -> list[str]:
    """~30 tickers: the ETF sleeve + held names + a rotating S&P slice.

    Deterministic: the same (universe, held, week_index) always returns the
    same list, in the same order.
    """
    etf_sleeve = load_rules()["etf_universe"]
    universe_set = set(universe)
    etf_set = set(etf_sleeve)

    result: list[str] = []
    seen: set[str] = set()

    def add(ticker: str) -> None:
        if ticker not in seen:
            seen.add(ticker)
            result.append(ticker)

    # 1. every ETF in the sleeve that is actually tradable
    for ticker in etf_sleeve:
        if ticker in universe_set:
            add(ticker)

    # 2. every currently-held name still in the universe, so the AI can
    #    always reassess what it owns
    for ticker in sorted(held):
        if ticker in universe_set:
            add(ticker)

    # 3. a rotating slice of the S&P names, advancing by week_index
    sp_names = sorted(t for t in universe if t not in etf_set)
    if sp_names:
        span = min(SP500_SLICE, len(sp_names))
        start = (week_index * span) % len(sp_names)
        for offset in range(span):
            add(sp_names[(start + offset) % len(sp_names)])

    return result
