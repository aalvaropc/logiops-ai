"""The SQLite connection settings shared by the app's own tables (preferences, model budget)."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


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
