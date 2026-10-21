"""The SQLite connection settings shared by the app's own tables (preferences, model budget), and which of
their rows still belong to an incident's current seed."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator


@contextmanager
def connect(db_path: Path) -> Iterator[sqlite3.Connection]:
    """One connection that commits on success, rolls back on an error, and always closes."""
    connection = sqlite3.connect(db_path, timeout=5)
    try:
        connection.execute("PRAGMA busy_timeout=5000")
        with connection:
            yield connection
    finally:
        connection.close()


def of_current_seed(snapshot: dict[str, Any], plan_id: str | None) -> bool:
    """Whether a row about this plan belongs to the incident as it is now. A reset or a date refresh seeds a new
    scenario run, and every plan id starts with the incident and its run."""
    state = snapshot["state"]
    return str(plan_id or "").startswith(f"{state['incident_id']}:{state['scenario_run_id']}:")
