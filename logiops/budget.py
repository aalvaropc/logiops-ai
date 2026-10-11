"""A daily cap on live model calls, shared by every visitor.

The per-minute limits in security.py are per visitor; this one bounds what the
whole demo can spend in a day. Each live request first reserves its run's
maximum number of model calls in one atomic update, so requests running at the
same time can never exceed the cap together; when the run ends, the calls it
did not make successfully are released. When a run no longer fits, the request
runs on the replay model and says so (`fallback: "daily_budget"`), instead of
failing or spending more.

Calls are counted, not tokens: the cap is a simple, predictable bound (an
investigation is at most 9 calls, its revision included), not an exact bill. SDK retries inside one
call are not counted separately.
"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from .bedrock import BedrockError
from .scenario import LIMA
from .storage import connect

DEFAULT_DAILY_CALLS = 150
FALLBACK = "daily_budget"
SCHEMA = "CREATE TABLE IF NOT EXISTS model_budget (day TEXT PRIMARY KEY, calls INTEGER NOT NULL)"


class DailyModelBudget:
    def __init__(self, db_path: str | Path, limit: int, clock: Callable[[], datetime] | None = None) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.limit = limit
        self._clock = clock or (lambda: datetime.now(LIMA))
        with connect(self.db_path) as connection:
            connection.execute(SCHEMA)

    @classmethod
    def from_env(cls, db_path: str | Path) -> "DailyModelBudget":
        try:
            return cls(db_path, int(os.environ.get("LOGIOPS_DAILY_MODEL_CALLS", DEFAULT_DAILY_CALLS)))
        except ValueError as exc:
            raise RuntimeError("LOGIOPS_DAILY_MODEL_CALLS must be an integer") from exc

    def today(self) -> str:
        return self._clock().astimezone(LIMA).date().isoformat()

    def used(self, day: str | None = None) -> int:
        """Calls used or reserved on a day (today by default)."""
        with connect(self.db_path) as connection:
            row = connection.execute("SELECT calls FROM model_budget WHERE day = ?", (day or self.today(),)).fetchone()
        return row[0] if row else 0

    def reserve(self, calls: int) -> str | None:
        """Hold `calls` of today's budget in one atomic update. Returns the day they were held on
        (to release unused calls later, even after midnight), or None when they no longer fit."""
        day = self.today()
        with connect(self.db_path) as connection:
            connection.execute("INSERT INTO model_budget (day, calls) VALUES (?, 0) ON CONFLICT(day) DO NOTHING", (day,))
            held = connection.execute(
                "UPDATE model_budget SET calls = calls + ? WHERE day = ? AND calls + ? <= ?",
                (calls, day, calls, self.limit),
            ).rowcount
        return day if held else None

    def release(self, day: str, calls: int) -> None:
        """Give back calls a run reserved but did not make."""
        if calls > 0:
            with connect(self.db_path) as connection:
                connection.execute("UPDATE model_budget SET calls = MAX(0, calls - ?) WHERE day = ?", (calls, day))


class BudgetedConverse:
    """A live client bound to one reservation: it counts the calls that returned a response
    (a failed call is not billed as a model answer, so an outage never looks like a used
    budget), refuses to go past the reservation, and releases the rest when settled."""

    def __init__(self, client: Any, budget: DailyModelBudget, day: str, reserved: int) -> None:
        self.client = client
        self.budget = budget
        self.day = day
        self.reserved = reserved
        self.calls = 0

    async def converse(
        self, messages: list[dict[str, Any]], system: str, tools: list[dict[str, Any]], skill: str | None = None
    ) -> dict[str, Any]:
        if self.calls >= self.reserved:
            raise BedrockError("The run used all the model calls reserved for it")
        response = await self.client.converse(messages, system, tools, skill=skill)
        self.calls += 1
        return response

    def settle(self) -> None:
        self.budget.release(self.day, self.reserved - self.calls)
