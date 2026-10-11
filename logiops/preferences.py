"""Operator preferences that persist across sessions and steer which plan to pick.

A preference never approves anything. Fixed rules apply it to the plans the service
calculated, the result is shown next to the agent's pick, and the agent is told about
it as a fact. A person still approves every plan.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, ContextManager

from .scenario import best_plan, rank_key
from .storage import connect

RULES = {
    "balanced": "Balanced: critical orders first, then the shortest delay, then cost",
    "cheapest_unless_critical_late": "Cheapest plan that keeps every critical order on time",
}
NOTE_LIMIT = 200
COST_LIMIT = 100_000
SCHEMA = """CREATE TABLE IF NOT EXISTS operator_preferences (
    id INTEGER PRIMARY KEY CHECK (id = 1), preferences_json TEXT NOT NULL, updated_at TEXT NOT NULL)"""


def normalized(rule: str, max_cost_usd: int | None, note: str) -> dict[str, Any]:
    if rule not in RULES:
        raise ValueError(f"Unknown preference rule: {rule}")
    if max_cost_usd is not None and (
        isinstance(max_cost_usd, bool) or not isinstance(max_cost_usd, int) or not 0 <= max_cost_usd <= COST_LIMIT
    ):
        raise ValueError(f"The spend cap must be a whole number of dollars from 0 to {COST_LIMIT}")
    note = " ".join(str(note).split())
    if len(note) > NOTE_LIMIT:
        raise ValueError(f"The note is limited to {NOTE_LIMIT} characters")
    return {"rule": rule, "max_cost_usd": max_cost_usd, "note": note}


class PreferenceStore:
    """The demo operator's single profile, kept in the same SQLite file as the incidents."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as connection:
            connection.execute(SCHEMA)

    def _connection(self) -> ContextManager[sqlite3.Connection]:
        return connect(self.db_path)

    def get(self) -> dict[str, Any] | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT preferences_json, updated_at FROM operator_preferences WHERE id = 1"
            ).fetchone()
        return None if row is None else {**json.loads(row[0]), "updated_at": row[1]}

    def put(self, rule: str, max_cost_usd: int | None, note: str = "") -> dict[str, Any]:
        value = normalized(rule, max_cost_usd, note)
        now = datetime.now(timezone.utc).isoformat()
        with self._connection() as connection:
            connection.execute(
                "INSERT INTO operator_preferences (id, preferences_json, updated_at) VALUES (1, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET preferences_json = excluded.preferences_json, "
                "updated_at = excluded.updated_at",
                (json.dumps(value, sort_keys=True), now),
            )
        return {**value, "updated_at": now}

    def clear(self) -> None:
        with self._connection() as connection:
            connection.execute("DELETE FROM operator_preferences")


def _late_critical(plan: dict[str, Any]) -> list[dict[str, Any]]:
    return [order for order in plan.get("orders", []) if order["priority"] == "critical" and order["delay_hours"] > 0]


def _cheapest(plans: list[dict[str, Any]]) -> dict[str, Any]:
    return min(plans, key=lambda plan: (plan["incremental_cost_usd"], rank_key(plan)))


def _trade_off(chosen: dict[str, Any], default: dict[str, Any]) -> str:
    parts = []
    saved = default["incremental_cost_usd"] - chosen["incremental_cost_usd"]
    if saved:
        parts.append(f"saves ${saved}" if saved > 0 else f"costs ${-saved} more")
    hours = chosen["projected_customer_delay_hours"] - default["projected_customer_delay_hours"]
    if hours:
        parts.append(f"the last order arrives {abs(hours)} h {'later' if hours > 0 else 'sooner'}")
    units = chosen.get("late_units", 0) - default.get("late_units", 0)
    if units:
        parts.append(f"{abs(units)} {'more' if units > 0 else 'fewer'} units arrive late")
    return ", ".join(parts)


def preference_for(plans: list[dict[str, Any]], preferences: dict[str, Any] | None) -> dict[str, Any] | None:
    """The plan the saved preferences point to among these plans, and why; None without both."""
    if not plans or not preferences:
        return None
    default = best_plan(plans)
    rule, cap = preferences["rule"], preferences.get("max_cost_usd")
    within = [plan for plan in plans if cap is None or plan["incremental_cost_usd"] <= cap]
    warnings = []
    if not within:
        chosen = _cheapest(plans)
        warnings.append(f"No plan fits the ${cap} spend cap; this is the cheapest one.")
    elif rule == "cheapest_unless_critical_late":
        safe = [plan for plan in within if not _late_critical(plan)]
        chosen = _cheapest(safe or within)
        if not safe:
            warnings.append("No plan within the preferences keeps every critical order on time.")
    else:
        chosen = min(within, key=rank_key)
    late = _late_critical(chosen)
    if late and not _late_critical(default):
        names = "; ".join(f"{order['order_id']} ({order['customer']}, critical) is {order['delay_hours']} h late"
                          for order in late)
        warnings.append(f"{names}. The default pick, “{default['label']}”, keeps critical orders on time.")
    if chosen["id"] == default["id"]:
        reason = "Your preferences agree with the default pick."
    else:
        if cap is not None and default["incremental_cost_usd"] > cap:
            why = f"The ${cap} spend cap rules out “{default['label']}” (${default['incremental_cost_usd']})"
        else:
            why = f"You prefer the {RULES[rule][0].lower()}{RULES[rule][1:]}"
        reason = f"{why}; “{chosen['label']}” {_trade_off(chosen, default)}."
    return {
        "rule": rule,
        "rule_label": RULES[rule],
        "max_cost_usd": cap,
        "note": preferences.get("note", ""),
        "updated_at": preferences.get("updated_at"),
        "preferred_plan_id": chosen["id"],
        "preferred_plan_label": chosen["label"],
        "default_plan_id": default["id"],
        "default_plan_label": default["label"],
        "changes_pick": chosen["id"] != default["id"],
        "reason": reason,
        "warnings": warnings,
    }
