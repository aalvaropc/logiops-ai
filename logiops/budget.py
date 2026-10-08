"""A daily cap on live model calls, shared by every visitor.

The per-minute limits in security.py are per visitor; this one bounds what the
whole demo can spend in a day. When it is used up, agent requests run in replay
mode and say so, instead of failing or spending more.
"""

from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterator

LIMA = timezone(timedelta(hours=-5))
DEFAULT_DAILY_CALLS = 150
EXHAUSTED_MODE = "replay (daily live budget used)"


class DailyModelBudget:
    def __init__(self, db_path: str | Path, limit: int, clock: Callable[[], datetime] | None = None) -> None:
        self.db_path = Path(db_path)
        self.limit = limit
        self._clock = clock or (lambda: datetime.now(LIMA))
        with self._connection() as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS model_budget (day TEXT PRIMARY KEY, calls INTEGER NOT NULL)")

    @classmethod
    def from_env(cls, db_path: str | Path) -> "DailyModelBudget":
        return cls(db_path, int(os.environ.get("LOGIOPS_DAILY_MODEL_CALLS", DEFAULT_DAILY_CALLS)))

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.db_path, timeout=5)
        connection.execute("PRAGMA busy_timeout=5000")
        try:
            with connection:  # commits, or rolls back on an error
                yield connection
        finally:
            connection.close()

    def _today(self) -> str:
        return self._clock().astimezone(LIMA).date().isoformat()

    def used(self) -> int:
        with self._connection() as connection:
            row = connection.execute("SELECT calls FROM model_budget WHERE day = ?", (self._today(),)).fetchone()
        return row[0] if row else 0

    def available(self) -> bool:
        return self.used() < self.limit

    def spend(self, calls: int = 1) -> int:
        """Count calls for today and return the new total."""
        with self._connection() as connection:
            connection.execute(
                "INSERT INTO model_budget (day, calls) VALUES (?, ?) "
                "ON CONFLICT(day) DO UPDATE SET calls = calls + excluded.calls",
                (self._today(), calls),
            )
            row = connection.execute("SELECT calls FROM model_budget WHERE day = ?", (self._today(),)).fetchone()
        return row[0]


class BudgetedConverse:
    """A live client that counts each call. A run that starts within the budget finishes,
    so the overshoot is bounded by one run's turn limit."""

    def __init__(self, client: Any, budget: DailyModelBudget) -> None:
        self.client = client
        self.budget = budget

    async def converse(self, messages: list[dict[str, Any]], system: str, tools: list[dict[str, Any]]) -> dict[str, Any]:
        self.budget.spend()
        return await self.client.converse(messages, system, tools)
