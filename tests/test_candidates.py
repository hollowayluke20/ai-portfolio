"""Pure-logic tests for candidate selection. No network."""

from src.portfolio import candidates
from src.portfolio.config import load_rules

ETFS = load_rules()["etf_universe"]
SP = [f"S{i:03d}" for i in range(120)]  # fake S&P-style names
UNIVERSE = ETFS + SP


def test_deterministic():
    a = candidates.select_candidates(UNIVERSE, [], 3)
    b = candidates.select_candidates(UNIVERSE, [], 3)
    assert a == b


def test_includes_every_etf():
    out = candidates.select_candidates(UNIVERSE, [], 0)
    for etf in ETFS:
        assert etf in out


def test_returns_the_whole_universe():
    """No rotation. The whole S&P 500 with names and sectors is ~4,800 tokens,
    which is 0.48% of the context window - there was never a reason to narrow
    it, and narrowing it alphabetically meant the portfolio's contents were
    decided by which letters came up that week."""
    out = candidates.select_candidates(UNIVERSE, [], 0)
    assert len(out) == len(UNIVERSE)
    assert set(out) == set(UNIVERSE)


def test_week_index_no_longer_changes_anything():
    """Explicitly asserted, because it used to. A silent return to rotation
    would otherwise pass every other test here."""
    assert (candidates.select_candidates(UNIVERSE, [], 0)
            == candidates.select_candidates(UNIVERSE, [], 37))


def test_etfs_come_first():
    out = candidates.select_candidates(UNIVERSE, [], 0)
    assert out[:len(ETFS)] == [e for e in ETFS if e in UNIVERSE]


def test_whole_universe_is_covered_in_a_single_week():
    """It used to take 34 weeks to see the index once."""
    out = set(candidates.select_candidates(UNIVERSE, [], 0))
    for name in SP:
        assert name in out


def test_held_names_are_included():
    out = candidates.select_candidates(UNIVERSE, ["S099", "S000"], 0)
    assert "S099" in out and "S000" in out


def test_success_criteria_line():
    out = candidates.select_candidates(["SPY", "QQQ", "MSFT", "AAPL"], [], 0)
    assert len(out) == 4
