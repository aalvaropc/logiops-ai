"""The incident workflow: inbox, snapshot, plans, approval, execution, demo controls, alerts and metrics."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Request

from ..identity import OPERATOR, actor_of, has_permission, profile_of
from ..metrics import incident_metrics, session_metrics
from ..preferences import preference_for
from ..presentation import customer_text
from ..scenario import incident_ids
from .context import Context, visible_plans
from .models import ApprovalRequest, ExecutionRequest, InventoryChange, ResetRequest


def router(ctx: Context) -> APIRouter:
    service, preferences, bookings, alerts, memory = ctx.service, ctx.preferences, ctx.bookings, ctx.alerts, ctx.memory
    routes = APIRouter()

    @routes.post("/demo/reset")
    async def reset(request: ResetRequest | None = None) -> dict[str, Any]:
        """Restore every synthetic incident and forget the preferences, bookings and the shared demo operator's
        memory, or reset only the incident named."""
        incident_id = request.incident_id if request else None
        if incident_id is None:
            preferences.clear_all()
            await asyncio.to_thread(memory.forget, OPERATOR)
        snapshot = service.reset(incident_id)
        bookings.clear(incident_id)
        alerts.clear(incident_id)
        return snapshot

    @routes.post("/demo/inventory")
    async def change_inventory(change: InventoryChange) -> dict[str, Any]:
        """Inject a stock change at an incident's warehouse to demonstrate stale-plan protection; an
        incident that was already investigated is re-planned at once and gets an alert."""
        snapshot = service.set_local_inventory(change.incident_id, change.available)
        if alerts.check(change.incident_id):
            snapshot = service.get(change.incident_id)
        return snapshot

    @routes.get("/alerts")
    async def list_alerts() -> dict[str, Any]:
        """Open proactive alerts, newest first: what changed, the plan it affects and the new pick. They never approve."""
        return {"alerts": alerts.open_alerts()}

    @routes.post("/alerts/{alert_id}/dismiss")
    async def dismiss_alert(alert_id: str) -> dict[str, Any]:
        return alerts.dismiss(alert_id)

    @routes.get("/incidents")
    async def list_incidents() -> dict[str, Any]:
        """The incident inbox: open first, then by critical units at risk, priority and due time."""
        return {"incidents": service.list_incidents()}

    @routes.get("/metrics")
    async def metrics() -> dict[str, Any]:
        items = [incident_metrics(service.get(incident_id), bookings.for_incident(incident_id)) for incident_id in incident_ids()]
        public = [{key: value for key, value in item.items() if key not in ("booking_number", "booking_total_usd")} for item in items]
        return {"incidents": public, "session": session_metrics(items)}

    @routes.get("/incidents/{incident_id}")
    async def get_incident(incident_id: str, request: Request) -> dict[str, Any]:
        snapshot = service.get(incident_id)
        saved = preferences.get(profile_of(actor_of(request)))
        for event in snapshot["events"]:
            if event["name"] == "agent_investigation_completed":
                version_plans = [plan for plan in snapshot["plans"] if plan["source_version"] == event["data"]["source_version"]]
                event["data"]["display_answer"] = customer_text(event["data"]["answer"], version_plans)
        return {
            **snapshot, "operator_preferences": saved,
            "preference": preference_for(visible_plans(snapshot), saved),
            "bookings": bookings.for_incident(incident_id) if has_permission(request, "incidents.operate") else [],
        }

    @routes.post("/incidents/{incident_id}/investigate")
    async def investigate(incident_id: str) -> dict[str, Any]:
        plans = service.investigate(incident_id)
        return {"plans": plans, "source_version": plans[0]["source_version"]}

    @routes.post("/incidents/{incident_id}/approvals")
    async def approve(incident_id: str, request: ApprovalRequest) -> dict[str, Any]:
        return service.approve(incident_id, request.plan_id, request.source_version, request.approved_by)

    @routes.post("/incidents/{incident_id}/execute")
    async def execute(incident_id: str, request: ExecutionRequest) -> dict[str, Any]:
        return service.execute(incident_id, request.plan_id, request.source_version)

    return routes
