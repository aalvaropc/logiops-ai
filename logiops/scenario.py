"""Versioned, synthetic incident data and deterministic plan calculations.

Four synthetic incidents, each self-contained (its own orders, stock and carrier
quotes), so working one never changes another. The plan options of each incident
are data (PLAYBOOKS); one greedy fill turns them into plans from the current state,
so a stock or capacity change always recalculates them.
"""

from __future__ import annotations

import json
import re
import threading
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
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


BUILTIN_DEFINITIONS: dict[str, dict[str, Any]] = {
    "SHIP-421": {
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
    },
    "SHIP-433": {
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
    },
    "SHIP-452": {
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
    },
    "SHIP-460": {
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
    },
}


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


INCIDENTS: dict[str, dict[str, Any]] = dict(BUILTIN_DEFINITIONS)
BUILTIN_KINDS = frozenset(KIND_LABELS)
INCIDENT_ID_PATTERN = re.compile(r"SHIP-\d+")
ORDER_ID_PATTERN = re.compile(r"ORD-\d+[A-Z]?")
NAME_PATTERN = re.compile(r"[a-z][a-z0-9-]*")
KIND_PATTERN = re.compile(r"[a-z][a-z_-]*")
PACK_VERSION = 1
FIRST_YEAR, LAST_YEAR = 2000, 2099
REGISTRY_LOCK = threading.Lock()


class ScenarioPackError(ValueError):
    """A scenario pack that cannot be registered; `errors` lists every problem with its path."""

    def __init__(self, errors: list[dict[str, str]]) -> None:
        self.errors = errors
        super().__init__("; ".join(f"{item['incident']} {item['path']}: {item['message']}" for item in errors))


def incident_ids() -> tuple[str, ...]:
    """Every registered incident, the built-ins first, read at call time."""
    return tuple(INCIDENTS)


def builtin_incidents() -> list[dict[str, Any]]:
    """The built-in incidents in pack form, as a template for a pack of your own."""
    return [{"id": incident_id, **deepcopy(definition), "options": deepcopy(PLAYBOOKS[incident_id])}
            for incident_id, definition in BUILTIN_DEFINITIONS.items()]


def reset_registry() -> None:
    """Forget every registered pack; the built-ins stay."""
    with REGISTRY_LOCK:
        for incident_id in [item for item in INCIDENTS if item not in BUILTIN_DEFINITIONS]:
            del INCIDENTS[incident_id]
            PLAYBOOKS.pop(incident_id, None)
        for kind in [item for item in KIND_LABELS if item not in BUILTIN_KINDS]:
            del KIND_LABELS[kind]


def _timestamp(value: Any) -> bool:
    """An ISO 8601 time with the -05:00 offset in a year the scenario clock can move whole days from and to."""
    if not isinstance(value, str) or not ISO_TIMESTAMP.match(value) or not value.endswith("-05:00"):
        return False
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        return False
    return moment.utcoffset() == LIMA.utcoffset(None) and FIRST_YEAR <= moment.year <= LAST_YEAR


def _problems(definition: Any, incidents: dict[str, dict[str, Any]], kind_labels: dict[str, str]) -> list[dict[str, str]]:
    found: list[dict[str, str]] = []
    incident = str(definition.get("id", "?")) if isinstance(definition, dict) else "?"

    def bad(path: str, message: str) -> None:
        found.append({"incident": incident, "path": path, "message": message})

    if not isinstance(definition, dict):
        return [{"incident": incident, "path": "", "message": "an incident must be an object"}]
    incident_id = definition.get("id")
    if not isinstance(incident_id, str) or not INCIDENT_ID_PATTERN.fullmatch(incident_id):
        bad("id", "an incident id looks like SHIP-470")
    elif incident_id in incidents:
        bad("id", f"{incident_id} is already registered")
    kind = definition.get("kind")
    if not isinstance(kind, str) or not KIND_PATTERN.fullmatch(kind):
        bad("kind", "a kind is lowercase letters, such as port_strike")
    elif kind not in kind_labels and (not isinstance(definition.get("kind_label"), str) or not definition["kind_label"].strip()):
        bad("kind_label", f"a new kind ({kind}) needs a kind_label")
    if not isinstance(definition.get("title"), str) or not definition["title"].strip():
        bad("title", "a title is required")
    shipment = definition.get("shipment")
    if not isinstance(shipment, dict):
        bad("shipment", "a shipment object is required")
        shipment = {}
    for field in ("origin", "destination", "sku", "disruption"):
        if not isinstance(shipment.get(field), str) or not shipment[field].strip():
            bad(f"shipment.{field}", f"{field} is required")
    if not isinstance(shipment.get("units_on_delayed_route"), int) or isinstance(shipment.get("units_on_delayed_route"), bool) or shipment["units_on_delayed_route"] <= 0:
        bad("shipment.units_on_delayed_route", "units_on_delayed_route must be a positive whole number")
    for field in ("original_eta", "delayed_eta"):
        if not _timestamp(shipment.get(field)):
            bad(f"shipment.{field}", f"{field} must be an ISO 8601 time with the -05:00 offset")
    orders = definition.get("orders")
    if not isinstance(orders, list) or not orders:
        bad("orders", "at least one order is required")
        orders = []
    seen_orders: set[str] = set()
    registered_orders = {order["id"] for item in incidents.values() for order in item["orders"]}
    for index, order in enumerate(orders):
        path = f"orders[{index}]"
        if not isinstance(order, dict):
            bad(path, "an order must be an object")
            continue
        order_id = order.get("id")
        if not isinstance(order_id, str) or not ORDER_ID_PATTERN.fullmatch(order_id):
            bad(f"{path}.id", "an order id looks like ORD-470 or ORD-470A")
        elif order_id in seen_orders or order_id in registered_orders:
            bad(f"{path}.id", f"{order_id} is already used")
        else:
            seen_orders.add(order_id)
        if order.get("sku") != shipment.get("sku"):
            bad(f"{path}.sku", "an order's sku must match the shipment's")
        if not isinstance(order.get("quantity"), int) or isinstance(order.get("quantity"), bool) or order["quantity"] <= 0:
            bad(f"{path}.quantity", "quantity must be a positive whole number")
        if not isinstance(order.get("customer"), str) or not order["customer"].strip():
            bad(f"{path}.customer", "customer is required")
        if not isinstance(order.get("priority"), str) or order["priority"] not in PRIORITY_RANK:
            bad(f"{path}.priority", "priority is critical or standard")
        for field in ("due_eta", "placed_at"):
            if not _timestamp(order.get(field)):
                bad(f"{path}.{field}", f"{field} must be an ISO 8601 time with the -05:00 offset")
    inventory = definition.get("inventory", {})
    if not isinstance(inventory, dict):
        bad("inventory", "inventory maps one warehouse to its stock")
        inventory = {}
    if len(inventory) > 1:
        bad("inventory", "an incident has at most one warehouse")
    for warehouse, stock in inventory.items():
        path = f"inventory.{warehouse}"
        if not NAME_PATTERN.fullmatch(str(warehouse)):
            bad(path, "a warehouse is a lowercase city name, such as piura")
        if not isinstance(stock, dict):
            bad(path, "stock is an object with sku, available and ready_at")
            continue
        if stock.get("sku") != shipment.get("sku"):
            bad(f"{path}.sku", "stock sku must match the shipment's")
        if not isinstance(stock.get("available"), int) or isinstance(stock.get("available"), bool) or stock["available"] < 0:
            bad(f"{path}.available", "available must be a whole number of units")
        if not _timestamp(stock.get("ready_at")):
            bad(f"{path}.ready_at", "ready_at must be an ISO 8601 time with the -05:00 offset")
    carriers = definition.get("carriers", {})
    if not isinstance(carriers, dict):
        bad("carriers", "carriers maps each carrier or service to its quote")
        carriers = {}
    for name, quote in carriers.items():
        path = f"carriers.{name}"
        if not NAME_PATTERN.fullmatch(str(name)) or str(name).endswith("-stock") or name == SHIPMENT_SOURCE:
            bad(path, "a carrier name is lowercase, such as refrigerated-truck, and not a stock source")
        if not isinstance(quote, dict):
            bad(path, "a quote is an object with capacity, arrival_eta and incremental_cost_usd")
            continue
        if not isinstance(quote.get("capacity"), int) or isinstance(quote.get("capacity"), bool) or quote["capacity"] <= 0:
            bad(f"{path}.capacity", "capacity must be a positive whole number")
        if not _timestamp(quote.get("arrival_eta")):
            bad(f"{path}.arrival_eta", "arrival_eta must be an ISO 8601 time with the -05:00 offset")
        if not isinstance(quote.get("incremental_cost_usd"), int) or isinstance(quote.get("incremental_cost_usd"), bool) or quote["incremental_cost_usd"] < 0:
            bad(f"{path}.incremental_cost_usd", "incremental_cost_usd must be a whole number of dollars")
    sources = {SHIPMENT_SOURCE, *(f"{warehouse}-stock" for warehouse in inventory), *carriers}
    options = definition.get("options")
    if not isinstance(options, list) or not options:
        bad("options", "at least one plan option is required")
        options = []
    seen_kinds: set[str] = set()
    for index, option in enumerate(options):
        path = f"options[{index}]"
        if not isinstance(option, dict):
            bad(path, "an option must be an object")
            continue
        option_kind = option.get("kind")
        if not isinstance(option_kind, str) or not re.fullmatch(r"[a-z][a-z-]*", option_kind):
            bad(f"{path}.kind", "an option kind is lowercase letters and dashes, such as priority-air")
        elif option_kind in seen_kinds:
            bad(f"{path}.kind", f"{option_kind} is repeated")
        else:
            seen_kinds.add(option_kind)
        if not isinstance(option.get("label"), str) or not option["label"].strip():
            bad(f"{path}.label", "a label is required")
        option_sources = option.get("sources")
        groups = option_sources.values() if isinstance(option_sources, dict) else [option_sources]
        if isinstance(option_sources, dict) and set(option_sources) != set(PRIORITY_RANK):
            bad(f"{path}.sources", "grouped sources need exactly critical and standard")
        for group in groups:
            if not isinstance(group, list) or not group:
                bad(f"{path}.sources", "sources is a non-empty list, or an object with critical and standard lists")
                continue
            for source in group:
                if not isinstance(source, str) or source not in sources:
                    bad(f"{path}.sources", f"unknown source {source!r}; use delayed-shipment, a <warehouse>-stock or a carrier")
        if "use_all" in option and not isinstance(option["use_all"], bool):
            bad(f"{path}.use_all", "use_all is true or false")
        if "sequence" in option and option["sequence"] not in ("priority", "placed"):
            bad(f"{path}.sequence", "sequence is priority or placed")
    for text in (incident_id, *seen_orders):
        if isinstance(text, str) and (":" in text or "." in text):
            bad("id", "ids cannot contain ':' or '.'")
    return found


def register_incident(definition: dict[str, Any]) -> str:
    """Validate one incident in pack form and add it to the registry; returns its id."""
    return register_pack({"version": PACK_VERSION, "incidents": [definition]})[0]


def register_pack(pack: Any) -> list[str]:
    """Register every incident of a pack {"version": 1, "incidents": [...]}; nothing is kept if any fails.
    One registration at a time runs from the snapshot to the commit, so two packs cannot both claim an id."""
    if not isinstance(pack, dict) or pack.get("version") != PACK_VERSION or not isinstance(pack.get("incidents"), list):
        raise ScenarioPackError([{"incident": "?", "path": "", "message": f'a pack is {{"version": {PACK_VERSION}, "incidents": [...]}}'}])
    problems: list[dict[str, str]] = []
    registered: list[str] = []
    with REGISTRY_LOCK:
        incidents, playbooks, kind_labels = dict(INCIDENTS), dict(PLAYBOOKS), dict(KIND_LABELS)
        for definition in pack["incidents"]:
            errors = _problems(definition, incidents, kind_labels)
            if errors:
                problems.extend(errors)
                continue
            incident_id = definition["id"]
            stored = {key: deepcopy(value) for key, value in definition.items() if key not in ("id", "options", "kind_label")}
            stored.setdefault("inventory", {})
            stored.setdefault("carriers", {})
            incidents[incident_id] = stored
            playbooks[incident_id] = deepcopy(definition["options"])
            if definition["kind"] not in kind_labels:
                kind_labels[definition["kind"]] = definition["kind_label"]
            registered.append(incident_id)
        if problems:
            raise ScenarioPackError(problems)
        # Readers take no lock, so an incident is added last: whoever sees it also finds its playbook and kind label.
        PLAYBOOKS.update(playbooks)
        KIND_LABELS.update(kind_labels)
        INCIDENTS.update(incidents)
    return registered


def load_scenario_pack(path: str | Path) -> list[str]:
    """Register the incidents of a JSON pack file; returns their ids."""
    try:
        pack = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ScenarioPackError([{"incident": "?", "path": str(path), "message": f"cannot read the pack: {exc}"}]) from exc
    return register_pack(pack)


def _seed(incident_id: str) -> dict[str, Any]:
    return deepcopy(INCIDENTS[incident_id])


def _shifted(value: Any, days: int) -> Any:
    """The seed with every timestamp in it moved by whole days (times of day and offsets kept).
    Any timestamp moves, so a field added later can never be left behind; text that only starts like one stays."""
    if isinstance(value, dict):
        return {key: _shifted(item, days) for key, item in value.items()}
    if isinstance(value, list):
        return [_shifted(item, days) for item in value]
    if _timestamp(value):
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


def known_figures(state: dict[str, Any]) -> dict[str, list[Any]]:
    """What an answer may quote besides the plans' own figures: dollar amounts, hour counts, unit
    counts, the ids of the incident and its orders, and the timestamps in its data."""
    shipment = state["shipment"]
    orders = state["orders"]
    hours = {delay_hours(shipment["delayed_eta"], shipment["original_eta"])}
    hours |= {delay_hours(shipment["delayed_eta"], order["due_eta"]) for order in orders}
    units = {shipment["units_on_delayed_route"], sum(order["quantity"] for order in orders), critical_units_at_risk(state)}
    units |= {order["quantity"] for order in orders}
    units |= {stock["available"] for stock in state["inventory"].values()}
    units |= {quote["capacity"] for quote in state["carriers"].values()}
    times = {shipment["original_eta"], shipment["delayed_eta"]}
    times |= {order[key] for order in orders for key in ("due_eta", "placed_at")}
    times |= {stock["ready_at"] for stock in state["inventory"].values()}
    times |= {quote["arrival_eta"] for quote in state["carriers"].values()}
    return {
        "dollars": sorted({quote["incremental_cost_usd"] for quote in state["carriers"].values()}),
        "hours": sorted(hours),
        "units": sorted(units),
        "ids": [state["incident_id"], *(order["id"] for order in orders)],
        "times": sorted(times, key=_at),
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
