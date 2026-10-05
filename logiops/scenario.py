"""Versioned, synthetic SHIP-421 data and deterministic plan calculations."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4


INCIDENT_ID = "SHIP-421"
SKU = "LAPTOP-01"
QUANTITY = 20


def seed_state() -> dict[str, Any]:
    return {
        "incident_id": INCIDENT_ID,
        "scenario_run_id": str(uuid4()),
        "status": "detected",
        "shipment": {
            "id": INCIDENT_ID,
            "origin": "Lima",
            "destination": "Arequipa",
            "sku": SKU,
            "units_on_delayed_route": QUANTITY,
            "original_eta": "2026-10-12T14:00:00-05:00",
            "delayed_eta": "2026-10-13T02:00:00-05:00",
        },
        "order": {"id": "ORD-421", "shipment_id": INCIDENT_ID, "sku": SKU, "quantity": QUANTITY},
        "inventory": {
            "arequipa": {"sku": SKU, "available": 12, "ready_at": "2026-10-12T10:00:00-05:00"}
        },
        "carriers": {
            "economy-reroute": {
                "capacity": 20,
                "arrival_eta": "2026-10-12T17:00:00-05:00",
                "incremental_cost_usd": 80,
            },
            "express": {
                "capacity": 8,
                "arrival_eta": "2026-10-12T13:00:00-05:00",
                "incremental_cost_usd": 120,
            },
        },
        "fulfillments": [],
        "notifications": [],
        "selected_plan_id": None,
    }


def delay_hours(arrival: str, original_eta: str) -> int:
    seconds = (datetime.fromisoformat(arrival) - datetime.fromisoformat(original_eta)).total_seconds()
    return max(0, int(seconds // 3600 + (seconds % 3600 > 0)))


def build_plans(state: dict[str, Any], source_version: int) -> list[dict[str, Any]]:
    """Compute all plans from the current operational snapshot, not canned results."""
    shipment = state["shipment"]
    order = state["order"]
    inventory = state["inventory"]["arequipa"]
    economy = state["carriers"]["economy-reroute"]
    express = state["carriers"]["express"]
    quantity = order["quantity"]
    original_eta = shipment["original_eta"]
    plans: list[dict[str, Any]] = []

    def add(kind: str, label: str, allocations: list[dict[str, Any]], cost: int) -> None:
        arrival = max(item["arrival_eta"] for item in allocations)
        plans.append(
            {
                "id": f"{state['incident_id']}:{state['scenario_run_id']}:{kind}:v{source_version}",
                "source_version": source_version,
                "kind": kind,
                "label": label,
                "allocations": allocations,
                "incremental_cost_usd": cost,
                "projected_completion_eta": arrival,
                "projected_customer_delay_hours": delay_hours(arrival, original_eta),
                "delivery_status": "projected",
            }
        )

    add(
        "wait",
        "Keep the delayed shipment",
        [{"source": "delayed-shipment", "units": quantity, "arrival_eta": shipment["delayed_eta"]}],
        0,
    )
    if economy["capacity"] >= quantity:
        add(
            "reroute",
            "Move the full order to an alternative carrier",
            [{"source": "economy-reroute", "units": quantity, "arrival_eta": economy["arrival_eta"]}],
            economy["incremental_cost_usd"],
        )
    local_units = min(inventory["available"], quantity)
    express_units = quantity - local_units
    if local_units > 0 and express_units > 0 and express["capacity"] >= express_units:
        add(
            "split-express",
            "Fulfill local stock and send the rest express",
            [
                {"source": "arequipa-stock", "units": local_units, "arrival_eta": inventory["ready_at"]},
                {"source": "express", "units": express_units, "arrival_eta": express["arrival_eta"]},
            ],
            express["incremental_cost_usd"],
        )
    return plans
