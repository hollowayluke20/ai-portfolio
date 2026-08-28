import json

import pytest

from src.portfolio.storage import append_history_row, read_json, write_json_atomic


def test_append_history_row_replaces_same_date_and_sorts(tmp_path):
    path = tmp_path / "history.json"
    append_history_row(path, {"date": "2026-09-02", "portfolio_value": 10})
    append_history_row(path, {"date": "2026-09-01", "portfolio_value": 5})
    append_history_row(path, {"date": "2026-09-02", "portfolio_value": 12})

    assert read_json(path)["rows"] == [
        {"date": "2026-09-01", "portfolio_value": 5},
        {"date": "2026-09-02", "portfolio_value": 12},
    ]


def test_atomic_write_preserves_original_when_serialisation_fails(tmp_path):
    path = tmp_path / "state.json"
    path.write_text(json.dumps({"last_known": "good"}), encoding="utf-8")

    with pytest.raises(TypeError):
        write_json_atomic(path, {"not_json": {1, 2, 3}})

    assert read_json(path) == {"last_known": "good"}
