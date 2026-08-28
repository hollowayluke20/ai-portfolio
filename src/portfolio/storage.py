"""Safe JSON persistence for portfolio state and history."""

import json
import os
import tempfile
from pathlib import Path


def read_json(path, default=None):
    """Read JSON from *path*, returning *default* when it does not exist."""
    try:
        with Path(path).open("r", encoding="utf-8") as file:
            return json.load(file)
    except FileNotFoundError:
        return default


def write_json_atomic(path, data):
    """Serialize *data* and atomically replace *path* only after success."""
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_name = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=destination.parent,
            prefix=f".{destination.name}.", suffix=".tmp", delete=False,
        ) as temporary:
            temporary_name = temporary.name
            json.dump(data, temporary, indent=2)
            temporary.write("\n")
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_name, destination)
        temporary_name = None
    finally:
        if temporary_name:
            try:
                os.unlink(temporary_name)
            except FileNotFoundError:
                pass


def append_history_row(path, row):
    """Insert or replace a history row, keeping the document date-sorted."""
    history = read_json(path, {"schema_version": 1, "rows": []})
    rows_by_date = {existing["date"]: existing for existing in history["rows"]}
    rows_by_date[row["date"]] = row
    history["rows"] = [rows_by_date[date] for date in sorted(rows_by_date)]
    write_json_atomic(path, history)
