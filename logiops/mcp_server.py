"""Amazon Alexa+ track: real MCP tools over Streamable HTTP."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings

from .service import LogiOpsService, WorkflowError


# MCP Apps (SEP-1865, 2026-01-26): investigate_incident declares an interactive
# view; hosts that support the extension render it, others just use the JSON.
UI_URI = "ui://logiops/resolution-options.html"
UI_MIME_TYPE = "text/html;profile=mcp-app"
UI_HTML = (Path(__file__).resolve().parent / "static" / "resolution_options.html").read_text(encoding="utf-8")


def _same(value: str, expected: str) -> bool:
    return value.strip().casefold() == expected.casefold()


def create_mcp_server(service: LogiOpsService, *, public_host: str | None = None) -> FastMCP:
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

    @server.tool()
    async def get_shipment(shipment_id: str) -> dict[str, Any]:
        """Read the current shipment, its delayed ETA, and the linked order id."""
        try:
            state = service.get(shipment_id.strip().upper())["state"]
        except WorkflowError as exc:
            raise ToolError(f"{exc}. The incident under investigation is SHIP-421.") from exc
        return {**state["shipment"], "order_id": state["order"]["id"]}

    @server.tool()
    async def get_order(order_id: str) -> dict[str, Any]:
        """Read the customer order linked to a shipment (order ids look like ORD-421)."""
        order = service.get("SHIP-421")["state"]["order"]
        if not _same(order_id, order["id"]):
            raise ToolError(f"Unknown order: {order_id}. The order linked to SHIP-421 is {order['id']}.")
        return order

    @server.tool()
    async def get_inventory(warehouse_id: str, sku: str) -> dict[str, Any]:
        """Read synthetic available stock at a warehouse."""
        state = service.get("SHIP-421")["state"]
        if not _same(warehouse_id, "arequipa") or not _same(sku, state["order"]["sku"]):
            raise ToolError(f"Unknown warehouse or SKU. Use warehouse_id 'arequipa' and sku '{state['order']['sku']}'.")
        return {"warehouse_id": "arequipa", **state["inventory"]["arequipa"]}

    @server.tool()
    async def find_alternative_carriers(shipment_id: str) -> dict[str, Any]:
        """Read carrier capacity, ETA, and incremental cost quotes."""
        try:
            return service.get(shipment_id)["state"]["carriers"]
        except WorkflowError as exc:
            raise ToolError(str(exc)) from exc

    @server.tool(meta={"ui": {"resourceUri": UI_URI}, "ui/resourceUri": UI_URI})
    async def investigate_incident(shipment_id: str) -> dict[str, Any]:
        """Investigate the incident and calculate feasible plans."""
        try:
            plans = service.investigate(shipment_id)
        except WorkflowError as exc:
            raise ToolError(str(exc)) from exc
        return {"source_version": plans[0]["source_version"], "plans": plans}

    @server.tool()
    async def get_execution_status(shipment_id: str) -> dict[str, Any]:
        """Read the current approval, execution status, and audit event names."""
        try:
            snapshot = service.get(shipment_id)
        except WorkflowError as exc:
            raise ToolError(str(exc)) from exc
        # Agent traces are stored as events; returning them here would feed every
        # previous trace back into the next model run, so only summarize events.
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

    @server.tool()
    async def execute_approved_plan(shipment_id: str, plan_id: str, source_version: int) -> dict[str, Any]:
        """Execute only a plan already approved by a human through the local API."""
        try:
            return service.execute(shipment_id, plan_id, source_version)
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
