"""A daily cap on live model calls, shared by every visitor.

The per-minute limits in security.py are per visitor; this one bounds what the
whole demo can spend in a day. Each live request first reserves its run's
maximum number of model calls in one atomic update, so requests running at the
same time can never exceed the cap together; when the run ends, the calls it
did not send are released. A call counts as soon as it is sent and is given back
only when Bedrock itself failed, so a call cancelled in flight (a client that
disconnects from a streamed run, or the run's deadline) stays counted, as AWS
still bills it. When a run no longer fits, the request
runs on the replay model and says so (`fallback: "daily_budget"`), instead of
failing or spending more.

Calls are counted, not tokens: the cap is a simple, predictable bound (an
investigation is at most 9 calls, its revision included), not an exact bill. SDK retries inside one
call are not counted separately.

A guest's run on the public deployment must also fit a smaller guest share of the
day (LOGIOPS_GUEST_DAILY_MODEL_CALLS, 0 by default), held in a second row, so a
judge who never signs in still meets the live agent while the share lasts and
signed-in people keep the rest. Within that share each visitor has their own
daily allowance (LOGIOPS_GUEST_VIEWER_DAILY_MODEL_CALLS, one investigation's worth
by default), held in a third row keyed by a hash of the visitor's address, so one
visitor cannot use up the share for everyone else.
"""

from __future__ import annotations

import hashlib
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from .bedrock import BedrockError
from .scenario import LIMA
from .storage import connect

DEFAULT_DAILY_CALLS = 150
DEFAULT_GUEST_CALLS = 0
DEFAULT_GUEST_VIEWER_CALLS = 9
FALLBACK = "daily_budget"
GUEST_FALLBACK = "guest_budget"
HOLD = "UPDATE model_budget SET calls = calls + ? WHERE day = ? AND calls + ? <= ?"
SCHEMA = "CREATE TABLE IF NOT EXISTS model_budget (day TEXT PRIMARY KEY, calls INTEGER NOT NULL)"


class DailyModelBudget:
    def __init__(
        self, db_path: str | Path, limit: int, clock: Callable[[], datetime] | None = None, guest_limit: int = DEFAULT_GUEST_CALLS,
        guest_viewer_limit: int = DEFAULT_GUEST_VIEWER_CALLS,
    ) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.limit = limit
        self.guest_limit = guest_limit
        self.guest_viewer_limit = guest_viewer_limit
        self._clock = clock or (lambda: datetime.now(LIMA))
        with connect(self.db_path) as connection:
            connection.execute(SCHEMA)

    @classmethod
    def from_env(cls, db_path: str | Path) -> "DailyModelBudget":
        try:
            return cls(db_path, int(os.environ.get("LOGIOPS_DAILY_MODEL_CALLS", DEFAULT_DAILY_CALLS)),
                       guest_limit=int(os.environ.get("LOGIOPS_GUEST_DAILY_MODEL_CALLS", DEFAULT_GUEST_CALLS)),
                       guest_viewer_limit=int(os.environ.get("LOGIOPS_GUEST_VIEWER_DAILY_MODEL_CALLS", DEFAULT_GUEST_VIEWER_CALLS)))
        except ValueError as exc:
            raise RuntimeError(
                "LOGIOPS_DAILY_MODEL_CALLS, LOGIOPS_GUEST_DAILY_MODEL_CALLS and LOGIOPS_GUEST_VIEWER_DAILY_MODEL_CALLS must be integers"
            ) from exc

    def today(self) -> str:
        return self._clock().astimezone(LIMA).date().isoformat()

    def _pools(self, day: str, guest: bool, viewer: str | None = None) -> list[tuple[str, int]]:
        pools = [(day, self.limit)]
        if guest:
            pools.append((f"{day}#guest", self.guest_limit))
            if viewer:
                pools.append((f"{day}#guest#{hashlib.sha256(viewer.encode()).hexdigest()[:16]}", self.guest_viewer_limit))
        return pools

    def used(self, day: str | None = None, guest: bool = False, viewer: str | None = None) -> int:
        """Calls used or reserved on a day (today by default), from the guest share when `guest`, and from
        one visitor's allowance within it when `viewer` is given too."""
        key = self._pools(day or self.today(), guest, viewer)[-1][0]
        with connect(self.db_path) as connection:
            row = connection.execute("SELECT calls FROM model_budget WHERE day = ?", (key,)).fetchone()
        return row[0] if row else 0

    def reserve(self, calls: int, guest: bool = False, viewer: str | None = None) -> str | None:
        """Hold `calls` of today's budget, and of the guest share and the visitor's allowance too when
        `guest`, in one transaction. Returns the day they were held on (to release unused calls later,
        even after midnight), or None when they no longer fit in any of them; nothing is held then."""
        day = self.today()
        with connect(self.db_path) as connection:
            for key, limit in self._pools(day, guest, viewer):
                connection.execute("INSERT INTO model_budget (day, calls) VALUES (?, 0) ON CONFLICT(day) DO NOTHING", (key,))
                if not connection.execute(HOLD, (calls, key, calls, limit)).rowcount:
                    connection.rollback()
                    return None
        return day

    def release(self, day: str, calls: int, guest: bool = False, viewer: str | None = None) -> None:
        """Give back calls a run reserved but did not make, to every pool they were held in."""
        if calls > 0:
            with connect(self.db_path) as connection:
                connection.executemany("UPDATE model_budget SET calls = MAX(0, calls - ?) WHERE day = ?",
                                       [(calls, key) for key, _ in self._pools(day, guest, viewer)])


class BudgetedConverse:
    """A live client bound to one reservation: it counts each call when it is sent, gives
    it back when Bedrock failed (an outage never looks like a used budget), keeps it when
    the call was cancelled in flight, refuses to go past the reservation, and releases the
    rest when settled."""

    def __init__(
        self, client: Any, budget: DailyModelBudget, day: str, reserved: int, guest: bool = False, viewer: str | None = None,
    ) -> None:
        self.client = client
        self.budget = budget
        self.day = day
        self.reserved = reserved
        self.guest = guest
        self.viewer = viewer
        self.calls = 0

    async def converse(
        self, messages: list[dict[str, Any]], system: str, tools: list[dict[str, Any]], skill: str | None = None
    ) -> dict[str, Any]:
        if self.calls >= self.reserved:
            raise BedrockError("The run used all the model calls reserved for it")
        self.calls += 1
        try:
            return await self.client.converse(messages, system, tools, skill=skill)
        except BedrockError:
            self.calls -= 1
            raise

    def settle(self) -> None:
        self.budget.release(self.day, self.reserved - self.calls, guest=self.guest, viewer=self.viewer)
