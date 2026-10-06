"""Persistent, provider-independent incident workflow."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .scenario import INCIDENT_ID, QUANTITY, build_plans, seed_state
from .tools import find_alternative_carriers, get_local_inventory, get_order, get_shipment


class WorkflowError(Exception):
    def __init__(self, message: str, status_code: int = 409) -> None:
        super().__init__(message)
        self.status_code = status_code


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


class LogiOpsService:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection(write=True) as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS snapshot (
                    incident_id TEXT PRIMARY KEY,
                    version INTEGER NOT NULL,
                    state_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS plans (
                    plan_id TEXT PRIMARY KEY,
                    source_version INTEGER NOT NULL,
                    plan_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS approvals (
                    plan_id TEXT PRIMARY KEY,
                    source_version INTEGER NOT NULL,
                    approved_by TEXT NOT NULL,
                    approved_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS executions (
                    plan_id TEXT PRIMARY KEY,
                    result_json TEXT NOT NULL,
                    executed_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS events (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    data_json TEXT NOT NULL,
                    recorded_at TEXT NOT NULL
                );
                """
            )
        with self._connection() as connection:
            seeded = connection.execute("SELECT 1 FROM snapshot WHERE incident_id = ?", (INCIDENT_ID,)).fetchone()
        if not seeded:
            self.reset()

    @contextmanager
    def _connection(self, *, write: bool = False) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.db_path, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=5000")
        try:
            if write:
                connection.execute("BEGIN IMMEDIATE")
            yield connection
            if write:
                connection.commit()
        except Exception:
            if write:
                connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def _event(connection: sqlite3.Connection, name: str, data: dict[str, Any]) -> None:
        connection.execute(
            "INSERT INTO events (name, data_json, recorded_at) VALUES (?, ?, ?)",
            (name, _json(data), datetime.now(timezone.utc).isoformat()),
        )

    @staticmethod
    def _snapshot(connection: sqlite3.Connection, incident_id: str) -> tuple[dict[str, Any], int]:
        row = connection.execute(
            "SELECT state_json, version FROM snapshot WHERE incident_id = ?", (incident_id,)
        ).fetchone()
        if row is None:
            raise WorkflowError(f"Unknown incident: {incident_id}", 404)
        return json.loads(row["state_json"]), row["version"]

    @staticmethod
    def _plan(connection: sqlite3.Connection, plan_id: str) -> dict[str, Any]:
        row = connection.execute("SELECT plan_json FROM plans WHERE plan_id = ?", (plan_id,)).fetchone()
        if row is None:
            raise WorkflowError(f"Unknown plan: {plan_id}", 404)
        return json.loads(row["plan_json"])

    def reset(self) -> dict[str, Any]:
        with self._connection(write=True) as connection:
            for table in ("events", "executions", "approvals", "plans", "snapshot"):
                connection.execute(f"DELETE FROM {table}")
            state = seed_state()
            connection.execute(
                "INSERT INTO snapshot (incident_id, version, state_json) VALUES (?, ?, ?)",
                (INCIDENT_ID, 1, _json(state)),
            )
            self._event(connection, "scenario_reset", {"incident_id": INCIDENT_ID, "source_version": 1})
        return self.get(INCIDENT_ID)

    def get(self, incident_id: str) -> dict[str, Any]:
        with self._connection() as connection:
            state, version = self._snapshot(connection, incident_id)
            plans = [json.loads(row[0]) for row in connection.execute("SELECT plan_json FROM plans ORDER BY rowid")]
            # Approvals from earlier versions stay in the audit trail, but only the
            # current version's approval can be executed, so flag it explicitly.
            approvals = [
                {**dict(row), "is_current": row["source_version"] == version}
                for row in connection.execute("SELECT * FROM approvals ORDER BY rowid")
            ]
            executions = [json.loads(row[0]) for row in connection.execute("SELECT result_json FROM executions ORDER BY rowid")]
            events = [
                {
                    "sequence": row["sequence"],
                    "name": row["name"],
                    "data": json.loads(row["data_json"]),
                    "recorded_at": row["recorded_at"],
                }
                for row in connection.execute("SELECT * FROM events ORDER BY sequence")
            ]
        return {
            "source_version": version,
            "state": state,
            "plans": plans,
            "approvals": approvals,
            "executions": executions,
            "events": events,
        }

    def investigate(self, incident_id: str) -> list[dict[str, Any]]:
        with self._connection(write=True) as connection:
            state, version = self._snapshot(connection, incident_id)
            if state["status"] in ("executed", "verified"):
                raise WorkflowError("The incident has already been executed")
            observed = {
                **state,
                "shipment": get_shipment(state),
                "order": get_order(state),
                "inventory": get_local_inventory(state),
                "carriers": find_alternative_carriers(state),
            }
            plans = build_plans(observed, version)
            existing = connection.execute(
                "SELECT 1 FROM plans WHERE source_version = ? LIMIT 1", (version,)
            ).fetchone()
            if not existing:
                for plan in plans:
                    connection.execute(
                        "INSERT INTO plans (plan_id, source_version, plan_json) VALUES (?, ?, ?)",
                        (plan["id"], version, _json(plan)),
                    )
                state["status"] = "investigated"
                connection.execute(
                    "UPDATE snapshot SET state_json = ? WHERE incident_id = ?", (_json(state), incident_id)
                )
                self._event(
                    connection,
                    "incident_investigated",
                    {"incident_id": incident_id, "source_version": version, "plan_ids": [p["id"] for p in plans]},
                )
            return plans

    def approve(self, incident_id: str, plan_id: str, source_version: int, approved_by: str) -> dict[str, Any]:
        if not approved_by.strip():
            raise WorkflowError("approved_by is required", 422)
        with self._connection(write=True) as connection:
            state, current_version = self._snapshot(connection, incident_id)
            plan = self._plan(connection, plan_id)
            if plan["source_version"] != source_version or current_version != source_version:
                raise WorkflowError("Plan is stale; investigate the incident again")
            if state["status"] in ("executed", "verified"):
                raise WorkflowError("The incident has already been executed")
            selected = connection.execute(
                "SELECT plan_id FROM approvals WHERE source_version = ? LIMIT 1", (source_version,)
            ).fetchone()
            if selected and selected["plan_id"] != plan_id:
                raise WorkflowError("A different plan is already approved for this version")
            existing = connection.execute("SELECT * FROM approvals WHERE plan_id = ?", (plan_id,)).fetchone()
            if existing:
                return dict(existing)
            approved_at = datetime.now(timezone.utc).isoformat()
            connection.execute(
                "INSERT INTO approvals (plan_id, source_version, approved_by, approved_at) VALUES (?, ?, ?, ?)",
                (plan_id, source_version, approved_by.strip(), approved_at),
            )
            state["status"] = "approved"
            state["selected_plan_id"] = plan_id
            connection.execute("UPDATE snapshot SET state_json = ? WHERE incident_id = ?", (_json(state), incident_id))
            self._event(connection, "plan_approved", {
                "plan_id": plan_id, "source_version": source_version, "approved_by": approved_by.strip(),
            })
            return {
                "plan_id": plan_id,
                "source_version": source_version,
                "approved_by": approved_by.strip(),
                "approved_at": approved_at,
            }

    def execute(self, incident_id: str, plan_id: str, source_version: int) -> dict[str, Any]:
        with self._connection(write=True) as connection:
            state, current_version = self._snapshot(connection, incident_id)
            existing = connection.execute(
                "SELECT result_json FROM executions WHERE plan_id = ?", (plan_id,)
            ).fetchone()
            if existing:
                return json.loads(existing["result_json"])
            plan = self._plan(connection, plan_id)
            if plan["source_version"] != source_version or current_version != source_version:
                raise WorkflowError("Plan is stale; investigate the incident again")
            approved = connection.execute(
                "SELECT 1 FROM approvals WHERE plan_id = ? AND source_version = ?", (plan_id, source_version)
            ).fetchone()
            if not approved:
                raise WorkflowError("The exact plan and version must be approved before execution")
            if sum(item["units"] for item in plan["allocations"]) != QUANTITY:
                raise WorkflowError("Plan does not account for the full order")
            for allocation in plan["allocations"]:
                source, units = allocation["source"], allocation["units"]
                if source == "arequipa-stock":
                    if state["inventory"]["arequipa"]["available"] < units:
                        raise WorkflowError("Insufficient local inventory")
                    state["inventory"]["arequipa"]["available"] -= units
                elif source in state["carriers"]:
                    if state["carriers"][source]["capacity"] < units:
                        raise WorkflowError(f"Insufficient {source} capacity")
                    state["carriers"][source]["capacity"] -= units
                if source != "delayed-shipment":
                    state["fulfillments"].append(
                        {"id": f"{plan_id}:{source}", "source": source, "units": units, "arrival_eta": allocation["arrival_eta"]}
                    )
            if plan["kind"] != "wait":
                state["shipment"]["units_on_delayed_route"] = 0
            state["selected_plan_id"] = plan_id
            for recipient in ("customer", "operations"):
                state["notifications"].append(
                    {"id": f"{plan_id}:{recipient}", "recipient": recipient, "status": "simulated-sent"}
                )
            state["status"] = "verified"
            if state["inventory"]["arequipa"]["available"] < 0:
                raise WorkflowError("Inventory became negative")
            accounted = state["shipment"]["units_on_delayed_route"] + sum(
                item["units"] for item in state["fulfillments"]
            )
            if accounted != QUANTITY:
                raise WorkflowError("Execution lost or duplicated units")
            result = {
                "incident_id": incident_id,
                "plan_id": plan_id,
                "source_version": source_version,
                "status": "verified_operationally",
                "delivery_status": "projected",
                "projected_completion_eta": plan["projected_completion_eta"],
                "projected_customer_delay_hours": plan["projected_customer_delay_hours"],
                "incremental_cost_usd": plan["incremental_cost_usd"],
                "fulfillments": state["fulfillments"],
                "notifications": state["notifications"],
            }
            connection.execute(
                "UPDATE snapshot SET version = ?, state_json = ? WHERE incident_id = ?",
                (current_version + 1, _json(state), incident_id),
            )
            connection.execute(
                "INSERT INTO executions (plan_id, result_json, executed_at) VALUES (?, ?, ?)",
                (plan_id, _json(result), datetime.now(timezone.utc).isoformat()),
            )
            self._event(connection, "plan_executed", {"plan_id": plan_id, "allocations": plan["allocations"]})
            self._event(connection, "notifications_simulated", {"plan_id": plan_id, "recipients": ["customer", "operations"]})
            self._event(connection, "execution_verified", {"plan_id": plan_id, "accounted_units": accounted})
            return result

    def set_local_inventory(self, incident_id: str, available: int) -> dict[str, Any]:
        if available < 0:
            raise WorkflowError("Inventory cannot be negative", 422)
        with self._connection(write=True) as connection:
            state, version = self._snapshot(connection, incident_id)
            if state["status"] == "verified":
                raise WorkflowError("Reset the demo before changing an executed incident")
            state["inventory"]["arequipa"]["available"] = available
            state["status"] = "detected"
            state["selected_plan_id"] = None
            connection.execute(
                "UPDATE snapshot SET version = ?, state_json = ? WHERE incident_id = ?",
                (version + 1, _json(state), incident_id),
            )
            self._event(connection, "inventory_changed", {"available": available, "source_version": version + 1})
        return self.get(incident_id)

    AGENT_EVENTS = frozenset({"agent_run_failed", "agent_verification_completed"})

    def record_agent_event(self, incident_id: str, name: str, data: dict[str, Any]) -> dict[str, Any]:
        """Audit agent activity that is not a completed investigation (failures, verifications)."""
        if name not in self.AGENT_EVENTS:
            raise WorkflowError(f"Unsupported agent event: {name}", 422)
        with self._connection(write=True) as connection:
            _state, version = self._snapshot(connection, incident_id)
            self._event(connection, name, {**data, "incident_id": incident_id, "source_version": version})
        return {"source_version": version}

    def record_agent_run(
        self, incident_id: str, expected_version: int, run: dict[str, Any]
    ) -> dict[str, Any]:
        with self._connection(write=True) as connection:
            _state, version = self._snapshot(connection, incident_id)
            if version != expected_version:
                raise WorkflowError("Source data changed during agent investigation; run again")
            plans = [
                json.loads(row[0]) for row in connection.execute(
                    "SELECT plan_json FROM plans WHERE source_version = ? ORDER BY rowid", (version,)
                )
            ]
            if not plans:
                raise WorkflowError("Agent finished without current incident plans")
            self._event(connection, "agent_investigation_completed", {
                "incident_id": incident_id,
                "source_version": version,
                "answer": run["answer"],
                "tool_trace": run["tool_trace"],
                "usage": run["usage"],
                "mode": run["mode"],
            })
            return {"plans": plans, "source_version": version}
