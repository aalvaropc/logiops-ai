"""Carrier bookings: a quote with its price breakdown, a simulated payment, and a receipt.

A quote prices the paid carriers and services of one current plan: their cost, a fixed service
fee and a sales tax (18 % by default, LOGIOPS_TAX_RATE), valid for ten minutes. Confirming it charges the quoted
total exactly once, and only when every check passes at that moment:
- the person confirmed the same total, recalculated now;
- the quote has not expired;
- the plan is the one a person approved on the current data, or it was already executed.
The same idempotency key returns the same booking, and a plan is booked at most once. Payments
are simulated; nothing leaves the demo.
"""

from __future__ import annotations

import hashlib
import html
import json
import os
import re
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any, Callable, ContextManager

from .identity import Actor
from .presentation import LIMA
from .scenario import SHIPMENT_SOURCE
from .service import LogiOpsService, WorkflowError
from .storage import connect, of_current_seed

SERVICE_FEE_CENTS = 500


def _tax_rate() -> Decimal:
    raw = os.environ.get("LOGIOPS_TAX_RATE", "0.18")
    try:
        rate = Decimal(raw)
    except ArithmeticError as exc:
        raise RuntimeError("LOGIOPS_TAX_RATE must be a decimal such as 0.18") from exc
    if not rate.is_finite() or not 0 <= rate < 1:
        raise RuntimeError("LOGIOPS_TAX_RATE must be at least 0 and below 1, such as 0.18")
    return rate


def _tax_label(name: str, rate: Decimal) -> str:
    return f"{name} {format((rate * 100).normalize(), 'f')}%"


TAX_RATE = _tax_rate()
TAX_NAME = os.environ.get("LOGIOPS_TAX_NAME", "").strip()[:24] or "Tax"
TAX_LABEL = _tax_label(TAX_NAME, TAX_RATE)
QUOTE_MINUTES = 10
NUMBER_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
BOOKING_NUMBER = re.compile(r"^LGO-[A-Z2-9]{6}$")
IDEMPOTENCY_KEY = re.compile(r"^[A-Za-z0-9_-]{8,100}$")
SCHEMA = (
    """CREATE TABLE IF NOT EXISTS booking_quotes (
        id TEXT PRIMARY KEY, incident_id TEXT NOT NULL, plan_id TEXT NOT NULL, source_version INTEGER NOT NULL,
        quote_json TEXT NOT NULL, created_at TEXT NOT NULL, expires_at TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS bookings (
        number TEXT PRIMARY KEY, quote_id TEXT NOT NULL, incident_id TEXT NOT NULL, plan_id TEXT NOT NULL UNIQUE,
        idempotency_key TEXT NOT NULL UNIQUE, booking_json TEXT NOT NULL, created_at TEXT NOT NULL)""",
)


def usd(cents: int) -> float:
    return round(cents / 100, 2)


def money(cents: int) -> str:
    return f"${cents // 100:,}.{cents % 100:02d}"


def cents_of(value: Any) -> int:
    """Whole cents from a dollar amount such as 147.5 or "147.50"; anything else is refused."""
    if isinstance(value, bool):
        raise WorkflowError("The confirmed total must be a dollar amount, such as 147.50", 422)
    try:
        amount = Decimal(str(value))
    except ArithmeticError as exc:
        raise WorkflowError("The confirmed total must be a dollar amount, such as 147.50", 422) from exc
    if not amount.is_finite() or amount < 0 or amount != amount.quantize(Decimal("0.01")):
        raise WorkflowError("The confirmed total must be a dollar amount with at most two decimals", 422)
    return int(amount * 100)


def local_text(moment: datetime) -> str:
    local = moment.astimezone(LIMA)
    return f"{local.strftime('%b')} {local.day}, {local.strftime('%H:%M')} local time"


def service_name(source: str) -> str:
    return source.replace("-", " ").capitalize()


def paid_lines(plan: dict[str, Any], carriers: dict[str, Any]) -> list[dict[str, Any]]:
    """The plan's paid carriers and services, with each one's cost when the quotes add up to the plan's."""
    units: dict[str, int] = {}
    arrivals: dict[str, str] = {}
    for allocation in plan["allocations"]:
        source = allocation["source"]
        if source == SHIPMENT_SOURCE or source.endswith("-stock"):
            continue
        units[source] = units.get(source, 0) + allocation["units"]
        arrivals[source] = max(arrivals.get(source, ""), allocation["arrival_eta"])
    costs = {source: carriers.get(source, {}).get("incremental_cost_usd") for source in units}
    priced = all(isinstance(cost, int) for cost in costs.values()) and sum(costs.values()) == plan["incremental_cost_usd"]
    return [
        {
            "service": service_name(source), "units": units[source], "arrival_eta": arrivals[source],
            **({"cost_usd": usd(costs[source] * 100)} if priced else {}),
        }
        for source in sorted(units)
    ]


def breakdown(plan: dict[str, Any]) -> dict[str, int]:
    base = plan["incremental_cost_usd"] * 100
    tax = int((Decimal(base + SERVICE_FEE_CENTS) * TAX_RATE).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return {"base": base, "fee": SERVICE_FEE_CENTS, "tax": tax, "total": base + SERVICE_FEE_CENTS + tax}


class SimulatedPaymentGateway:
    """Stands in for a card processor: it captures every charge and never moves money."""

    method = "Corporate card ending 4242 (simulated)"

    def charge(self, amount_cents: int, idempotency_key: str, description: str) -> dict[str, Any]:
        reference = hashlib.sha256(f"{idempotency_key}:{amount_cents}:{description}".encode()).hexdigest()[:12].upper()
        return {"id": f"PAY-{reference}", "status": "captured", "amount_usd": usd(amount_cents),
                "method": self.method, "simulated": True}


class BookingStore:
    """Quotes and bookings, kept in the same SQLite file as the incidents."""

    def __init__(
        self, db_path: str | Path, service: LogiOpsService, *,
        gateway: SimulatedPaymentGateway | None = None, clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.service = service
        self.gateway = gateway or SimulatedPaymentGateway()
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        with self._connection() as connection:
            for statement in SCHEMA:
                connection.execute(statement)

    def _connection(self) -> ContextManager[sqlite3.Connection]:
        return connect(self.db_path)

    def _plan(self, incident_id: str, plan_id: str | None) -> tuple[dict[str, Any], dict[str, Any]]:
        """(snapshot, plan) for a bookable plan: current, or already executed. Without a plan id, the
        plan a person approved on the current data, or the executed one."""
        snapshot = self.service.get(incident_id)
        executed = {item["plan_id"] for item in snapshot["executions"]}
        if plan_id is None:
            approved = [item["plan_id"] for item in snapshot["approvals"] if item["is_current"]]
            plan_id = next(iter(approved or sorted(executed)), None)
            if plan_id is None:
                raise WorkflowError("No plan is approved yet. Approve a plan in the operator panel, or name the plan to price.", 409)
        plan = next((item for item in snapshot["plans"] if item["id"] == plan_id), None)
        if plan is None:
            raise WorkflowError("Unknown plan for this incident. Investigate it and pick one of its plans.", 404)
        if plan_id not in executed and plan["source_version"] != snapshot["source_version"]:
            raise WorkflowError(f"“{plan['label']}” was calculated on older data. Investigate again and price the new plan.", 409)
        return snapshot, plan

    def _approved(self, snapshot: dict[str, Any], plan: dict[str, Any]) -> bool:
        return any(item["plan_id"] == plan["id"] for item in snapshot["executions"]) or any(
            item["plan_id"] == plan["id"] and item["source_version"] == plan["source_version"] for item in snapshot["approvals"])

    def quote_of(self, quote_id: str) -> dict[str, Any] | None:
        with self._connection() as connection:
            row = connection.execute("SELECT quote_json FROM booking_quotes WHERE id = ?", (quote_id,)).fetchone()
        return None if row is None else json.loads(row[0])

    def booking_for_plan(self, plan_id: str) -> dict[str, Any] | None:
        with self._connection() as connection:
            row = connection.execute("SELECT booking_json FROM bookings WHERE plan_id = ?", (plan_id,)).fetchone()
        return None if row is None else json.loads(row[0])

    def quote(self, incident_id: str, plan_id: str | None, actor: Actor) -> dict[str, Any]:
        """A price for the plan's paid carriers and services; the same open quote while it is valid."""
        snapshot, plan = self._plan(incident_id, plan_id)
        booked = self.booking_for_plan(plan["id"])
        if booked:
            raise WorkflowError(f"“{plan['label']}” is already booked as {booked['number']}. Nothing more to pay.", 409)
        lines = paid_lines(plan, snapshot["state"].get("carriers", {}))
        if not lines or plan["incremental_cost_usd"] <= 0:
            raise WorkflowError(f"“{plan['label']}” uses no paid carrier or service, so there is nothing to book.", 409)
        now = self.clock()
        with self._connection() as connection:
            row = connection.execute(
                "SELECT quote_json FROM booking_quotes WHERE plan_id = ? AND source_version = ? AND expires_at > ? "
                "ORDER BY created_at DESC LIMIT 1", (plan["id"], plan["source_version"], now.isoformat()),
            ).fetchone()
            if row:
                return {**json.loads(row[0]), "approved": self._approved(snapshot, plan)}
            price = breakdown(plan)
            expires = now + timedelta(minutes=QUOTE_MINUTES)
            quote = {
                "quote_id": f"Q-{secrets.token_hex(6)}", "incident_id": incident_id, "plan_id": plan["id"],
                "plan_label": plan["label"], "source_version": plan["source_version"],
                "approved": self._approved(snapshot, plan), "lines": lines,
                "base_usd": usd(price["base"]), "service_fee_usd": usd(price["fee"]), "tax_rate": float(TAX_RATE),
                "tax_label": TAX_LABEL, "tax_usd": usd(price["tax"]), "total_usd": usd(price["total"]), "currency": "USD",
                "payment_method": self.gateway.method, "expires_at": expires.isoformat(),
                "summary": (f"Booking “{plan['label']}”: carriers and services {money(price['base'])}, service fee "
                            f"{money(price['fee'])}, {TAX_LABEL} {money(price['tax'])}, total {money(price['total'])}, "
                            f"charged to the {self.gateway.method.removesuffix(' (simulated)').lower()}. "
                            f"The price holds until {local_text(expires)}."),
                "quoted_by": actor.name,
            }
            connection.execute(
                "INSERT INTO booking_quotes (id, incident_id, plan_id, source_version, quote_json, created_at, expires_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (quote["quote_id"], incident_id, plan["id"], plan["source_version"], json.dumps(quote),
                 now.isoformat(), expires.isoformat()),
            )
        return quote

    def confirm(self, quote_id: str, confirmed_total_usd: Any, idempotency_key: str, actor: Actor) -> dict[str, Any]:
        """Charge the quoted total once and return the booking with its receipt; see the module docstring."""
        if not IDEMPOTENCY_KEY.fullmatch(str(idempotency_key)):
            raise WorkflowError("The idempotency key must be 8 to 100 letters, digits, - or _", 422)
        confirmed = cents_of(confirmed_total_usd)
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = connection.execute(
                "SELECT booking_json, quote_id FROM bookings WHERE idempotency_key = ?", (idempotency_key,)).fetchone()
            if replay:
                if replay[1] != quote_id:
                    raise WorkflowError("This idempotency key already paid for a different quote. Use a new key.", 409)
                return {**json.loads(replay[0]), "replayed": True}
            row = connection.execute("SELECT quote_json FROM booking_quotes WHERE id = ?", (quote_id,)).fetchone()
            if row is None:
                raise WorkflowError("Unknown quote. Ask for a new quote for the approved plan.", 404)
            quote = json.loads(row[0])
            booked = connection.execute("SELECT number FROM bookings WHERE plan_id = ?", (quote["plan_id"],)).fetchone()
            if booked:
                raise WorkflowError(f"“{quote['plan_label']}” is already booked as {booked[0]}. Nothing was charged again.", 409)
            now = self.clock()
            if now >= datetime.fromisoformat(quote["expires_at"]):
                raise WorkflowError("That price expired. Ask for a new quote; nothing was charged.", 409)
            snapshot, plan = self._plan(quote["incident_id"], quote["plan_id"])
            if plan["source_version"] != quote["source_version"]:
                raise WorkflowError("The plan changed since the quote. Ask for a new quote; nothing was charged.", 409)
            if not self._approved(snapshot, plan):
                raise WorkflowError(f"A person must approve “{plan['label']}” in the operator panel before it is booked. "
                                    "Nothing was charged.", 409)
            price = breakdown(plan)
            if price["total"] != cents_of(quote["total_usd"]):
                raise WorkflowError("The price changed since the quote. Ask for a new quote; nothing was charged.", 409)
            if confirmed != price["total"]:
                raise WorkflowError(f"The confirmed total {money(confirmed)} does not match the quoted total "
                                    f"{money(price['total'])}. Nothing was charged.", 409)
            payment = self.gateway.charge(price["total"], idempotency_key, f"{quote['incident_id']} {plan['label']}")
            while True:
                number = "LGO-" + "".join(secrets.choice(NUMBER_ALPHABET) for _ in range(6))
                if not connection.execute("SELECT 1 FROM bookings WHERE number = ?", (number,)).fetchone():
                    break
            booking = {
                "number": number, "status": "confirmed", "incident_id": quote["incident_id"], "plan_id": plan["id"],
                "plan_label": plan["label"], "source_version": plan["source_version"], "quote_id": quote_id,
                "lines": quote["lines"], "base_usd": quote["base_usd"], "service_fee_usd": quote["service_fee_usd"],
                "tax_rate": quote["tax_rate"], "tax_label": quote["tax_label"], "tax_usd": quote["tax_usd"],
                "total_usd": quote["total_usd"],
                "currency": "USD", "payment": payment, "booked_by": actor.name, "booked_at": now.isoformat(),
                "receipt_url": f"/bookings/{number}/receipt",
                "confirmation": (f"Booked “{plan['label']}” for {quote['incident_id']}: {money(price['total'])} charged to "
                                 f"the {payment['method'].removesuffix(' (simulated)').lower()}. Confirmation number "
                                 f"{number}. Delivery is still projected, not confirmed."),
                "simulated": True,
            }
            connection.execute(
                "INSERT INTO bookings (number, quote_id, incident_id, plan_id, idempotency_key, booking_json, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (number, quote_id, quote["incident_id"], plan["id"], idempotency_key, json.dumps(booking), now.isoformat()),
            )
        return booking

    def get(self, number: str) -> dict[str, Any]:
        if not BOOKING_NUMBER.fullmatch(str(number).upper()):
            raise WorkflowError("Booking numbers look like LGO-7K2M9Q.", 404)
        with self._connection() as connection:
            row = connection.execute("SELECT booking_json FROM bookings WHERE number = ?", (str(number).upper(),)).fetchone()
        if row is None:
            raise WorkflowError("No booking has that number.", 404)
        return json.loads(row[0])

    def for_incident(self, incident_id: str) -> list[dict[str, Any]]:
        """The incident's bookings as it is now; a booking from before a date refresh is still found by its number,
        but no longer shown on the fresh incident. A reset deletes the incident's bookings."""
        snapshot = self.service.get(incident_id)
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT booking_json FROM bookings WHERE incident_id = ? ORDER BY created_at", (incident_id,)).fetchall()
        return [item for item in (json.loads(row[0]) for row in rows) if of_current_seed(snapshot, item["plan_id"])]

    def figures(self, incident_id: str) -> dict[str, list[float]]:
        """The dollar amounts of the incident's current quotes and bookings, for the grounding check."""
        snapshot = self.service.get(incident_id)
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT quote_json FROM booking_quotes WHERE incident_id = ? UNION ALL "
                "SELECT booking_json FROM bookings WHERE incident_id = ?", (incident_id, incident_id)).fetchall()
        amounts = set()
        for item in (json.loads(row[0]) for row in rows):
            if of_current_seed(snapshot, item["plan_id"]):
                amounts |= {float(item[key]) for key in ("base_usd", "service_fee_usd", "tax_usd", "total_usd")}
        return {"dollars": sorted(amounts)}

    def clear(self, incident_id: str | None = None) -> None:
        with self._connection() as connection:
            for table in ("bookings", "booking_quotes"):
                if incident_id is None:
                    connection.execute(f"DELETE FROM {table}")
                else:
                    connection.execute(f"DELETE FROM {table} WHERE incident_id = ?", (incident_id,))


def line_amount(line: dict[str, Any]) -> str:
    return f"${line['cost_usd']:,.2f}" if "cost_usd" in line else "included"


def receipt_text(booking: dict[str, Any]) -> str:
    """The receipt as Markdown, for MCP clients and voice hosts."""
    lines = [
        f"# LogiOps receipt {booking['number']}", "",
        f"{booking['plan_label']} · {booking['incident_id']}", "",
        "| Item | Amount |", "|---|---|",
        *(f"| {line['service']}, {line['units']} units | {line_amount(line)} |" for line in booking["lines"]),
        f"| Carriers and services | ${booking['base_usd']:,.2f} |",
        f"| Service fee | ${booking['service_fee_usd']:,.2f} |",
        f"| {booking['tax_label']} | ${booking['tax_usd']:,.2f} |",
        f"| **Total charged** | **${booking['total_usd']:,.2f}** |", "",
        f"Paid with: {booking['payment']['method']} · payment {booking['payment']['id']}",
        f"Booked by {booking['booked_by']} on {local_text(datetime.fromisoformat(booking['booked_at']))}.",
        "Synthetic demo data: no money moved, and delivery is projected, not confirmed.",
    ]
    return "\n".join(lines) + "\n"


def receipt_html(booking: dict[str, Any]) -> str:
    """A printable receipt page; every value is escaped."""
    def cell(value: Any) -> str:
        return html.escape(str(value))

    rows = "".join(
        f"<tr><td>{cell(line['service'])}, {cell(line['units'])} units</td><td>{cell(line_amount(line))}</td></tr>"
        for line in booking["lines"]
    )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Receipt {cell(booking['number'])}</title>
<style>
body {{ margin: 0; padding: 24px 16px; background: #f6fafb; color: #0b2730; font: 15px/1.5 system-ui, sans-serif; }}
main {{ max-width: 560px; margin: 0 auto; padding: 24px; border: 1px solid #c5d9de; border-radius: 12px; background: #fff; }}
h1 {{ margin: 0 0 4px; font-size: 20px; }}
p {{ margin: 4px 0; color: #33515a; }}
table {{ width: 100%; margin: 16px 0; border-collapse: collapse; }}
td {{ padding: 6px 0; border-bottom: 1px solid #e3eef1; }}
td:last-child {{ text-align: right; white-space: nowrap; }}
tr.total td {{ border-bottom: 0; font-weight: 800; font-size: 17px; }}
small {{ color: #4a6670; }}
@media print {{ body {{ background: #fff; padding: 0; }} main {{ border: 0; }} }}
</style></head>
<body><main>
<h1>Receipt {cell(booking['number'])}</h1>
<p>{cell(booking['plan_label'])} · {cell(booking['incident_id'])}</p>
<table aria-label="Price breakdown">
{rows}
<tr><td>Carriers and services</td><td>${booking['base_usd']:,.2f}</td></tr>
<tr><td>Service fee</td><td>${booking['service_fee_usd']:,.2f}</td></tr>
<tr><td>{cell(booking['tax_label'])}</td><td>${booking['tax_usd']:,.2f}</td></tr>
<tr class="total"><td>Total charged</td><td>${booking['total_usd']:,.2f}</td></tr>
</table>
<p>Paid with {cell(booking['payment']['method'])} · payment {cell(booking['payment']['id'])}</p>
<p>Booked by {cell(booking['booked_by'])} on {cell(local_text(datetime.fromisoformat(booking['booked_at'])))}</p>
<p><small>Synthetic demo data: no money moved, and delivery is projected, not confirmed.</small></p>
</main></body></html>
"""
