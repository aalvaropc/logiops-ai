"""Incidents come from a registry: the built-ins plus any scenario pack, validated before anything is seeded."""

import copy
import json
from pathlib import Path

import pytest

from logiops.scenario import (
    INCIDENT_IDS, INCIDENTS, KIND_LABELS, PLAYBOOKS, ScenarioPackError, best_plan, build_plans, builtin_incidents, incident_ids,
    load_scenario_pack, register_incident, register_pack, reset_registry, seed_state,
)
from logiops.service import LogiOpsService, WorkflowError

PACK = Path(__file__).resolve().parent / "fixtures" / "scenario_pack.json"


def pack_incident(**changes):
    definition = copy.deepcopy(json.loads(PACK.read_text())["incidents"][0])
    for path, value in changes.items():
        target = definition
        keys = path.split(".")
        for key in keys[:-1]:
            target = target[key] if not key.isdigit() else target[int(key)]
        last = keys[-1]
        if value is ...:
            del target[last]
        elif last.isdigit():
            target[int(last)] = value
        else:
            target[last] = value
    return definition


def test_the_built_ins_are_the_registry_and_the_template():
    assert incident_ids() == INCIDENT_IDS == ("SHIP-421", "SHIP-433", "SHIP-452", "SHIP-460")
    template = builtin_incidents()
    assert [item["id"] for item in template] == list(INCIDENT_IDS)
    for item in template:
        assert item["options"] == PLAYBOOKS[item["id"]] and item["options"] is not PLAYBOOKS[item["id"]]
        clone = {**copy.deepcopy(item), "id": "SHIP-999"}
        clone["orders"] = [{**order, "id": order["id"].replace("ORD-4", "ORD-9")} for order in clone["orders"]]
        register_incident(clone)
        reset_registry()
    assert seed_state("SHIP-433")["inventory"] == {}
    seed_state("SHIP-421")["carriers"]["express"]["capacity"] = 0
    assert seed_state("SHIP-421")["carriers"]["express"]["capacity"] == 8, "seeds are copies"


def test_a_pack_registers_a_new_kind_and_its_plans_are_calculated_like_the_built_ins(tmp_path):
    assert load_scenario_pack(PACK) == ["SHIP-470"]
    assert incident_ids()[-1] == "SHIP-470" and KIND_LABELS["port_strike"] == "Port strike"
    state = seed_state("SHIP-470")
    plans = build_plans(state, 1)
    assert [plan["kind"] for plan in plans] == ["wait", "priority-local", "reroute"]
    assert best_plan(plans)["kind"] == "priority-local"
    service = LogiOpsService(tmp_path / "pack.sqlite3")
    entry = next(item for item in service.list_incidents() if item["incident_id"] == "SHIP-470")
    assert entry["kind_label"] == "Port strike" and entry["priority"] == "critical" and entry["units"] == 50
    chosen = next(plan for plan in service.investigate("SHIP-470") if plan["kind"] == "priority-local")
    service.approve("SHIP-470", chosen["id"], chosen["source_version"], "operator")
    executed = service.execute("SHIP-470", chosen["id"], chosen["source_version"])
    assert executed["accounted_units"] == 50 and executed["incremental_cost_usd"] == 0
    assert service.reset("SHIP-470")["state"]["status"] == "detected"
    reset_registry()
    assert "SHIP-470" not in incident_ids() and "port_strike" not in KIND_LABELS and "SHIP-470" not in PLAYBOOKS


def test_a_pack_registered_later_is_seeded_on_demand_and_dropped_when_the_process_forgets_it(tmp_path):
    service = LogiOpsService(tmp_path / "later.sqlite3")
    assert len(service.list_incidents()) == 4
    load_scenario_pack(PACK)
    assert service.seed_missing() == ["SHIP-470"] and service.seed_missing() == []
    assert len(service.list_incidents()) == 5
    assert len(service.reset()["events"]) == 1 and len(service.list_incidents()) == 5
    reset_registry()
    with pytest.raises(WorkflowError):
        service.reset("SHIP-470")
    reopened = LogiOpsService(tmp_path / "later.sqlite3")
    assert {item["incident_id"] for item in reopened.list_incidents()} == set(INCIDENT_IDS)


@pytest.mark.parametrize("change, path, message", [
    ({"id": "SHIP-421"}, "id", "already registered"),
    ({"id": "ship 470"}, "id", "looks like SHIP-470"),
    ({"kind": "Port Strike"}, "kind", "lowercase"),
    ({"kind": "harbour_closed", "kind_label": ...}, "kind_label", "needs a kind_label"),
    ({"shipment.units_on_delayed_route": 0}, "shipment.units_on_delayed_route", "positive"),
    ({"shipment.delayed_eta": "2026-10-15T10:00:00Z"}, "shipment.delayed_eta", "-05:00"),
    ({"orders.0.priority": "urgent"}, "orders[0].priority", "critical or standard"),
    ({"orders.0.id": "ORD-471"}, "orders[1].id", "already used"),
    ({"orders.0.sku": "OTHER"}, "orders[0].sku", "must match"),
    ({"inventory": {"piura": {"sku": "SEAFOOD-07", "available": 1, "ready_at": "2026-10-13T08:00:00-05:00"}, "lima": {"sku": "SEAFOOD-07", "available": 1, "ready_at": "2026-10-13T08:00:00-05:00"}}}, "inventory", "at most one warehouse"),
    ({"carriers": {"delayed-shipment": {"capacity": 1, "arrival_eta": "2026-10-13T08:00:00-05:00", "incremental_cost_usd": 1}}}, "carriers.delayed-shipment", "not a stock source"),
    ({"options.2.sources": ["sea-plane"]}, "options[2].sources", "unknown source 'sea-plane'"),
    ({"options.1.sources": {"critical": ["piura-stock"]}}, "options[1].sources", "exactly critical and standard"),
    ({"options.0.kind": "reroute"}, "options[2].kind", "repeated"),
    ({"options.0.sequence": "random"}, "options[0].sequence", "priority or placed"),
])
def test_every_mistake_is_reported_with_its_path(change, path, message):
    with pytest.raises(ScenarioPackError) as raised:
        register_incident(pack_incident(**change))
    assert any(item["path"] == path and message in item["message"] for item in raised.value.errors), raised.value.errors
    assert "SHIP-470" not in INCIDENTS


def test_a_pack_with_one_bad_incident_registers_nothing():
    good = pack_incident()
    bad = pack_incident(id="SHIP-471", title="")
    bad["orders"] = [{**order, "id": order["id"].replace("ORD-47", "ORD-48")} for order in bad["orders"]]
    with pytest.raises(ScenarioPackError) as raised:
        register_pack({"version": 1, "incidents": [good, bad]})
    assert raised.value.errors[0]["incident"] == "SHIP-471"
    assert "SHIP-470" not in INCIDENTS and "SHIP-471" not in INCIDENTS
    with pytest.raises(ScenarioPackError, match="version"):
        register_pack({"version": 2, "incidents": []})
    with pytest.raises(ScenarioPackError, match="cannot read"):
        load_scenario_pack(PACK.with_name("missing.json"))
