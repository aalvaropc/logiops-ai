"""Proactive alerts: when an incident's data changes after it was investigated, re-plan and say so.

The watcher looks for incidents whose data moved past their last calculated plans and that were
not executed. For each one it recalculates the plans (deterministic and free), applies the saved
preferences, compares the new pick with the plan approved or picked before, stores one alert per
data version, and records an `autopilot_decision` event. It never approves or books anything: the
alert proposes, and a person decides.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, ContextManager

from .preferences import PreferenceStore, preference_for
from .scenario import best_plan, incident_ids
from .service import LogiOpsService, WorkflowError
from .storage import connect

SCHEMA = """CREATE TABLE IF NOT EXISTS alerts (
    id TEXT PRIMARY KEY, incident_id TEXT NOT NULL, source_version INTEGER NOT NULL, alert_json TEXT NOT NULL,
    created_at TEXT NOT NULL, dismissed_at TEXT, UNIQUE (incident_id, source_version))"""


def _what_changed(snapshot: dict[str, Any]) -> str:
    version = snapshot["source_version"]
    change = next((event["data"] for event in reversed(snapshot["events"])
                   if event["name"] == "inventory_changed" and event["data"].get("source_version") == version), None)
    if change is None:
        return f"{snapshot['state']['incident_id']}'s data changed"
    units = change["available"]
    return f"{change['warehouse_id'].replace('-', ' ').title()} stock is now {units} unit{'' if units == 1 else 's'}"


def _delay(plan: dict[str, Any], unit: str = "h") -> str:
    hours = plan["projected_customer_delay_hours"]
    if not hours:
        return "on time"
    return f"{hours} h late" if unit == "h" else f"{hours} hour{'' if hours == 1 else 's'} late"


def _late_critical(plan: dict[str, Any]) -> list[str]:
    return [order["customer"] for order in plan.get("orders", []) if order["priority"] == "critical" and order["delay_hours"] > 0]


class AlertWatcher:
    """Finds incidents whose plans went stale, re-plans them and keeps the alerts."""

    def __init__(
        self, db_path: str | Path, service: LogiOpsService, preferences: PreferenceStore, *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.db_path = Path(db_path)
        self.service = service
        self.preferences = preferences
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        with self._connection() as connection:
            connection.execute(SCHEMA)

    def _connection(self) -> ContextManager[sqlite3.Connection]:
        return connect(self.db_path)

    def _known(self, incident_id: str, version: int) -> bool:
        with self._connection() as connection:
            return connection.execute(
                "SELECT 1 FROM alerts WHERE incident_id = ? AND source_version = ?", (incident_id, version)).fetchone() is not None

    def scan(self) -> list[dict[str, Any]]:
        """New alerts for every incident whose plans went stale; repeating a scan adds nothing."""
        return [alert for incident_id in incident_ids() if (alert := self.check(incident_id))]

    def check(self, incident_id: str) -> dict[str, Any] | None:
        snapshot = self.service.get(incident_id)
        version = snapshot["source_version"]
        planned = max((plan["source_version"] for plan in snapshot["plans"]), default=None)
        if snapshot["executions"] or planned is None or planned >= version or self._known(incident_id, version):
            return None
        earlier = [plan for plan in snapshot["plans"] if plan["source_version"] == planned]
        saved = self.preferences.get()
        approval = next((item for item in snapshot["approvals"] if item["source_version"] == planned), None)
        if approval:
            before = next(plan for plan in earlier if plan["id"] == approval["plan_id"])
        else:
            preferred = preference_for(earlier, saved)
            before = next((plan for plan in earlier if preferred and plan["id"] == preferred["preferred_plan_id"]), None) or best_plan(earlier)
        change = _what_changed(snapshot)
        lead = (f"Heads up on {incident_id}: {change}, so your approved plan “{before['label']}” no longer applies."
                if approval else f"Heads up on {incident_id}: {change}, so the plans I gave you are out of date.")
        try:
            plans = self.service.investigate(incident_id)
        except WorkflowError as exc:
            pick = None
            message = f"{lead} I recalculated, and no plan works with the new data: {exc}. A person needs to change the data or the carriers."
            spoken = f"Heads up on {incident_id}: {change}. No plan works with the new data anymore. Someone needs to look at it."
        else:
            preferred = preference_for(plans, saved)
            pick = next((plan for plan in plans if preferred and plan["id"] == preferred["preferred_plan_id"]), None) or best_plan(plans)
            late = _late_critical(pick)
            risk = f" It still leaves the critical order for {' and '.join(late)} late." if late else ""
            same = pick["kind"] == before["kind"]
            verdict = (f"“{pick['label']}” still works and is still my pick: ${pick['incremental_cost_usd']}, {_delay(pick)}."
                       if same else f"The new pick is “{pick['label']}”: ${pick['incremental_cost_usd']}, {_delay(pick)}.")
            message = (f"{lead} I recalculated the plans. {verdict}{risk} Nothing was approved; "
                       "say “approve the recommended plan”, or ask me about it.")
            spoken = (f"Heads up on {incident_id}: {change}. I recalculated; "
                      + (f"{pick['label']} still works, ${pick['incremental_cost_usd']}, {_delay(pick, 'hours')}."
                         if same else f"the new pick is {pick['label']}, ${pick['incremental_cost_usd']}, {_delay(pick, 'hours')}.")
                      + " Nothing was approved.")
        now = self.clock().isoformat()
        alert = {
            "id": f"{incident_id}-v{version}", "incident_id": incident_id, "source_version": version,
            "kind": "data_changed", "change": change, "approval_invalidated": bool(approval),
            "previous_plan": {"plan_id": before["id"], "label": before["label"]},
            "new_plan": None if pick is None else {
                "plan_id": pick["id"], "label": pick["label"], "incremental_cost_usd": pick["incremental_cost_usd"],
                "projected_customer_delay_hours": pick["projected_customer_delay_hours"],
            },
            "message": message, "spoken": spoken, "created_at": now,
        }
        with self._connection() as connection:
            inserted = connection.execute(
                "INSERT OR IGNORE INTO alerts (id, incident_id, source_version, alert_json, created_at) VALUES (?, ?, ?, ?, ?)",
                (alert["id"], incident_id, version, json.dumps(alert), now),
            ).rowcount
        if not inserted:
            return None
        self.service.record_agent_event(incident_id, "autopilot_decision", {
            "job": "alert", "decision": "propose", "reason": "data_changed", "change": change,
            "previous_plan_id": before["id"], "proposed_plan_id": pick["id"] if pick else None,
            "approved": False,
        })
        return alert

    def open_alerts(self) -> list[dict[str, Any]]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT alert_json FROM alerts WHERE dismissed_at IS NULL ORDER BY created_at DESC, id").fetchall()
        return [json.loads(row[0]) for row in rows]

    def dismiss(self, alert_id: str) -> dict[str, Any]:
        with self._connection() as connection:
            row = connection.execute("SELECT alert_json FROM alerts WHERE id = ?", (alert_id,)).fetchone()
            if row is None:
                raise WorkflowError("No alert has that id.", 404)
            connection.execute("UPDATE alerts SET dismissed_at = COALESCE(dismissed_at, ?) WHERE id = ?",
                               (self.clock().isoformat(), alert_id))
        return {**json.loads(row[0]), "dismissed": True}

    def clear(self, incident_id: str | None = None) -> None:
        with self._connection() as connection:
            if incident_id is None:
                connection.execute("DELETE FROM alerts")
            else:
                connection.execute("DELETE FROM alerts WHERE incident_id = ?", (incident_id,))
