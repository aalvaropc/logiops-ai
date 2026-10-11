"""Versioned, synthetic incident data and deterministic plan calculations.

Four synthetic incidents, each self-contained (its own orders, stock and carrier
quotes), so working one never changes another. The plan options of each incident
are data (PLAYBOOKS); one greedy fill turns them into plans from the current state,
so a stock or capacity change always recalculates them.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable
from uuid import uuid4


INCIDENT_ID = "SHIP-421"
INCIDENT_IDS = ("SHIP-421", "SHIP-433", "SHIP-452", "SHIP-460")
KIND_LABELS = {
    "delay": "Delayed in transit",
    "carrier_outage": "Carrier outage",
    "customs_hold": "Customs hold",
    "stock_conflict": "Orders competing for stock",
}
PRIORITY_RANK = {"critical": 0, "standard": 1}
SHIPMENT_SOURCE = "delayed-shipment"
LIMA = timezone(timedelta(hours=-5))
SEED_DAY = date(2026, 10, 12)
ISO_TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}")
ANCHOR_SETTING = re.compile(r"\d{4}-\d{2}-\d{2}")


def _seed(incident_id: str) -> dict[str, Any]:
    if incident_id == "SHIP-421":
        return {
            "kind": "delay",
            "title": "Laptop shipment delayed in transit",
            "shipment": {
                "origin": "Lima", "destination": "Arequipa", "sku": "LAPTOP-01", "units_on_delayed_route": 20,
                "original_eta": "2026-10-12T14:00:00-05:00", "delayed_eta": "2026-10-13T02:00:00-05:00",
                "disruption": "The truck is held up on the highway and the carrier reports a later arrival.",
            },
            "orders": [{
                "id": "ORD-421", "sku": "LAPTOP-01", "quantity": 20, "customer": "Arequipa electronics store",
                "priority": "standard", "due_eta": "2026-10-12T14:00:00-05:00", "placed_at": "2026-10-05T09:00:00-05:00",
            }],
            "inventory": {"arequipa": {"sku": "LAPTOP-01", "available": 12, "ready_at": "2026-10-12T10:00:00-05:00"}},
            "carriers": {
                "economy-reroute": {"capacity": 20, "arrival_eta": "2026-10-12T17:00:00-05:00", "incremental_cost_usd": 80},
                "express": {"capacity": 8, "arrival_eta": "2026-10-12T13:00:00-05:00", "incremental_cost_usd": 120},
            },
        }
    if incident_id == "SHIP-433":
        return {
            "kind": "carrier_outage",
            "title": "Carrier suspended departures: tablets for Cusco",
            "shipment": {
                "origin": "Lima", "destination": "Cusco", "sku": "TABLET-03", "units_on_delayed_route": 30,
                "original_eta": "2026-10-13T12:00:00-05:00", "delayed_eta": "2026-10-14T12:00:00-05:00",
                "disruption": "The booked carrier suspended departures from Lima; the restart time is the carrier's own estimate.",
            },
            "orders": [
                {
                    "id": "ORD-433A", "sku": "TABLET-03", "quantity": 12, "customer": "Cusco regional hospital",
                    "priority": "critical", "due_eta": "2026-10-13T12:00:00-05:00", "placed_at": "2026-10-06T10:00:00-05:00",
                },
                {
                    "id": "ORD-433B", "sku": "TABLET-03", "quantity": 18, "customer": "Cusco electronics store",
                    "priority": "standard", "due_eta": "2026-10-13T12:00:00-05:00", "placed_at": "2026-10-05T15:00:00-05:00",
                },
            ],
            "inventory": {},
            "carriers": {
                "ground-reroute": {"capacity": 30, "arrival_eta": "2026-10-13T20:00:00-05:00", "incremental_cost_usd": 150},
                "air-freight": {"capacity": 12, "arrival_eta": "2026-10-12T20:00:00-05:00", "incremental_cost_usd": 240},
            },
        }
    if incident_id == "SHIP-452":
        return {
            "kind": "customs_hold",
            "title": "Import held at customs: routers for Lima",
            "shipment": {
                "origin": "Callao", "destination": "Lima", "sku": "ROUTER-05", "units_on_delayed_route": 40,
                "original_eta": "2026-10-12T16:00:00-05:00", "delayed_eta": "2026-10-15T16:00:00-05:00",
                "disruption": "Customs flagged a documentation discrepancy; the standard review sets the release time.",
            },
            "orders": [{
                "id": "ORD-452", "sku": "ROUTER-05", "quantity": 40, "customer": "Lima telecom distributor",
                "priority": "standard", "due_eta": "2026-10-12T16:00:00-05:00", "placed_at": "2026-10-01T09:00:00-05:00",
            }],
            "inventory": {"lima": {"sku": "ROUTER-05", "available": 25, "ready_at": "2026-10-12T12:00:00-05:00"}},
            "carriers": {
                "expedited-clearance": {"capacity": 40, "arrival_eta": "2026-10-13T10:00:00-05:00", "incremental_cost_usd": 350},
            },
        }
    if incident_id == "SHIP-460":
        return {
            "kind": "stock_conflict",
            "title": "Replenishment delayed: two orders compete for laptops in Trujillo",
            "shipment": {
                "origin": "Lima", "destination": "Trujillo", "sku": "LAPTOP-02", "units_on_delayed_route": 30,
                "original_eta": "2026-10-12T18:00:00-05:00", "delayed_eta": "2026-10-14T18:00:00-05:00",
                "disruption": "The replenishment truck to the Trujillo warehouse is delayed, so the stock on hand cannot cover both orders on time.",
            },
            "orders": [
                {
                    "id": "ORD-460", "sku": "LAPTOP-02", "quantity": 20, "customer": "Trujillo regional hospital",
                    "priority": "critical", "due_eta": "2026-10-13T12:00:00-05:00", "placed_at": "2026-10-06T11:00:00-05:00",
                },
                {
                    "id": "ORD-461", "sku": "LAPTOP-02", "quantity": 25, "customer": "Trujillo school district",
                    "priority": "standard", "due_eta": "2026-10-14T12:00:00-05:00", "placed_at": "2026-10-05T08:00:00-05:00",
                },
            ],
            "inventory": {"trujillo": {"sku": "LAPTOP-02", "available": 30, "ready_at": "2026-10-13T08:00:00-05:00"}},
            "carriers": {
                "express-transfer": {"capacity": 15, "arrival_eta": "2026-10-13T20:00:00-05:00", "incremental_cost_usd": 300},
            },
        }
    raise KeyError(incident_id)


PLAYBOOKS: dict[str, list[dict[str, Any]]] = {
    "SHIP-421": [
        {"kind": "wait", "label": "Keep the delayed shipment", "sources": [SHIPMENT_SOURCE]},
        {"kind": "reroute", "label": "Move the full order to an alternative carrier", "sources": ["economy-reroute"]},
        {"kind": "local-stock", "label": "Fulfill the whole order from local stock", "sources": ["arequipa-stock"]},
        {"kind": "split-express", "label": "Fulfill local stock and send the rest express",
         "sources": ["arequipa-stock", "express"], "use_all": True},
    ],
    "SHIP-433": [
        {"kind": "wait", "label": "Wait for the booked carrier to restart", "sources": [SHIPMENT_SOURCE]},
        {"kind": "reroute", "label": "Rebook both orders on an alternative ground carrier", "sources": ["ground-reroute"]},
        {"kind": "priority-air", "label": "Fly the hospital order; the store order waits for the carrier",
         "sources": {"critical": ["air-freight"], "standard": [SHIPMENT_SOURCE]}, "use_all": True},
        {"kind": "priority-air-ground", "label": "Fly the hospital order; rebook the store order on ground",
         "sources": {"critical": ["air-freight"], "standard": ["ground-reroute"]}, "use_all": True},
    ],
    "SHIP-452": [
        {"kind": "wait", "label": "Wait for the standard customs review", "sources": [SHIPMENT_SOURCE]},
        {"kind": "expedite", "label": "Pay a broker to expedite clearance", "sources": ["expedited-clearance"]},
        {"kind": "local-stock", "label": "Fulfill the whole order from Lima stock", "sources": ["lima-stock"]},
        {"kind": "split-wait", "label": "Ship Lima stock now; the rest after the standard review",
         "sources": ["lima-stock", SHIPMENT_SOURCE], "use_all": True},
        {"kind": "split-expedite", "label": "Ship Lima stock now; expedite clearance for the rest",
         "sources": ["lima-stock", "expedited-clearance"], "use_all": True},
    ],
    "SHIP-460": [
        {"kind": "priority-first", "label": "Serve the hospital first; the school's shortfall waits for the replenishment",
         "sources": ["trujillo-stock", SHIPMENT_SOURCE], "use_all": True},
        {"kind": "first-come", "label": "Serve orders as placed (school first); the hospital's shortfall waits",
         "sequence": "placed", "sources": ["trujillo-stock", SHIPMENT_SOURCE], "use_all": True},
        {"kind": "express-transfer", "label": "Serve the hospital first; cover the school's shortfall by express transfer",
         "sources": ["trujillo-stock", "express-transfer"], "use_all": True},
        {"kind": "local-stock", "label": "Fulfill both orders from Trujillo stock", "sources": ["trujillo-stock"]},
    ],
}


def _shifted(value: Any, days: int) -> Any:
    """The seed with every timestamp in it moved by whole days (times of day and offsets kept).
    Any ISO timestamp moves, so a field added later can never be left behind."""
    if isinstance(value, dict):
        return {key: _shifted(item, days) for key, item in value.items()}
    if isinstance(value, list):
        return [_shifted(item, days) for item in value]
    if isinstance(value, str) and ISO_TIMESTAMP.match(value):
        return (datetime.fromisoformat(value) + timedelta(days=days)).isoformat()
    return value


def scenario_clock(
    setting: str | None, today: Callable[[], date] | None = None,
) -> Callable[[], date | None]:
    """Read LOGIOPS_SCENARIO_ANCHOR once and return the scenario's anchor day for each seed:
    "relative" (the default, also when blank) is tomorrow in Lima, "fixed" keeps the seed's own
    dates (None), and a YYYY-MM-DD day between 2000 and 2099 pins it."""
    value = (setting or "").strip().lower() or "relative"
    today = today or (lambda: datetime.now(LIMA).date())
    if value == "fixed":
        return lambda: None
    if value == "relative":
        return lambda: today() + timedelta(days=1)
    try:
        pinned = date.fromisoformat(value) if ANCHOR_SETTING.fullmatch(value) else None
    except ValueError:
        pinned = None
    if pinned is None or not 2000 <= pinned.year <= 2099:
        raise ValueError("LOGIOPS_SCENARIO_ANCHOR must be relative, fixed, or a YYYY-MM-DD day between 2000 and 2099")
    return lambda: pinned


def seed_state(incident_id: str = INCIDENT_ID, day: date | None = None) -> dict[str, Any]:
    seed = _seed(incident_id)
    if day is not None and day != SEED_DAY:
        seed = _shifted(seed, (day - SEED_DAY).days)
    anchor = day or SEED_DAY
    shipment = {"id": incident_id, **seed["shipment"]}
    orders = [{**order, "shipment_id": incident_id} for order in seed["orders"]]
    return {
        "incident_id": incident_id,
        "scenario_run_id": str(uuid4()),
        "scenario_day": anchor.isoformat(),
        "kind": seed["kind"],
        "title": seed["title"],
        "simulated": True,
        "status": "detected",
        "shipment": shipment,
        "orders": orders,
        "inventory": seed["inventory"],
        "carriers": seed["carriers"],
        "fulfillments": [],
        "notifications": [],
        "selected_plan_id": None,
    }


def _at(value: str) -> datetime:
    return datetime.fromisoformat(value)


def delay_hours(arrival: str, original_eta: str) -> int:
    seconds = (_at(arrival) - _at(original_eta)).total_seconds()
    return max(0, int(seconds // 3600 + (seconds % 3600 > 0)))


def local_warehouse(state: dict[str, Any]) -> str | None:
    """The incident's warehouse, which the demo's stock control adjusts; None if it has none."""
    return next(iter(state["inventory"]), None)


def available_units(state: dict[str, Any]) -> dict[str, tuple[int, str]]:
    """Every allocation source of the incident: units it can supply and when they arrive."""
    pool: dict[str, tuple[int, str]] = {
        SHIPMENT_SOURCE: (state["shipment"]["units_on_delayed_route"], state["shipment"]["delayed_eta"]),
    }
    for warehouse, stock in state["inventory"].items():
        pool[f"{warehouse}-stock"] = (stock["available"], stock["ready_at"])
    for carrier, quote in state["carriers"].items():
        pool[carrier] = (quote["capacity"], quote["arrival_eta"])
    return pool


def _served_in(orders: list[dict[str, Any]], sequence: str) -> list[dict[str, Any]]:
    if sequence == "placed":
        return sorted(orders, key=lambda order: (_at(order["placed_at"]), order["id"]))
    return sorted(orders, key=lambda order: (
        PRIORITY_RANK[order["priority"]], _at(order["due_eta"]), _at(order["placed_at"]), order["id"]))


def _sources_for(option: dict[str, Any], order: dict[str, Any]) -> list[str]:
    sources = option["sources"]
    return sources.get(order["priority"], []) if isinstance(sources, dict) else sources


def _fill(state: dict[str, Any], option: dict[str, Any], pool: dict[str, tuple[int, str]]) -> list[dict[str, Any]] | None:
    """Allocate every order from the option's sources, or None if the option is not feasible."""
    remaining = {source: units for source, (units, _arrival) in pool.items()}
    allocations: list[dict[str, Any]] = []
    for order in _served_in(state["orders"], option.get("sequence", "priority")):
        need = order["quantity"]
        for source in _sources_for(option, order):
            take = min(need, remaining.get(source, 0))
            if take > 0:
                allocations.append({"order_id": order["id"], "source": source, "units": take, "arrival_eta": pool[source][1]})
                remaining[source] -= take
                need -= take
        if need:
            return None
    listed = option["sources"].values() if isinstance(option["sources"], dict) else [option["sources"]]
    if option.get("use_all") and {item["source"] for item in allocations} != {s for group in listed for s in group}:
        return None
    return allocations


def build_plans(state: dict[str, Any], source_version: int) -> list[dict[str, Any]]:
    """Compute all feasible plans from the current operational snapshot, not canned results."""
    pool = available_units(state)
    plans: list[dict[str, Any]] = []
    for option in PLAYBOOKS[state["incident_id"]]:
        allocations = _fill(state, option, pool)
        if allocations is None:
            continue
        orders = []
        for order in state["orders"]:
            mine = [item for item in allocations if item["order_id"] == order["id"]]
            arrival = max((item["arrival_eta"] for item in mine), key=_at)
            orders.append({
                "order_id": order["id"],
                "customer": order["customer"],
                "priority": order["priority"],
                "quantity": order["quantity"],
                "due_eta": order["due_eta"],
                "arrival_eta": arrival,
                "delay_hours": delay_hours(arrival, order["due_eta"]),
                "late_units": sum(item["units"] for item in mine if _at(item["arrival_eta"]) > _at(order["due_eta"])),
            })
        used = {item["source"] for item in allocations}
        plans.append({
            "id": f"{state['incident_id']}:{state['scenario_run_id']}:{option['kind']}:v{source_version}",
            "source_version": source_version,
            "kind": option["kind"],
            "label": option["label"],
            "allocations": allocations,
            "orders": orders,
            "incremental_cost_usd": sum(quote["incremental_cost_usd"] for name, quote in state["carriers"].items() if name in used),
            "projected_completion_eta": max((item["arrival_eta"] for item in allocations), key=_at),
            "projected_customer_delay_hours": max(order["delay_hours"] for order in orders),
            "late_units": sum(order["late_units"] for order in orders),
            "delivery_status": "projected",
        })
    return plans


def rank_key(plan: dict[str, Any]) -> tuple[int, int, int, int]:
    """Critical orders first, then the worst delay, then late units, then cost."""
    critical = [order["delay_hours"] for order in plan.get("orders", []) if order["priority"] == "critical"]
    return (max(critical, default=0), plan["projected_customer_delay_hours"],
            plan.get("late_units", 0), plan["incremental_cost_usd"])


def best_plan(plans: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The default recommendation; on a tie, the option listed first."""
    return min(plans, key=rank_key) if plans else None


def known_figures(state: dict[str, Any]) -> dict[str, list[int]]:
    """Dollar amounts and hour counts an answer may quote besides the plans' own."""
    shipment = state["shipment"]
    hours = {delay_hours(shipment["delayed_eta"], shipment["original_eta"])}
    hours |= {delay_hours(shipment["delayed_eta"], order["due_eta"]) for order in state["orders"]}
    return {
        "dollars": sorted({quote["incremental_cost_usd"] for quote in state["carriers"].values()}),
        "hours": sorted(hours),
    }


def critical_units_at_risk(state: dict[str, Any]) -> int:
    """Units of critical orders that nothing already on hand delivers by their due time: local
    stock ready in time, then the delayed shipment, critical orders served first. Carrier options
    do not count, since they need a decision and cost money."""
    remaining = {f"{warehouse}-stock": [stock["available"], stock["ready_at"]] for warehouse, stock in state["inventory"].items()}
    remaining[SHIPMENT_SOURCE] = [state["shipment"]["units_on_delayed_route"], state["shipment"]["delayed_eta"]]
    at_risk = 0
    for order in _served_in([order for order in state["orders"] if order["priority"] == "critical"], "priority"):
        need = order["quantity"]
        for source in remaining.values():
            if need and _at(source[1]) <= _at(order["due_eta"]):
                take = min(need, source[0])
                source[0] -= take
                need -= take
        at_risk += need
    return at_risk


def incident_summary(state: dict[str, Any], version: int) -> dict[str, Any]:
    shipment = state["shipment"]
    orders = state["orders"]
    return {
        "incident_id": state["incident_id"],
        "kind": state["kind"],
        "kind_label": KIND_LABELS[state["kind"]],
        "title": state["title"],
        "simulated": state["simulated"],
        "status": state["status"],
        "source_version": version,
        "priority": "critical" if any(order["priority"] == "critical" for order in orders) else "standard",
        "due_eta": min((order["due_eta"] for order in orders), key=_at),
        "route": f"{shipment['origin']} → {shipment['destination']}",
        "disruption": shipment["disruption"],
        "units": sum(order["quantity"] for order in orders),
        "delay_hours": delay_hours(shipment["delayed_eta"], shipment["original_eta"]),
        "critical_units_at_risk": 0 if state["status"] == "verified" else critical_units_at_risk(state),
        "orders": [
            {key: order[key] for key in ("id", "customer", "priority", "quantity", "due_eta")} for order in orders
        ],
        "warehouse_id": local_warehouse(state),
        "selected_plan_id": state["selected_plan_id"],
    }


def inbox_key(summary: dict[str, Any]) -> tuple[bool, int, int, datetime, str]:
    """Open incidents first, then the most critical units at risk, then critical first, then the earliest due."""
    return (summary["status"] == "verified", -summary["critical_units_at_risk"],
            PRIORITY_RANK[summary["priority"]], _at(summary["due_eta"]), summary["incident_id"])
