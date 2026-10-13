"""Outcome metrics per incident and for the session, read from the recorded events: nothing is estimated."""

from __future__ import annotations

from datetime import datetime
from statistics import median
from typing import Any, Iterable


def _at(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _first(events: list[dict[str, Any]], name: str, **match: Any) -> dict[str, Any] | None:
    return next((event for event in events if event["name"] == name
                 and all(event["data"].get(key) == value for key, value in match.items())), None)


def _seconds(start: dict[str, Any] | None, end: dict[str, Any] | None) -> float | None:
    if start is None or end is None:
        return None
    return round(max(0.0, (_at(end["recorded_at"]) - _at(start["recorded_at"])).total_seconds()), 1)


def incident_metrics(snapshot: dict[str, Any], bookings: Iterable[dict[str, Any]] = ()) -> dict[str, Any]:
    """What happened to one incident: the plan decided and executed, its cost and service outcome, the
    time from the first investigation to the approval and to the verified execution, the paid booking
    and what the agent spent. Fields are None until the step they describe has happened."""
    events = snapshot["events"]
    state = snapshot["state"]
    execution = snapshot["executions"][0] if snapshot["executions"] else None
    version = execution["source_version"] if execution else snapshot["source_version"]
    approval = next((item for item in snapshot["approvals"] if item["source_version"] == version), None)
    plan_id = execution["plan_id"] if execution else approval["plan_id"] if approval else None
    plan = next((item for item in snapshot["plans"] if item["id"] == plan_id), None)
    investigated = _first(events, "incident_investigated")
    approved = _first(events, "plan_approved", plan_id=plan_id) if plan_id else None
    verified = _first(events, "execution_verified", plan_id=plan_id) if execution else None
    runs = [event["data"] for event in events if event["name"] == "agent_investigation_completed"]
    booking = next((item for item in bookings if item["plan_id"] == plan_id), None) if plan_id else None
    orders = plan["orders"] if plan else []
    return {
        "incident_id": state["incident_id"], "kind": state["kind"], "status": state["status"],
        "units": sum(order["quantity"] for order in state["orders"]),
        "critical_units": sum(order["quantity"] for order in state["orders"] if order["priority"] == "critical"),
        "investigations": len(runs),
        "mode": runs[-1]["mode"] if runs else None,
        "model_calls": sum(1 for run in runs if run["mode"] != "replay"),
        "tokens": sum((run["usage"] or {}).get("inputTokens", 0) + (run["usage"] or {}).get("outputTokens", 0) for run in runs),
        "decided": approval is not None, "executed": execution is not None,
        "time_to_decision_s": _seconds(investigated, approved),
        "time_to_execution_s": _seconds(investigated, verified),
        "chosen_plan_id": plan_id, "chosen_plan_label": plan["label"] if plan else None,
        "chosen_plan_cost_usd": plan["incremental_cost_usd"] if plan else None,
        "customer_delay_hours": plan["projected_customer_delay_hours"] if plan else None,
        "critical_units_on_time": sum(order["quantity"] - order.get("late_units", 0) for order in orders if order["priority"] == "critical") if plan else None,
        "late_units": plan.get("late_units", sum(order.get("late_units", 0) for order in orders)) if plan else None,
        "booking_number": booking["number"] if booking else None,
        "booking_total_usd": booking["total_usd"] if booking else None,
    }


def _median(values: list[float]) -> float | None:
    return round(median(values), 1) if values else None


def session_metrics(items: list[dict[str, Any]]) -> dict[str, Any]:
    """Totals over the incidents of this session: how many were investigated, decided and executed, the
    median times, the money committed and what the agent spent."""
    executed = [item for item in items if item["executed"]]
    return {
        "incidents": len(items),
        "investigated": sum(1 for item in items if item["investigations"]),
        "decided": sum(1 for item in items if item["decided"]),
        "executed": len(executed),
        "median_time_to_decision_s": _median([item["time_to_decision_s"] for item in items if item["time_to_decision_s"] is not None]),
        "median_time_to_execution_s": _median([item["time_to_execution_s"] for item in items if item["time_to_execution_s"] is not None]),
        "extra_cost_usd": sum(item["chosen_plan_cost_usd"] for item in executed),
        "critical_units_on_time": sum(item["critical_units_on_time"] for item in executed),
        "late_units": sum(item["late_units"] for item in executed),
        "booked_usd": round(sum(item["booking_total_usd"] for item in items if item["booking_total_usd"] is not None), 2),
        "model_calls": sum(item["model_calls"] for item in items),
        "tokens": sum(item["tokens"] for item in items),
    }
