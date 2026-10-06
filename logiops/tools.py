"""Read-only logistics tools used by the planner and future model adapters."""

from __future__ import annotations

from copy import deepcopy
from typing import Any


def get_shipment(state: dict[str, Any]) -> dict[str, Any]:
    return deepcopy(state["shipment"])


def get_order(state: dict[str, Any]) -> dict[str, Any]:
    return deepcopy(state["order"])


def get_local_inventory(state: dict[str, Any]) -> dict[str, Any]:
    return deepcopy(state["inventory"])


def find_alternative_carriers(state: dict[str, Any]) -> dict[str, Any]:
    return deepcopy(state["carriers"])
