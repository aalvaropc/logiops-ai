"""Amazon Alexa+ track: real MCP tools over Streamable HTTP."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings

from .service import LogiOpsService, WorkflowError


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
        """Read the current shipment and its delayed ETA."""
        try:
            return service.get(shipment_id)["state"]["shipment"]
        except WorkflowError as exc:
            raise ToolError(str(exc)) from exc

    @server.tool()
    async def get_order(order_id: str) -> dict[str, Any]:
        """Read the order associated with a shipment."""
        order = service.get("SHIP-421")["state"]["order"]
        if order["id"] != order_id:
            raise ToolError(f"Unknown order: {order_id}")
        return order

    @server.tool()
    async def get_inventory(warehouse_id: str, sku: str) -> dict[str, Any]:
        """Read synthetic available stock at a warehouse."""
        state = service.get("SHIP-421")["state"]
        if warehouse_id != "arequipa" or sku != state["order"]["sku"]:
            raise ToolError("Unknown warehouse or SKU")
        return {"warehouse_id": warehouse_id, **state["inventory"][warehouse_id]}

    @server.tool()
    async def find_alternative_carriers(shipment_id: str) -> dict[str, Any]:
        """Read carrier capacity, ETA, and incremental cost quotes."""
        try:
            return service.get(shipment_id)["state"]["carriers"]
        except WorkflowError as exc:
            raise ToolError(str(exc)) from exc

    @server.tool()
    async def investigate_incident(shipment_id: str) -> dict[str, Any]:
        """Investigate the incident and calculate feasible plans."""
        try:
            plans = service.investigate(shipment_id)
        except WorkflowError as exc:
            raise ToolError(str(exc)) from exc
        return {"source_version": plans[0]["source_version"], "plans": plans}

    @server.tool()
    async def get_execution_status(shipment_id: str) -> dict[str, Any]:
        """Read approvals, execution status, and audit events."""
        try:
            snapshot = service.get(shipment_id)
        except WorkflowError as exc:
            raise ToolError(str(exc)) from exc
        return {
            "status": snapshot["state"]["status"],
            "approvals": snapshot["approvals"],
            "executions": snapshot["executions"],
            "events": snapshot["events"],
        }

    @server.tool()
    async def execute_approved_plan(shipment_id: str, plan_id: str, source_version: int) -> dict[str, Any]:
        """Execute only a plan already approved by a human through the local API."""
        try:
            return service.execute(shipment_id, plan_id, source_version)
        except WorkflowError as exc:
            raise ToolError(str(exc)) from exc

    return server
