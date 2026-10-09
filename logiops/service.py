"""Persistent, provider-independent incident workflow."""

from __future__ import annotations

import json
import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .scenario import (
    INCIDENT_ID, INCIDENT_IDS, SHIPMENT_SOURCE, available_units, build_plans, inbox_key, incident_summary,
    local_warehouse, seed_state,
)
from .tools import find_alternative_carriers, get_local_inventory, get_orders, get_shipment

logger = logging.getLogger(__name__)

# Bump when the stored state, plan or table shape changes. Additive tables don't need it.
SCHEMA_VERSION = 2
APPROVER_MAX_LENGTH = 80
INCIDENT_TABLES = ("events", "executions", "approvals", "plans", "snapshot")
SCHEMA = (
    "CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
    """CREATE TABLE IF NOT EXISTS snapshot (
        incident_id TEXT PRIMARY KEY, version INTEGER NOT NULL, state_json TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS plans (
        plan_id TEXT PRIMARY KEY, incident_id TEXT NOT NULL, source_version INTEGER NOT NULL, plan_json TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS approvals (
        plan_id TEXT PRIMARY KEY, incident_id TEXT NOT NULL, source_version INTEGER NOT NULL,
        approved_by TEXT NOT NULL, approved_at TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS executions (
        plan_id TEXT PRIMARY KEY, incident_id TEXT NOT NULL, result_json TEXT NOT NULL, executed_at TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS events (
        sequence INTEGER PRIMARY KEY AUTOINCREMENT, incident_id TEXT NOT NULL, name TEXT NOT NULL,
        data_json TEXT NOT NULL, recorded_at TEXT NOT NULL)""",
    "CREATE INDEX IF NOT EXISTS plans_by_incident ON plans (incident_id, source_version)",
    "CREATE INDEX IF NOT EXISTS events_by_incident ON events (incident_id, sequence)",
)


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
        # One transaction: a failed migration leaves the old database untouched.
        # (executescript would commit first, so each statement runs on its own.)
        with self._connection(write=True) as connection:
            stored = self._stored_schema(connection)
            migrated_from = stored if stored is not None and stored != SCHEMA_VERSION else None
            if migrated_from is not None:
                # The incidents are synthetic, so an older layout is rebuilt, not converted.
                for table in INCIDENT_TABLES:
                    connection.execute(f"DROP TABLE IF EXISTS {table}")
            for statement in SCHEMA:
                connection.execute(statement)
            connection.execute(
                "INSERT INTO meta (key, value) VALUES ('schema_version', ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (str(SCHEMA_VERSION),),
            )
            seeded = {row[0] for row in connection.execute("SELECT incident_id FROM snapshot")}
            for incident_id in INCIDENT_IDS:
                if incident_id not in seeded:
                    self._seed(connection, incident_id)
                    if migrated_from is not None:
                        self._event(connection, incident_id, "schema_migrated",
                                    {"from_schema": migrated_from, "to_schema": SCHEMA_VERSION})
        if migrated_from is not None:
            logger.warning("Stored data used schema %s; rebuilt the synthetic incidents for schema %s",
                           migrated_from, SCHEMA_VERSION)

    @staticmethod
    def _stored_schema(connection: sqlite3.Connection) -> int | None:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        if "meta" in tables:
            row = connection.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
            if row:
                return int(row[0])
        # Before the meta table, the only layout was the single-incident one.
        return 1 if "snapshot" in tables else None

    @contextmanager
    def _connection(self, *, write: bool = False) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.db_path, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=5000")
        try:
            # Reads take a transaction too, so a write that commits between two SELECTs
            # cannot mix the old state with the new rows (a deferred BEGIN holds the read lock).
            connection.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def _event(connection: sqlite3.Connection, incident_id: str, name: str, data: dict[str, Any]) -> None:
        connection.execute(
            "INSERT INTO events (incident_id, name, data_json, recorded_at) VALUES (?, ?, ?, ?)",
            (incident_id, name, _json({**data, "incident_id": incident_id}), datetime.now(timezone.utc).isoformat()),
        )

    @classmethod
    def _seed(cls, connection: sqlite3.Connection, incident_id: str) -> None:
        connection.execute(
            "INSERT INTO snapshot (incident_id, version, state_json) VALUES (?, ?, ?)",
            (incident_id, 1, _json(seed_state(incident_id))),
        )
        cls._event(connection, incident_id, "scenario_reset", {"source_version": 1})

    @staticmethod
    def _snapshot(connection: sqlite3.Connection, incident_id: str) -> tuple[dict[str, Any], int]:
        row = connection.execute(
            "SELECT state_json, version FROM snapshot WHERE incident_id = ?", (incident_id,)
        ).fetchone()
        if row is None:
            raise WorkflowError(f"Unknown incident: {incident_id}", 404)
        return json.loads(row["state_json"]), row["version"]

    @staticmethod
    def _plan(connection: sqlite3.Connection, incident_id: str, plan_id: str) -> dict[str, Any]:
        # A plan id from another incident is unknown here, never applied to this one.
        row = connection.execute(
            "SELECT plan_json FROM plans WHERE plan_id = ? AND incident_id = ?", (plan_id, incident_id)
        ).fetchone()
        if row is None:
            raise WorkflowError(f"Unknown plan: {plan_id}", 404)
        return json.loads(row["plan_json"])

    def reset(self, incident_id: str | None = None) -> dict[str, Any]:
        """Restore one incident, or all of them, to its original synthetic state."""
        if incident_id is not None and incident_id not in INCIDENT_IDS:
            raise WorkflowError(f"Unknown incident: {incident_id}", 404)
        with self._connection(write=True) as connection:
            if incident_id is None:
                for table in INCIDENT_TABLES:
                    connection.execute(f"DELETE FROM {table}")
            else:
                for table in INCIDENT_TABLES:
                    connection.execute(f"DELETE FROM {table} WHERE incident_id = ?", (incident_id,))
            for item in INCIDENT_IDS if incident_id is None else (incident_id,):
                self._seed(connection, item)
        return self.get(incident_id or INCIDENT_ID)

    def get(self, incident_id: str) -> dict[str, Any]:
        with self._connection() as connection:
            state, version = self._snapshot(connection, incident_id)
            plans = [
                json.loads(row[0]) for row in connection.execute(
                    "SELECT plan_json FROM plans WHERE incident_id = ? ORDER BY rowid", (incident_id,))
            ]
            # Approvals from earlier versions stay in the audit trail, but only the
            # current version's approval can be executed, so flag it explicitly.
            approvals = [
                {**dict(row), "is_current": row["source_version"] == version}
                for row in connection.execute(
                    "SELECT plan_id, source_version, approved_by, approved_at FROM approvals "
                    "WHERE incident_id = ? ORDER BY rowid", (incident_id,))
            ]
            executions = [
                json.loads(row[0]) for row in connection.execute(
                    "SELECT result_json FROM executions WHERE incident_id = ? ORDER BY rowid", (incident_id,))
            ]
            events = [
                {
                    "sequence": row["sequence"],
                    "name": row["name"],
                    "data": json.loads(row["data_json"]),
                    "recorded_at": row["recorded_at"],
                }
                for row in connection.execute(
                    "SELECT sequence, name, data_json, recorded_at FROM events WHERE incident_id = ? ORDER BY sequence",
                    (incident_id,))
            ]
        return {
            "source_version": version,
            "state": state,
            "plans": plans,
            "approvals": approvals,
            "executions": executions,
            "events": events,
        }

    def list_incidents(self) -> list[dict[str, Any]]:
        """Every incident as an inbox entry: open first, then by due time and priority."""
        with self._connection() as connection:
            rows = connection.execute("SELECT state_json, version FROM snapshot").fetchall()
        return sorted((incident_summary(json.loads(row["state_json"]), row["version"]) for row in rows), key=inbox_key)

    def investigate(self, incident_id: str) -> list[dict[str, Any]]:
        with self._connection(write=True) as connection:
            state, version = self._snapshot(connection, incident_id)
            if state["status"] in ("executed", "verified"):
                raise WorkflowError("The incident has already been executed")
            observed = {
                **state,
                "shipment": get_shipment(state),
                "orders": get_orders(state),
                "inventory": get_local_inventory(state),
                "carriers": find_alternative_carriers(state),
            }
            plans = build_plans(observed, version)
            if not plans:
                raise WorkflowError(
                    f"No feasible plan for {incident_id}: the current stock and carrier capacity cannot cover every order")
            existing = connection.execute(
                "SELECT 1 FROM plans WHERE incident_id = ? AND source_version = ? LIMIT 1", (incident_id, version)
            ).fetchone()
            if not existing:
                for plan in plans:
                    connection.execute(
                        "INSERT INTO plans (plan_id, incident_id, source_version, plan_json) VALUES (?, ?, ?, ?)",
                        (plan["id"], incident_id, version, _json(plan)),
                    )
                state["status"] = "investigated"
                connection.execute(
                    "UPDATE snapshot SET state_json = ? WHERE incident_id = ?", (_json(state), incident_id)
                )
                self._event(connection, incident_id, "incident_investigated",
                            {"source_version": version, "plan_ids": [p["id"] for p in plans]})
            return plans

    def approve(self, incident_id: str, plan_id: str, source_version: int, approved_by: str) -> dict[str, Any]:
        if not approved_by.strip():
            raise WorkflowError("approved_by is required", 422)
        if len(approved_by.strip()) > APPROVER_MAX_LENGTH:
            raise WorkflowError(f"approved_by must be at most {APPROVER_MAX_LENGTH} characters", 422)
        with self._connection(write=True) as connection:
            state, current_version = self._snapshot(connection, incident_id)
            plan = self._plan(connection, incident_id, plan_id)
            if plan["source_version"] != source_version or current_version != source_version:
                raise WorkflowError("Plan is stale; investigate the incident again")
            if state["status"] in ("executed", "verified"):
                raise WorkflowError("The incident has already been executed")
            selected = connection.execute(
                "SELECT plan_id FROM approvals WHERE incident_id = ? AND source_version = ? LIMIT 1",
                (incident_id, source_version),
            ).fetchone()
            if selected and selected["plan_id"] != plan_id:
                raise WorkflowError("A different plan is already approved for this version")
            existing = connection.execute(
                "SELECT plan_id, source_version, approved_by, approved_at FROM approvals WHERE plan_id = ?", (plan_id,)
            ).fetchone()
            if existing:
                return dict(existing)
            approved_at = datetime.now(timezone.utc).isoformat()
            connection.execute(
                "INSERT INTO approvals (plan_id, incident_id, source_version, approved_by, approved_at) VALUES (?, ?, ?, ?, ?)",
                (plan_id, incident_id, source_version, approved_by.strip(), approved_at),
            )
            state["status"] = "approved"
            state["selected_plan_id"] = plan_id
            connection.execute("UPDATE snapshot SET state_json = ? WHERE incident_id = ?", (_json(state), incident_id))
            self._event(connection, incident_id, "plan_approved", {
                "plan_id": plan_id, "source_version": source_version, "approved_by": approved_by.strip(),
            })
            return {
                "plan_id": plan_id,
                "source_version": source_version,
                "approved_by": approved_by.strip(),
                "approved_at": approved_at,
            }

    @staticmethod
    def _checked_use(state: dict[str, Any], plan: dict[str, Any]) -> dict[str, int]:
        """Units the plan takes from each source, after checking it covers every order exactly."""
        orders = {order["id"]: order for order in state["orders"]}
        pool = available_units(state)
        per_order = dict.fromkeys(orders, 0)
        use: dict[str, int] = {}
        for allocation in plan["allocations"]:
            order_id, source, units = allocation.get("order_id"), allocation["source"], allocation["units"]
            if order_id not in orders:
                raise WorkflowError(f"Plan allocates units to an unknown order: {order_id}")
            if not isinstance(units, int) or isinstance(units, bool) or units <= 0:
                raise WorkflowError("Plan allocations must be whole, positive unit counts")
            if source not in pool:
                raise WorkflowError(f"Unknown allocation source: {source}")
            per_order[order_id] += units
            use[source] = use.get(source, 0) + units
        if any(per_order[order_id] != order["quantity"] for order_id, order in orders.items()):
            raise WorkflowError("Plan does not account for the full order")
        for source, units in use.items():
            if pool[source][0] < units:
                raise WorkflowError(
                    "Insufficient local inventory" if source.endswith("-stock") else f"Insufficient {source} capacity")
        return use

    def execute(self, incident_id: str, plan_id: str, source_version: int) -> dict[str, Any]:
        with self._connection(write=True) as connection:
            state, current_version = self._snapshot(connection, incident_id)
            existing = connection.execute(
                "SELECT result_json FROM executions WHERE plan_id = ? AND incident_id = ?", (plan_id, incident_id)
            ).fetchone()
            if existing:
                return json.loads(existing["result_json"])
            plan = self._plan(connection, incident_id, plan_id)
            if plan["source_version"] != source_version or current_version != source_version:
                raise WorkflowError("Plan is stale; investigate the incident again")
            approved = connection.execute(
                "SELECT 1 FROM approvals WHERE plan_id = ? AND incident_id = ? AND source_version = ?",
                (plan_id, incident_id, source_version),
            ).fetchone()
            if not approved:
                raise WorkflowError("The exact plan and version must be approved before execution")
            use = self._checked_use(state, plan)
            for source, units in use.items():
                if source.endswith("-stock"):
                    state["inventory"][source.removesuffix("-stock")]["available"] -= units
                elif source in state["carriers"]:
                    state["carriers"][source]["capacity"] -= units
            for allocation in plan["allocations"]:
                if allocation["source"] != SHIPMENT_SOURCE:
                    state["fulfillments"].append({
                        "id": f"{plan_id}:{allocation['order_id']}:{allocation['source']}",
                        "order_id": allocation["order_id"],
                        "source": allocation["source"],
                        "units": allocation["units"],
                        "arrival_eta": allocation["arrival_eta"],
                    })
            # Units of these orders that stay on the delayed shipment (all of them for "wait").
            state["shipment"]["units_on_delayed_route"] = use.get(SHIPMENT_SOURCE, 0)
            state["selected_plan_id"] = plan_id
            notifications = [
                {"id": f"{plan_id}:customer:{order['id']}", "recipient": "customer", "order_id": order["id"],
                 "status": "simulated-sent"}
                for order in state["orders"]
            ] + [{"id": f"{plan_id}:operations", "recipient": "operations", "status": "simulated-sent"}]
            state["notifications"].extend(notifications)
            state["status"] = "verified"
            if any(stock["available"] < 0 for stock in state["inventory"].values()):
                raise WorkflowError("Inventory became negative")
            accounted = state["shipment"]["units_on_delayed_route"] + sum(
                item["units"] for item in state["fulfillments"]
            )
            if accounted != sum(order["quantity"] for order in state["orders"]):
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
                "accounted_units": accounted,
                "orders": [
                    {"order_id": order["id"],
                     "units": sum(a["units"] for a in plan["allocations"] if a["order_id"] == order["id"])}
                    for order in state["orders"]
                ],
                "fulfillments": state["fulfillments"],
                "notifications": state["notifications"],
            }
            connection.execute(
                "UPDATE snapshot SET version = ?, state_json = ? WHERE incident_id = ?",
                (current_version + 1, _json(state), incident_id),
            )
            connection.execute(
                "INSERT INTO executions (plan_id, incident_id, result_json, executed_at) VALUES (?, ?, ?, ?)",
                (plan_id, incident_id, _json(result), datetime.now(timezone.utc).isoformat()),
            )
            self._event(connection, incident_id, "plan_executed", {"plan_id": plan_id, "allocations": plan["allocations"]})
            self._event(connection, incident_id, "notifications_simulated", {
                "plan_id": plan_id, "recipients": [item["recipient"] for item in notifications],
            })
            self._event(connection, incident_id, "execution_verified", {"plan_id": plan_id, "accounted_units": accounted})
            return result

    def set_local_inventory(self, incident_id: str, available: int) -> dict[str, Any]:
        if available < 0:
            raise WorkflowError("Inventory cannot be negative", 422)
        with self._connection(write=True) as connection:
            state, version = self._snapshot(connection, incident_id)
            warehouse = local_warehouse(state)
            if warehouse is None:
                raise WorkflowError(f"{incident_id} has no local stock to change", 422)
            if state["status"] == "verified":
                raise WorkflowError("Reset the demo before changing an executed incident")
            state["inventory"][warehouse]["available"] = available
            state["status"] = "detected"
            state["selected_plan_id"] = None
            connection.execute(
                "UPDATE snapshot SET version = ?, state_json = ? WHERE incident_id = ?",
                (version + 1, _json(state), incident_id),
            )
            self._event(connection, incident_id, "inventory_changed",
                        {"warehouse_id": warehouse, "available": available, "source_version": version + 1})
        return self.get(incident_id)

    # autopilot_decision: a bounded server policy's auto-or-escalate verdict, with its reasons.
    AGENT_EVENTS = frozenset({"agent_run_failed", "agent_verification_completed", "autopilot_decision"})

    def record_agent_event(self, incident_id: str, name: str, data: dict[str, Any]) -> dict[str, Any]:
        """Audit agent activity that is not a completed investigation (failures, verifications, decisions)."""
        if name not in self.AGENT_EVENTS:
            raise WorkflowError(f"Unsupported agent event: {name}", 422)
        with self._connection(write=True) as connection:
            _state, version = self._snapshot(connection, incident_id)
            self._event(connection, incident_id, name, {**data, "source_version": version})
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
                    "SELECT plan_json FROM plans WHERE incident_id = ? AND source_version = ? ORDER BY rowid",
                    (incident_id, version),
                )
            ]
            if not plans:
                raise WorkflowError("Agent finished without current incident plans")
            self._event(connection, incident_id, "agent_investigation_completed", {
                "source_version": version,
                "answer": run["answer"],
                "tool_trace": run["tool_trace"],
                "usage": run["usage"],
                "mode": run["mode"],
                # The grounding checks and the model, when the agent ran them, so a reload shows them.
                **{key: run[key] for key in ("model", "evaluations", "grounded") if key in run},
            })
            return {"plans": plans, "source_version": version}
