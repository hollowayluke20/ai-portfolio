"""Candidate selection — which tickers the AI may consider.

**It considers all of them.**

This module used to show ~30 tickers a week: every ETF, every held name, and a
rotating 15-name slice of the S&P 500. That existed on an assumption nobody
checked — that 518 tickers was too many to put in front of a model.

It is not. The entire S&P 500 with company names and sectors is about 4,800
tokens, which is 0.48% of the model's context window.

The rotation was not merely unnecessary, it was harmful. The slice advanced
alphabetically, so in any given week the AI could consider Allegion and
A.O. Smith but not Microsoft, and it took 34 weeks to see the index once. The
portfolio's contents were being decided by which letters came up.

If this ever needs narrowing again, narrow it for a reason that can be stated
in one sentence and defended — not because a long list feels unwieldy.
"""

from __future__ import annotations

from .config import load_rules


def select_candidates(
    universe: list[str], held: list[str], week_index: int = 0
) -> list[str]:
    """Every tradable ticker: the ETF sleeve first, then everything else.

    `held` and `week_index` are accepted and ignored. They remain in the
    signature because callers pass them and because a future filter would want
    them; removing them would be churn for no gain.

    Ordering is deterministic — ETFs first so the asset-class options are
    visible up front, then the rest alphabetically.
    """
    del held, week_index

    etf_sleeve = load_rules()["etf_universe"]
    universe_set = set(universe)

    ordered = [ticker for ticker in etf_sleeve if ticker in universe_set]
    seen = set(ordered)
    ordered.extend(sorted(t for t in universe if t not in seen))
    return ordered
