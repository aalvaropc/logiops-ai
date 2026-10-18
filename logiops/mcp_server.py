"""Amazon Alexa+ track: real MCP tools over Streamable HTTP."""

from __future__ import annotations

import base64
import hashlib
import json
import re
from pathlib import Path
from typing import Annotated, Any

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.server.fastmcp.prompts.base import UserMessage
from mcp.server.transport_security import TransportSecuritySettings
from mcp.shared.exceptions import UrlElicitationRequiredError
from mcp.types import (
    CallToolResult, Completion, ElicitRequestURLParams, EmbeddedResource, Icon, TextContent, TextResourceContents,
    ToolAnnotations,
)
from pydantic import Field

from . import __version__
from .alerts import AlertWatcher
from .booking import BookingStore, receipt_text
from .identity import OPERATOR, Actor, actor_of, profile_of
from .mcp_models import (
    AlertList, Booking, CarrierQuote, Execution, ExecutionStatus, IncidentList, Investigation, Order, OrderId, Quote, Shipment,
    ShipmentId, Stock,
)
from .preferences import PreferenceStore, preference_for
from .scenario import incident_ids
from .service import LogiOpsService, WorkflowError
from .skill import SKILL_MIME_TYPE, SKILL_NAME, SKILL_TEXT, SKILL_URI
from .tools import inventory_hint, inventory_view, order_view, orders_hint, shipment_view


UI_MIME_TYPE = "text/html;profile=mcp-app"
UI_FONT_TOKEN = "logiops-card-font.woff2"
UI_FONT = Path(__file__).resolve().parent / "static" / "fonts" / "overpass-latin.woff2"
UI_FIELD_TOKEN = "LOGIOPS_CARD_FIELD"
UI_FIELD = Path(__file__).resolve().parent / "static" / "field.js"
UI_HTML = (Path(__file__).resolve().parent / "static" / "resolution_options.html").read_text(encoding="utf-8").replace(
    UI_FONT_TOKEN, "data:font/woff2;base64," + base64.b64encode(UI_FONT.read_bytes()).decode("ascii")).replace(
    UI_FIELD_TOKEN, UI_FIELD.read_text(encoding="utf-8").strip())
UI_URI = f"ui://logiops/resolution-options.{hashlib.sha256(UI_HTML.encode()).hexdigest()[:8]}.html"
UI_INVOKING = "Calculating every feasible plan…"
UI_INVOKED = "Plans ready to compare"
WEBSITE_URL = "https://github.com/aalvaropc/logiops-ai"
ICON_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><rect width="64" height="64" rx="14" fill="#071318"/>'
    '<path d="M18 16h8v24h20v8H18z" fill="#72dfc7"/></svg>'
)
ICON = Icon(src="data:image/svg+xml;base64," + base64.b64encode(ICON_SVG.encode()).decode(), mimeType="image/svg+xml", sizes=["any"])
INSTRUCTIONS = """LogiOps AI resolves synthetic logistics exceptions (late or held shipments) with a person in charge.
Flow: list_incidents (already ordered by what needs attention first) -> read facts with get_shipment, get_order,
get_inventory and find_alternative_carriers -> investigate_incident calculates every feasible plan from the current
data -> recommend one plan, quoting its exact figures and calling it by its label.
Rules: plans and their numbers are calculated by code; never estimate new ones. Approval is human-only and bound to one
exact plan and data version; no tool approves. execute_approved_plan runs only an approved plan, is idempotent, and
sends simulated notifications. To book a plan's paid carriers: quote_carrier_booking, read its summary to the person,
and call book_carrier with the exact total only after an explicit yes; payment is simulated and never charged twice.
Delivery is projected, not physically confirmed. Times are the incident's local time (UTC-05:00 in the sample incidents).
All data is synthetic. The Agent Skill at skill://logiops-exception-desk/SKILL.md is the full playbook."""



def open_incidents() -> str:
    return "Incidents: " + ", ".join(incident_ids()) + "."

SHIPMENT_NUMBER = re.compile(r"^(?:ship(?:ment)?|case|incident)?[\s#_-]*(\d+)$", re.I)
READ = ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=False)


def normalized_incident(shipment_id: str) -> str:
    """SHIP-433 from SHIP-433, ship-433, ship 433, case 433 or 433; anything else is upper-cased as given."""
    text = str(shipment_id).strip()
    found = SHIPMENT_NUMBER.match(text)
    return f"SHIP-{found.group(1)}" if found else text.upper()


def create_mcp_server(
    service: LogiOpsService, *, preferences: PreferenceStore | None = None, bookings: BookingStore | None = None,
    alerts: AlertWatcher | None = None, public_host: str | None = None,
) -> FastMCP:
    bookings = bookings or BookingStore(service.db_path, service)
    alerts = alerts or AlertWatcher(service.db_path, service, preferences or PreferenceStore(service.db_path))
    allowed_hosts = ["127.0.0.1:*", "localhost:*", "[::1]:*"]
    allowed_origins = ["http://127.0.0.1:*", "http://localhost:*", "http://[::1]:*"]
    if public_host:
        allowed_hosts.append(public_host)
        allowed_origins.append(f"https://{public_host}")
    server = FastMCP(
        "LogiOps AI",
        instructions=INSTRUCTIONS,
        website_url=WEBSITE_URL,
        icons=[ICON],
        stateless_http=True,
        json_response=True,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=allowed_hosts,
            allowed_origins=allowed_origins,
        ),
    )
    server._mcp_server.version = __version__

    def fail(exc: Exception, next_step: str) -> ToolError:
        return ToolError(f"{str(exc).rstrip('.')}. Next step: {next_step}")

    def snapshot_of(shipment_id: str) -> dict[str, Any]:
        try:
            return service.get(normalized_incident(shipment_id))
        except WorkflowError as exc:
            raise fail(exc, f"use one of the open incidents from list_incidents. {open_incidents()}") from exc

    def panel_url(ctx: Context, incident: str) -> str:
        if public_host:
            return f"https://{public_host}/demo#{incident}"
        try:
            base = str(ctx.request_context.request.base_url).rstrip("/")
        except (AttributeError, ValueError):
            base = "http://127.0.0.1:8000"
        return f"{base}/demo#{incident}"

    def awaiting_approval(incident: str, plan_id: str, source_version: int) -> dict[str, Any] | None:
        """The current plan a person has not approved yet, or None (unknown, stale, approved or executed)."""
        snapshot = service.get(incident)
        if snapshot["source_version"] != source_version or snapshot["executions"]:
            return None
        plan = next((item for item in snapshot["plans"]
                     if item["id"] == plan_id and item["source_version"] == source_version), None)
        approved = any(item["plan_id"] == plan_id and item["is_current"] for item in snapshot["approvals"])
        return None if approved else plan

    def actor(ctx: Context) -> Actor:
        try:
            return actor_of(ctx.request_context.request)
        except (AttributeError, ValueError):
            return OPERATOR

    def approval_elicitation(ctx: Context, incident: str, plan: dict[str, Any], version: int, action: str, tail: str) -> UrlElicitationRequiredError:
        url = panel_url(ctx, incident)
        text = (f"A person must approve “{plan['label']}” for {incident} in the LogiOps operator panel before it can "
                f"{action}. Open {url}, approve the plan there, then ask again. {tail}")
        return UrlElicitationRequiredError([ElicitRequestURLParams(
            mode="url", message=text, url=url, elicitationId=f"approve-{incident}-v{version}",
        )], message=text)

    def skill_message() -> UserMessage:
        return UserMessage(EmbeddedResource(type="resource", resource=TextResourceContents(
            uri=SKILL_URI, mimeType=SKILL_MIME_TYPE, text=SKILL_TEXT)))

    @server.tool(title="List incidents", annotations=READ)
    async def list_incidents() -> IncidentList:
        """List every incident with its kind, priority, due time, status and critical units at risk, in the
        order to work them: open first, then the most critical units at risk, priority and due time."""
        return {"incidents": service.list_incidents()}

    @server.tool(title="Get shipment", annotations=READ)
    async def get_shipment(shipment_id: ShipmentId) -> Shipment:
        """Read the shipment behind an incident: route, delayed ETA, its order ids and its local warehouse."""
        return shipment_view(snapshot_of(shipment_id)["state"])

    @server.tool(title="Get customer order", annotations=READ)
    async def get_order(order_id: OrderId) -> Order:
        """Read a customer order (quantity, priority, due time); order ids look like ORD-421."""
        states = [service.get(item)["state"] for item in incident_ids()]
        for state in states:
            order = order_view(state, order_id)
            if order is not None:
                return order
        linked = next((state for state in states if state["incident_id"] == normalized_incident(order_id)), None)
        hint = orders_hint(linked) if linked else "Read the shipment first; it lists its order ids."
        raise ToolError(f"Unknown order: {order_id}. Next step: {hint}")

    @server.tool(title="Get warehouse stock", annotations=READ)
    async def get_inventory(
        warehouse_id: Annotated[str, Field(description="Warehouse id from get_shipment, such as arequipa.")],
        sku: Annotated[str, Field(description="Product SKU from get_shipment, such as LAPTOP-01.")],
        shipment_id: ShipmentId | None = None,
    ) -> Stock:
        """Read synthetic available stock at an incident's local warehouse (the shipment lists its warehouse_id)."""
        if shipment_id is not None:
            candidates = [snapshot_of(shipment_id)["state"]]
        else:
            candidates = [service.get(item)["state"] for item in incident_ids()]
        for state in candidates:
            stock = inventory_view(state, warehouse_id, sku)
            if stock is not None:
                return stock
        hint = inventory_hint(candidates[0]) if len(candidates) == 1 else "Read the shipment first; it names its warehouse."
        raise ToolError(f"Unknown warehouse or SKU. Next step: {hint}")

    @server.tool(title="Find alternative carriers", annotations=READ)
    async def find_alternative_carriers(shipment_id: ShipmentId) -> dict[str, CarrierQuote]:
        """Read alternative carrier and service quotes for the incident's route: capacity, ETA and incremental cost."""
        return snapshot_of(shipment_id)["state"]["carriers"]

    @server.tool(
        title="Investigate incident and calculate plans",
        annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False),
        meta={"ui": {"resourceUri": UI_URI, "invoking": UI_INVOKING, "invoked": UI_INVOKED}, "ui/resourceUri": UI_URI},
    )
    async def investigate_incident(shipment_id: ShipmentId, ctx: Context) -> Investigation:
        """Investigate the incident and calculate every feasible plan from its current data, with the operator's
        saved preferences applied. Calculating plans records them for this data version; it approves nothing."""
        try:
            plans = service.investigate(normalized_incident(shipment_id))
        except WorkflowError as exc:
            raise fail(exc, "read the incident's shipment, stock and carriers; a person may need to change the data") from exc
        result = {"source_version": plans[0]["source_version"], "plans": plans}
        preference = preference_for(plans, preferences.get(profile_of(actor(ctx))) if preferences else None)
        if preference:
            result["operator_preferences"] = preference
        return CallToolResult(
            content=[TextContent(type="text", text=json.dumps(result, indent=2))], structuredContent=result,
            _meta={"ui": {"resourceUri": UI_URI, "invoked": UI_INVOKED}},
        )

    @server.tool(title="List proactive alerts", annotations=READ)
    async def list_alerts() -> AlertList:
        """Read open alerts: incidents whose data changed after they were investigated, re-planned on the new data.
        Each names what changed, the plan it affects and the new pick; an alert never approves anything."""
        return {"alerts": alerts.open_alerts()}

    @server.tool(title="Get execution status", annotations=READ)
    async def get_execution_status(shipment_id: ShipmentId) -> ExecutionStatus:
        """Read the current approval, execution status, and audit event names."""
        snapshot = snapshot_of(shipment_id)
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

    @server.tool(
        title="Execute approved plan",
        annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=True, openWorldHint=False),
        meta={"ui": {"visibility": ["model"]}},
    )
    async def execute_approved_plan(
        shipment_id: ShipmentId,
        plan_id: Annotated[str, Field(description="Exact plan id from investigate_incident.")],
        source_version: Annotated[int, Field(description="The plan's source_version.", ge=1)],
        ctx: Context,
    ) -> Execution:
        """Execute only a plan a person already approved for this exact data version. Repeating the call returns the
        same execution; it never runs twice. Notifications to customers are simulated. If the plan still needs a
        person's approval, the error is a URL elicitation (-32042) that opens the operator panel."""
        incident = normalized_incident(shipment_id)
        try:
            return service.execute(incident, plan_id, source_version)
        except WorkflowError as exc:
            plan = awaiting_approval(incident, plan_id, source_version) if incident in incident_ids() else None
            if plan is None:
                raise fail(exc, "a person approves the exact plan and version in the operator panel; no tool can approve") from exc
            raise approval_elicitation(ctx, incident, plan, source_version, "run", "No tool can approve.") from exc

    @server.tool(
        title="Quote a carrier booking",
        annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False),
    )
    async def quote_carrier_booking(
        shipment_id: ShipmentId,
        ctx: Context,
        plan_id: Annotated[str | None, Field(
            description="Exact plan id from investigate_incident. Default: the plan a person approved.")] = None,
    ) -> Quote:
        """Price booking a plan's paid carriers and services: their cost, a service fee and a sales tax, held for ten
        minutes. It charges nothing. Read the summary back to the person and get an explicit yes before book_carrier."""
        try:
            return bookings.quote(normalized_incident(shipment_id), plan_id, actor(ctx))
        except WorkflowError as exc:
            raise fail(exc, "investigate the incident and price one of its current plans") from exc

    @server.tool(
        title="Book and pay a carrier quote",
        annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=True, openWorldHint=False),
        meta={"ui": {"visibility": ["model"]}},
    )
    async def book_carrier(
        quote_id: Annotated[str, Field(description="quote_id from quote_carrier_booking.", min_length=3, max_length=40)],
        confirmed_total_usd: Annotated[float, Field(
            description="The total the person confirmed; it must equal the quote's total_usd.", ge=0)],
        idempotency_key: Annotated[str, Field(
            description="A key you choose for this purchase (8-100 letters, digits, - or _). The same key never pays twice.",
            min_length=8, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")],
        ctx: Context,
    ) -> Booking:
        """Book and pay a quote, only after the person heard its price breakdown and said yes. It charges the quoted
        total once (simulated payment) and returns the confirmation number and receipt. A person must have approved
        the plan; otherwise the error is a URL elicitation (-32042) that opens the operator panel."""
        try:
            return bookings.confirm(quote_id, confirmed_total_usd, idempotency_key, actor(ctx))
        except WorkflowError as exc:
            quote = bookings.quote_of(quote_id)
            plan = awaiting_approval(quote["incident_id"], quote["plan_id"], quote["source_version"]) if quote else None
            if plan is not None and "approve" in str(exc):
                raise approval_elicitation(ctx, quote["incident_id"], plan, quote["source_version"], "be booked",
                                           "Nothing was charged.") from exc
            raise fail(exc, "ask for a new quote with quote_carrier_booking, read it back, and confirm its exact total") from exc

    @server.tool(title="Get booking", annotations=READ)
    async def get_booking(
        number: Annotated[str, Field(description="Confirmation number, such as LGO-7K2M9Q.", min_length=3, max_length=20)],
    ) -> Booking:
        """Read a booking and its receipt by confirmation number."""
        try:
            return bookings.get(number)
        except WorkflowError as exc:
            raise fail(exc, "use the confirmation number book_carrier returned") from exc

    @server.resource(
        UI_URI, name="resolution_options", title="Resolution options",
        description="Interactive comparison of the calculated plans. It can select a plan, never approve one.",
        mime_type=UI_MIME_TYPE, meta={"ui": {"prefersBorder": True, "csp": {"connectDomains": [], "resourceDomains": []}}},
    )
    def resolution_options() -> str:
        return UI_HTML

    @server.resource(
        SKILL_URI, name=SKILL_NAME, title="LogiOps exception desk (Agent Skill)",
        description="Agent Skill for these tools: the workflow, the rules, how to speak, and what to do when a tool fails.",
        mime_type=SKILL_MIME_TYPE,
    )
    def exception_desk_skill() -> str:
        return SKILL_TEXT

    @server.resource(
        "incident://{shipment_id}", name="incident", title="Incident record",
        description="One incident as JSON: its summary, shipment, current plans, current approval and executions.",
        mime_type="application/json",
    )
    def incident_record(shipment_id: str) -> str:
        incident = normalized_incident(shipment_id)
        if incident not in incident_ids():
            raise ValueError(f"Unknown incident: {shipment_id}. {open_incidents()}")
        snapshot = service.get(incident)
        version = snapshot["source_version"]
        return json.dumps({
            "incident": next(item for item in service.list_incidents() if item["incident_id"] == incident),
            "shipment": shipment_view(snapshot["state"]),
            "source_version": version,
            "plans": [plan for plan in snapshot["plans"] if plan["source_version"] == version],
            "approval": next((item for item in snapshot["approvals"] if item["is_current"]), None),
            "executions": snapshot["executions"],
        }, indent=2)

    @server.resource(
        "receipt://logiops/{number}", name="receipt", title="Booking receipt",
        description="A booking's receipt as Markdown: the price breakdown, payment and confirmation number.",
        mime_type="text/markdown",
    )
    def booking_receipt(number: str) -> str:
        try:
            return receipt_text(bookings.get(number))
        except WorkflowError as exc:
            raise ValueError(str(exc)) from exc

    @server.prompt(
        name="morning_briefing", title="Morning briefing",
        description="Brief me on the incident queue: what is late or held, and which incident to start with.",
    )
    def morning_briefing() -> list[UserMessage]:
        return [skill_message(), UserMessage(
            "Any delays today? Brief me on the logistics incidents, following the logiops-exception-desk skill above. "
            "Call list_incidents and keep its order. Give each open incident one short line: what happened, who is "
            "affected, and why it sits there. Count the resolved ones in one phrase, end with the incident to start "
            "with, and do not calculate or recommend plans yet."
        )]

    @server.prompt(
        name="investigate_incident", title="Investigate an incident",
        description="Read an incident's facts, calculate its plans and recommend one; a person approves.",
    )
    def investigate_prompt(
        shipment_id: Annotated[str, Field(description="Incident id, such as SHIP-433 or 433.")],
    ) -> list[UserMessage]:
        incident = normalized_incident(shipment_id)
        if incident not in incident_ids():
            raise ValueError(f"Unknown incident: {shipment_id}. {open_incidents()}")
        return [skill_message(), UserMessage(
            f"What's happening with {incident}, and which plan should we choose? Follow the logiops-exception-desk "
            "skill above: read the facts, call investigate_incident, and recommend exactly one plan by its label with "
            "its exact figures. Do not approve or execute anything."
        )]

    @server.completion()
    async def complete(ref: Any, argument: Any, context: Any) -> Completion | None:
        if argument.name != "shipment_id":
            return None
        typed = argument.value.strip().lower()
        found = SHIPMENT_NUMBER.match(typed)
        number = found.group(1) if found else typed
        values = [item["incident_id"] for item in service.list_incidents()
                  if item["incident_id"].lower().startswith(typed) or item["incident_id"].split("-", 1)[1].startswith(number)]
        return Completion(values=values, total=len(values), hasMore=False)

    return server
