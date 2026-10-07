"""Read-only logistics views used by the planner and the model adapters.

Both adapters (the MCP server and the direct tool loop) answer with these views,
so the same question always gets the same answer.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from .scenario import local_warehouse


def get_shipment(state: dict[str, Any]) -> dict[str, Any]:
    return deepcopy(state["shipment"])


def get_orders(state: dict[str, Any]) -> list[dict[str, Any]]:
    return deepcopy(state["orders"])


def get_local_inventory(state: dict[str, Any]) -> dict[str, Any]:
    return deepcopy(state["inventory"])


def find_alternative_carriers(state: dict[str, Any]) -> dict[str, Any]:
    return deepcopy(state["carriers"])


def _same(left: Any, right: Any) -> bool:
    return str(left).strip().casefold() == str(right).strip().casefold()


def shipment_view(state: dict[str, Any]) -> dict[str, Any]:
    """The shipment with the ids a model needs next: its orders and its warehouse, if any."""
    order_ids = [order["id"] for order in state["orders"]]
    view = {**get_shipment(state), "order_ids": order_ids, "warehouse_id": local_warehouse(state)}
    if len(order_ids) == 1:
        view["order_id"] = order_ids[0]
    return view


def order_view(state: dict[str, Any], order_id: Any) -> dict[str, Any] | None:
    return next((deepcopy(order) for order in state["orders"] if _same(order["id"], order_id)), None)


def orders_hint(state: dict[str, Any]) -> str:
    ids = [order["id"] for order in state["orders"]]
    if len(ids) == 1:
        return f"The order linked to {state['incident_id']} is {ids[0]}."
    return f"The orders linked to {state['incident_id']} are {', '.join(ids[:-1])} and {ids[-1]}."


def inventory_view(state: dict[str, Any], warehouse_id: Any, sku: Any) -> dict[str, Any] | None:
    warehouse = local_warehouse(state)
    if warehouse is None or not _same(warehouse_id, warehouse):
        return None
    stock = state["inventory"][warehouse]
    if not _same(sku, stock["sku"]):
        return None
    return {"warehouse_id": warehouse, **deepcopy(stock)}


def inventory_hint(state: dict[str, Any]) -> str:
    warehouse = local_warehouse(state)
    if warehouse is None:
        return f"{state['incident_id']} has no local warehouse stock to check."
    return f"Use warehouse_id '{warehouse}' and sku '{state['inventory'][warehouse]['sku']}'."
