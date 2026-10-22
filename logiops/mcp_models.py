"""Output schemas of the MCP tools.

Each tool declares the fields it always returns; optional fields (such as the operator's
preferences) are allowed as extra properties, so a client can rely on the schema without the
server inventing empty values.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field

def spoken_number(value: object) -> object:
    """A shipment number a client sent as a JSON number, such as 433, read as the text the ids are matched on."""
    return str(value) if isinstance(value, int) and not isinstance(value, bool) else value


ShipmentId = Annotated[str, BeforeValidator(spoken_number), Field(
    description="Incident (shipment) id, such as SHIP-433. Also accepted: 433, ship 433, ship-433, case 433.",
    min_length=1, max_length=40,
)]
OrderId = Annotated[str, Field(
    description="Customer order id, such as ORD-421 or ORD-433A (case-insensitive). get_shipment lists them.",
    min_length=1, max_length=40,
)]


class Output(BaseModel):
    model_config = ConfigDict(extra="allow")


class OrderLine(Output):
    id: str = Field(description="Order id, such as ORD-433A.")
    customer: str
    priority: Literal["critical", "standard"]
    quantity: int = Field(description="Units ordered.")
    due_eta: str = Field(description="Promised delivery time, ISO 8601 in the incident's local time (UTC-05:00 in the sample incidents).")


class IncidentSummary(Output):
    incident_id: str
    kind: str
    kind_label: str
    title: str
    status: str = Field(description="detected, investigated, approved or verified.")
    priority: Literal["critical", "standard"]
    due_eta: str = Field(description="Earliest promised time among the incident's orders.")
    route: str
    units: int
    delay_hours: int = Field(description="Hours the delayed shipment arrives after its original ETA.")
    critical_units_at_risk: int = Field(description="Units of critical orders nothing on hand delivers in time.")
    orders: list[OrderLine]


class IncidentList(Output):
    """Every incident, in the order to work them: open first, then the most critical units at risk."""

    incidents: list[IncidentSummary]


class Shipment(Output):
    id: str
    origin: str
    destination: str
    sku: str
    units_on_delayed_route: int
    original_eta: str
    delayed_eta: str
    disruption: str
    order_ids: list[str]
    warehouse_id: str | None = Field(description="The incident's local warehouse, or null when it has none.")


class Order(Output):
    id: str
    shipment_id: str
    sku: str
    customer: str
    priority: Literal["critical", "standard"]
    quantity: int
    due_eta: str
    placed_at: str


class Stock(Output):
    warehouse_id: str
    sku: str
    available: int = Field(description="Synthetic units available.")
    ready_at: str = Field(description="When the stock can leave the warehouse, ISO 8601 in the incident's local time.")


class CarrierQuote(Output):
    capacity: int = Field(description="Units the carrier or service can move.")
    arrival_eta: str
    incremental_cost_usd: int


class PlanOrder(Output):
    order_id: str
    customer: str
    priority: Literal["critical", "standard"]
    quantity: int
    due_eta: str
    arrival_eta: str
    delay_hours: int
    late_units: int


class Allocation(Output):
    order_id: str
    source: str = Field(description="delayed-shipment, a warehouse's stock, or a carrier or service.")
    units: int
    arrival_eta: str


class Plan(Output):
    id: str = Field(description="Exact plan id; approval and execution are bound to it and to source_version.")
    kind: str
    label: str = Field(description="Plain-language name of the plan; use it when talking to a person.")
    source_version: int
    incremental_cost_usd: int
    projected_customer_delay_hours: int
    projected_completion_eta: str
    late_units: int
    delivery_status: str = Field(description="Always projected: physical delivery is not confirmed.")
    orders: list[PlanOrder]
    allocations: list[Allocation]


class Investigation(Output):
    """Every feasible plan calculated from the incident's current data; operator_preferences is
    present when saved preferences apply, with the plan they point to and why."""

    source_version: int
    plans: list[Plan]


class AuditEvent(Output):
    sequence: int
    name: str
    recorded_at: str


class ExecutionStatus(Output):
    status: str
    source_version: int
    approvals: list[dict] = Field(description="Current approvals: plan id, version, approver and time.")
    executions: list[dict]
    events: list[AuditEvent]


class Execution(Output):
    """The executed plan: units accounted for, simulated notifications and projected delivery."""

    incident_id: str
    plan_id: str
    source_version: int
    status: str
    accounted_units: int
    incremental_cost_usd: int
    projected_customer_delay_hours: int
    projected_completion_eta: str
    delivery_status: str
    notifications: list[dict]
    fulfillments: list[dict]


class BookingLine(Output):
    service: str = Field(description="Paid carrier or service, such as Express or Air freight.")
    units: int
    arrival_eta: str


class Quote(Output):
    """A price for a plan's paid carriers and services. It charges nothing and holds for ten minutes;
    cost_usd per line is present when the carrier quotes add up to the plan's cost."""

    quote_id: str
    incident_id: str
    plan_id: str
    plan_label: str
    source_version: int
    approved: bool = Field(description="Whether a person already approved the plan; booking requires it.")
    lines: list[BookingLine]
    base_usd: float = Field(description="Cost of the carriers and services.")
    service_fee_usd: float
    tax_rate: float = Field(description="Sales tax rate, applied to cost plus fee.")
    tax_label: str = Field(description="How the tax reads on a receipt, such as Tax 18%.")
    tax_usd: float
    total_usd: float = Field(description="What book_carrier charges; the person must confirm this exact amount.")
    currency: str
    payment_method: str
    expires_at: str
    summary: str = Field(description="The read-back for the person: plan, breakdown, payment method and expiry, no ids.")


class Payment(Output):
    id: str
    status: str
    amount_usd: float
    method: str
    simulated: bool


class Booking(Output):
    """A paid booking with its receipt; replayed is true when the same idempotency key returned it again."""

    number: str = Field(description="Confirmation number, such as LGO-7K2M9Q; safe to say to a person.")
    status: str
    incident_id: str
    plan_id: str
    plan_label: str
    source_version: int
    quote_id: str
    lines: list[BookingLine]
    base_usd: float
    service_fee_usd: float
    tax_rate: float
    tax_label: str
    tax_usd: float
    total_usd: float
    currency: str
    payment: Payment
    booked_by: str
    booked_at: str
    receipt_url: str
    confirmation: str = Field(description="The written confirmation to show or read to the person.")
    simulated: bool


class AlertPlan(Output):
    plan_id: str
    label: str
    incremental_cost_usd: float | None = None


class Alert(Output):
    """A proposal after the data changed; new_plan is null when no plan works any more."""

    id: str
    incident_id: str
    source_version: int
    kind: str
    change: str = Field(description="What changed, such as stock at the warehouse is now 3 units.")
    approval_invalidated: bool = Field(description="Whether a person's approval stopped applying.")
    previous_plan: AlertPlan
    new_plan: dict | None = Field(description="The recalculated pick (label, cost, delay), or null.")
    message: str = Field(description="What to tell the person; it names plans by label and approves nothing.")
    spoken: str
    created_at: str


class AlertList(Output):
    """Open alerts, newest first."""

    alerts: list[Alert]
