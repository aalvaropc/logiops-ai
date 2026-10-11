"""Amazon Alexa+ track: real MCP tools over Streamable HTTP."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings

from .preferences import PreferenceStore, preference_for
from .scenario import INCIDENT_IDS
from .service import LogiOpsService, WorkflowError
from .tools import inventory_hint, inventory_view, order_view, orders_hint, shipment_view


UI_URI = "ui://logiops/resolution-options.html"
UI_MIME_TYPE = "text/html;profile=mcp-app"
UI_HTML = (Path(__file__).resolve().parent / "static" / "resolution_options.html").read_text(encoding="utf-8")


OPEN_INCIDENTS = "Incidents: " + ", ".join(INCIDENT_IDS) + "."


def create_mcp_server(
    service: LogiOpsService, *, preferences: PreferenceStore | None = None, public_host: str | None = None
) -> FastMCP:
    allowed_hosts = ["127.0.0.1:*", "localhost:*", "[::1]:*"]
    allowed_origins = ["http://127.0.0.1:*", "http://localhost:*", "http://[::1]:*"]
    if public_host:
        allowed_hosts.append(public_host)
        allowed_origins.append(f"https://{public_host}")
    server = FastMCP(
        "LogiOps AI",
        stateless_http=True,
        json_response=True,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=allowed_hosts,
            allowed_origins=allowed_origins,
        ),
    )

    def incident(shipment_id: str) -> str:
        return str(shipment_id).strip().upper()

    def state_of(shipment_id: str) -> dict[str, Any]:
        try:
            return service.get(incident(shipment_id))["state"]
        except WorkflowError as exc:
            raise ToolError(f"{exc}. {OPEN_INCIDENTS}") from exc

    @server.tool()
    async def list_incidents() -> dict[str, Any]:
        """List every open and resolved incident with its kind, priority, due time and status."""
        return {"incidents": service.list_incidents()}

    @server.tool()
    async def get_shipment(shipment_id: str) -> dict[str, Any]:
        """Read the shipment behind an incident: route, delayed ETA, its order ids and its local warehouse."""
        return shipment_view(state_of(shipment_id))

    @server.tool()
    async def get_order(order_id: str) -> dict[str, Any]:
        """Read a customer order (quantity, priority, due time); order ids look like ORD-421."""
        states = [service.get(item)["state"] for item in INCIDENT_IDS]
        for state in states:
            order = order_view(state, order_id)
            if order is not None:
                return order
        linked = next((state for state in states if state["incident_id"] == incident(order_id)), None)
        hint = orders_hint(linked) if linked else "Read the shipment first; it lists its order ids."
        raise ToolError(f"Unknown order: {order_id}. {hint}")

    @server.tool()
    async def get_inventory(warehouse_id: str, sku: str, shipment_id: str | None = None) -> dict[str, Any]:
        """Read synthetic available stock at an incident's local warehouse (the shipment lists its warehouse_id)."""
        if shipment_id is not None:
            candidates = [state_of(shipment_id)]
        else:
            candidates = [service.get(item)["state"] for item in INCIDENT_IDS]
        for state in candidates:
            stock = inventory_view(state, warehouse_id, sku)
            if stock is not None:
                return stock
        hint = inventory_hint(candidates[0]) if len(candidates) == 1 else "Read the shipment first; it names its warehouse."
        raise ToolError(f"Unknown warehouse or SKU. {hint}")

    @server.tool()
    async def find_alternative_carriers(shipment_id: str) -> dict[str, Any]:
        """Read alternative carrier and service quotes: capacity, ETA and incremental cost."""
        try:
            return service.get(incident(shipment_id))["state"]["carriers"]
        except WorkflowError as exc:
            raise ToolError(str(exc)) from exc

    @server.tool(meta={"ui": {"resourceUri": UI_URI}, "ui/resourceUri": UI_URI})
    async def investigate_incident(shipment_id: str) -> dict[str, Any]:
        """Investigate the incident and calculate feasible plans, with the operator's saved preferences applied."""
        try:
            plans = service.investigate(incident(shipment_id))
        except WorkflowError as exc:
            raise ToolError(str(exc)) from exc
        result = {"source_version": plans[0]["source_version"], "plans": plans}
        preference = preference_for(plans, preferences.get() if preferences else None)
        if preference:
            result["operator_preferences"] = preference
        return result

    @server.tool()
    async def get_execution_status(shipment_id: str) -> dict[str, Any]:
        """Read the current approval, execution status, and audit event names."""
        try:
            snapshot = service.get(incident(shipment_id))
        except WorkflowError as exc:
            raise ToolError(str(exc)) from exc
        return {
            "status": snapshot["state"]["status"],
            "source_version": snapshot["source_version"],
            "approvals": [item for item in snapshot["approvals"] if item["is_current"]],
            "executions": snapshot["executions"],
            "events": [
                {"sequence": event["sequence"], "name": event["name"], "recorded_at": event["recorded_at"]}
                for event in snapshot["events"]
            ],
        }

    @server.tool(meta={"ui": {"visibility": ["model"]}})
    async def execute_approved_plan(shipment_id: str, plan_id: str, source_version: int) -> dict[str, Any]:
        """Execute only a plan already approved by a human through the local API."""
        try:
            return service.execute(incident(shipment_id), plan_id, source_version)
        except WorkflowError as exc:
            raise ToolError(str(exc)) from exc

    @server.resource(
        UI_URI, name="resolution_options", title="Resolution options",
        description="Interactive comparison of the calculated plans. It can select a plan, never approve one.",
        mime_type=UI_MIME_TYPE, meta={"ui": {"prefersBorder": True}},
    )
    def resolution_options() -> str:
        return UI_HTML

    return server
