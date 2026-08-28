import pytest

from src.portfolio.decisions import read_active_theses, write_cycle


def test_cycle_is_immutable_and_opening_thesis_is_found(tmp_path):
    state, ai = {"totals": {"total_value": 100}}, {"commentary": "", "considered": []}
    path = tmp_path / "2026-08-28.json"
    write_cycle(path, "cycle", "2026-08-28T12:00:00Z", state, ai, [{"ticker": "MSFT", "action": "BUY", "status": "executed", "thesis": "original"}])
    assert read_active_theses(tmp_path, ["MSFT"]) == {"MSFT": "original"}
    with pytest.raises(FileExistsError):
        write_cycle(path, "again", "2026-08-28T12:00:00Z", state, ai, [])
