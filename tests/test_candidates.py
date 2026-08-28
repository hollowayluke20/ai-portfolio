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


def test_roughly_thirty_with_no_holdings():
    out = candidates.select_candidates(UNIVERSE, [], 0)
    assert len(out) == len(ETFS) + candidates.SP500_SLICE


def test_week_index_changes_the_sp_slice():
    week0 = set(candidates.select_candidates(UNIVERSE, [], 0)) - set(ETFS)
    week1 = set(candidates.select_candidates(UNIVERSE, [], 1)) - set(ETFS)
    assert week0 != week1


def test_whole_universe_is_covered_over_time():
    seen: set[str] = set()
    for week in range(len(SP)):  # more than enough cycles
        seen |= set(candidates.select_candidates(UNIVERSE, [], week))
    for name in SP:
        assert name in seen


def test_held_names_are_included():
    out = candidates.select_candidates(UNIVERSE, ["S099", "S000"], 0)
    assert "S099" in out and "S000" in out


def test_success_criteria_line():
    out = candidates.select_candidates(["SPY", "QQQ", "MSFT", "AAPL"], [], 0)
    assert len(out) == 4
