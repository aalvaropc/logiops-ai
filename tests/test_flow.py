"""The demo's financial, inventory, approval, and retry invariants."""

import asyncio
import json
import sqlite3
import threading
import time
from contextlib import asynccontextmanager

import httpx
import pytest

from logiops.api import create_app
from logiops.scenario import INCIDENT_IDS, best_plan, build_plans, known_figures, seed_state
from logiops.service import LogiOpsService, WorkflowError


@asynccontextmanager
async def client_for(db_path):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(db_path)), base_url="http://test"
    ) as client:
        yield client


async def plans_from(client):
    response = await client.post("/incidents/SHIP-421/investigate")
    assert response.status_code == 200, response.text
    return {plan["kind"]: plan for plan in response.json()["plans"]}


def test_default_scenario_has_three_calculated_options(tmp_path):
    async def run():
        async with client_for(tmp_path / "logiops.sqlite3") as client:
            plans = await plans_from(client)
            assert set(plans) == {"wait", "reroute", "split-express"}
            assert [(plans[k]["incremental_cost_usd"], plans[k]["projected_customer_delay_hours"])
                    for k in ("wait", "reroute", "split-express")] == [(0, 12), (80, 3), (120, 0)]
            assert [(item["source"], item["units"]) for item in plans["split-express"]["allocations"]] == [
                ("arequipa-stock", 12), ("express", 8)
            ]
            snapshot = (await client.get("/incidents/SHIP-421")).json()
            assert snapshot["state"]["inventory"]["arequipa"]["available"] == 12
            assert snapshot["state"]["shipment"]["units_on_delayed_route"] == 20
            assert not snapshot["executions"]

    asyncio.run(run())


def test_approval_execution_retry_and_restart(tmp_path):
    async def run():
        db_path = tmp_path / "logiops.sqlite3"
        async with client_for(db_path) as client:
            plan = (await plans_from(client))["split-express"]
            body = {"plan_id": plan["id"], "source_version": plan["source_version"]}
            assert (await client.post("/incidents/SHIP-421/execute", json=body)).status_code == 409
            approval = await client.post(
                "/incidents/SHIP-421/approvals", json={**body, "approved_by": "demo-operator"}
            )
            assert approval.status_code == 200, approval.text
            first = await client.post("/incidents/SHIP-421/execute", json=body)
            second = await client.post("/incidents/SHIP-421/execute", json=body)
            assert first.status_code == second.status_code == 200
            assert first.json() == second.json()
            assert first.json()["status"] == "verified_operationally"
            assert first.json()["delivery_status"] == "projected"

        async with client_for(db_path) as restarted:
            snapshot = (await restarted.get("/incidents/SHIP-421")).json()
            assert snapshot["state"]["status"] == "verified"
            assert snapshot["state"]["inventory"]["arequipa"]["available"] == 0
            assert snapshot["state"]["shipment"]["units_on_delayed_route"] == 0
            assert sum(item["units"] for item in snapshot["state"]["fulfillments"]) == 20
            assert len(snapshot["state"]["notifications"]) == 2
            assert len(snapshot["executions"]) == 1
            assert sum(event["name"] == "plan_executed" for event in snapshot["events"]) == 1

    asyncio.run(run())


def test_inventory_change_invalidates_approved_plan(tmp_path):
    async def run():
        async with client_for(tmp_path / "logiops.sqlite3") as client:
            plan = (await plans_from(client))["split-express"]
            body = {"plan_id": plan["id"], "source_version": plan["source_version"]}
            assert (await client.post(
                "/incidents/SHIP-421/approvals", json={**body, "approved_by": "demo-operator"}
            )).status_code == 200
            approved = (await client.get("/incidents/SHIP-421")).json()["approvals"]
            assert [item["is_current"] for item in approved] == [True]
            changed = await client.post("/demo/inventory", json={"available": 11})
            assert changed.status_code == 200
            assert changed.json()["source_version"] == 2
            # The old approval stays in the audit trail but is no longer current.
            assert [item["is_current"] for item in changed.json()["approvals"]] == [False]
            approval_event = next(e for e in changed.json()["events"] if e["name"] == "plan_approved")
            assert approval_event["data"]["source_version"] == 1
            assert (await client.post("/incidents/SHIP-421/execute", json=body)).status_code == 409
            new_plans = await plans_from(client)
            assert set(new_plans) == {"wait", "reroute"}
            assert (await client.get("/incidents/SHIP-421")).json()["state"]["notifications"] == []

    asyncio.run(run())


def test_reset_restores_fixture_and_clears_history(tmp_path):
    async def run():
        async with client_for(tmp_path / "logiops.sqlite3") as client:
            old_plan = (await plans_from(client))["split-express"]
            reset = await client.post("/demo/reset")
            assert reset.status_code == 200
            assert reset.json()["source_version"] == 1
            assert reset.json()["plans"] == []
            assert reset.json()["approvals"] == []
            assert reset.json()["state"]["inventory"]["arequipa"]["available"] == 12
            assert [event["name"] for event in reset.json()["events"]] == ["scenario_reset"]
            new_plan = (await plans_from(client))["split-express"]
            assert new_plan["id"] != old_plan["id"]
            stale_approval = await client.post(
                "/incidents/SHIP-421/approvals",
                json={"plan_id": old_plan["id"], "source_version": 1, "approved_by": "demo-operator"},
            )
            assert stale_approval.status_code == 404

    asyncio.run(run())


@pytest.mark.parametrize(
    ("kind", "delayed_units", "fulfillment_units", "local_stock"),
    [("wait", 20, 0, 12), ("reroute", 0, 20, 12)],
)
def test_other_approved_options_preserve_all_units(
    tmp_path, kind, delayed_units, fulfillment_units, local_stock
):
    async def run():
        async with client_for(tmp_path / "logiops.sqlite3") as client:
            plan = (await plans_from(client))[kind]
            request = {"plan_id": plan["id"], "source_version": plan["source_version"]}
            approval = await client.post(
                "/incidents/SHIP-421/approvals", json={**request, "approved_by": "demo-operator"}
            )
            assert approval.status_code == 200
            assert (await client.post("/incidents/SHIP-421/execute", json=request)).status_code == 200
            state = (await client.get("/incidents/SHIP-421")).json()["state"]
            assert state["shipment"]["units_on_delayed_route"] == delayed_units
            assert sum(item["units"] for item in state["fulfillments"]) == fulfillment_units
            assert state["inventory"]["arequipa"]["available"] == local_stock

    asyncio.run(run())


def test_enough_local_stock_offers_the_whole_order_from_the_warehouse(tmp_path):
    async def run():
        async with client_for(tmp_path / "logiops.sqlite3") as client:
            assert (await client.post("/demo/inventory", json={"available": 25})).status_code == 200
            plans = await plans_from(client)
            assert set(plans) == {"wait", "reroute", "local-stock"}
            local = plans["local-stock"]
            assert (local["incremental_cost_usd"], local["projected_customer_delay_hours"]) == (0, 0)
            request = {"plan_id": local["id"], "source_version": local["source_version"]}
            approval = await client.post(
                "/incidents/SHIP-421/approvals", json={**request, "approved_by": "demo-operator"}
            )
            assert approval.status_code == 200
            assert (await client.post("/incidents/SHIP-421/execute", json=request)).status_code == 200
            state = (await client.get("/incidents/SHIP-421")).json()["state"]
            assert state["shipment"]["units_on_delayed_route"] == 0
            assert [(item["source"], item["units"]) for item in state["fulfillments"]] == [("arequipa-stock", 20)]
            assert state["inventory"]["arequipa"]["available"] == 5

    asyncio.run(run())


def test_agent_trace_rejects_stale_snapshot(tmp_path):
    service = LogiOpsService(tmp_path / "stale-agent.sqlite3")
    service.investigate("SHIP-421")
    service.set_local_inventory("SHIP-421", 5)
    with pytest.raises(WorkflowError, match="Source data changed"):
        service.record_agent_run("SHIP-421", 1, {
            "answer": "stale", "tool_trace": [], "usage": {}, "mode": "replay",
        })
    assert not any(
        event["name"] == "agent_investigation_completed"
        for event in service.get("SHIP-421")["events"]
    )


def test_agent_events_are_audited_with_the_current_version(tmp_path):
    service = LogiOpsService(tmp_path / "agent-events.sqlite3")
    service.set_local_inventory("SHIP-421", 11)
    recorded = service.record_agent_event("SHIP-421", "agent_run_failed", {"error": "timeout", "source_version": 99})
    assert recorded == {"source_version": 2}
    event = service.get("SHIP-421")["events"][-1]
    assert event["name"] == "agent_run_failed"
    assert event["data"] == {"error": "timeout", "incident_id": "SHIP-421", "source_version": 2}
    with pytest.raises(WorkflowError, match="Unsupported agent event"):
        service.record_agent_event("SHIP-421", "plan_executed", {})
    decided = service.record_agent_event("SHIP-421", "autopilot_decision", {"decision": "escalate", "reasons": ["cost"]})
    assert decided == {"source_version": 2} and service.get("SHIP-421")["events"][-1]["name"] == "autopilot_decision"


# --- Several incidents (R1, 2026-10-07) -------------------------------------------


def _summary(plans):
    return {plan["kind"]: (plan["incremental_cost_usd"], plan["projected_customer_delay_hours"], plan["late_units"])
            for plan in plans}


EXPECTED_PLANS = {
    "SHIP-421": ({"wait": (0, 12, 20), "reroute": (80, 3, 20), "split-express": (120, 0, 0)}, "split-express"),
    "SHIP-433": ({"wait": (0, 24, 30), "reroute": (150, 8, 30), "priority-air": (240, 24, 18),
                  "priority-air-ground": (390, 8, 18)}, "priority-air-ground"),
    "SHIP-452": ({"wait": (0, 72, 40), "expedite": (350, 18, 40), "split-wait": (0, 72, 15),
                  "split-expedite": (350, 18, 15)}, "split-expedite"),
    "SHIP-460": ({"priority-first": (0, 6, 15), "first-come": (0, 30, 15), "express-transfer": (300, 0, 0)},
                 "express-transfer"),
}


@pytest.mark.parametrize("incident_id", INCIDENT_IDS)
def test_each_incident_offers_its_own_plans_and_a_defensible_best(incident_id):
    plans = build_plans(seed_state(incident_id), 1)
    expected, best = EXPECTED_PLANS[incident_id]
    assert _summary(plans) == expected
    assert best_plan(plans)["kind"] == best
    for plan in plans:
        assert plan["id"].startswith(f"{incident_id}:") and plan["delivery_status"] == "projected"
        assert sum(order["quantity"] for order in plan["orders"]) == sum(a["units"] for a in plan["allocations"])


def test_the_inbox_lists_every_incident_open_first_by_due_time(tmp_path):
    async def run():
        async with client_for(tmp_path / "inbox.sqlite3") as client:
            inbox = (await client.get("/incidents")).json()["incidents"]
            assert [item["incident_id"] for item in inbox] == ["SHIP-421", "SHIP-452", "SHIP-433", "SHIP-460"]
            assert {item["kind"] for item in inbox} == {"delay", "carrier_outage", "customs_hold", "stock_conflict"}
            assert all(item["simulated"] and item["status"] == "detected" for item in inbox)
            assert {item["incident_id"]: item["priority"] for item in inbox} == {
                "SHIP-421": "standard", "SHIP-452": "standard", "SHIP-433": "critical", "SHIP-460": "critical"}
            assert next(item for item in inbox if item["incident_id"] == "SHIP-433")["warehouse_id"] is None

    asyncio.run(run())


def test_incidents_are_isolated_from_each_other(tmp_path):
    async def run():
        async with client_for(tmp_path / "isolated.sqlite3") as client:
            ship_421_plan = (await plans_from(client))["split-express"]
            response = await client.post("/incidents/SHIP-433/investigate")
            plan = {item["kind"]: item for item in response.json()["plans"]}["priority-air-ground"]
            request = {"plan_id": plan["id"], "source_version": plan["source_version"]}
            assert (await client.post("/incidents/SHIP-433/approvals",
                                      json={**request, "approved_by": "demo-operator"})).status_code == 200
            executed = await client.post("/incidents/SHIP-433/execute", json=request)
            assert executed.status_code == 200 and executed.json()["accounted_units"] == 30
            # SHIP-421 at the same version keeps its own plans, approvals and events.
            other = (await client.get("/incidents/SHIP-421")).json()
            assert other["state"]["status"] == "investigated" and other["approvals"] == [] and other["executions"] == []
            assert {event["name"] for event in other["events"]} == {"scenario_reset", "incident_investigated"}
            assert all(item["id"].startswith("SHIP-421:") for item in other["plans"])
            # A plan id from one incident is unknown under another.
            foreign = {"plan_id": ship_421_plan["id"], "source_version": 1}
            assert (await client.post("/incidents/SHIP-433/approvals",
                                      json={**foreign, "approved_by": "demo-operator"})).status_code == 404
            assert (await client.post("/incidents/SHIP-433/execute", json=foreign)).status_code in (404, 409)

    asyncio.run(run())


def test_two_orders_share_the_stock_and_every_unit_is_accounted_for(tmp_path):
    async def run():
        async with client_for(tmp_path / "conflict.sqlite3") as client:
            response = await client.post("/incidents/SHIP-460/investigate")
            plan = {item["kind"]: item for item in response.json()["plans"]}["priority-first"]
            request = {"plan_id": plan["id"], "source_version": plan["source_version"]}
            await client.post("/incidents/SHIP-460/approvals", json={**request, "approved_by": "demo-operator"})
            result = (await client.post("/incidents/SHIP-460/execute", json=request)).json()
            assert result["accounted_units"] == 45
            assert result["orders"] == [{"order_id": "ORD-460", "units": 20}, {"order_id": "ORD-461", "units": 25}]
            state = (await client.get("/incidents/SHIP-460")).json()["state"]
            assert state["inventory"]["trujillo"]["available"] == 0
            assert state["shipment"]["units_on_delayed_route"] == 15  # the school's shortfall waits
            assert len(state["notifications"]) == 3  # one customer per order, plus operations

    asyncio.run(run())


def test_execution_rejects_a_plan_that_does_not_match_its_incident(tmp_path):
    service = LogiOpsService(tmp_path / "tampered.sqlite3")
    plan = {item["kind"]: item for item in service.investigate("SHIP-452")}["split-expedite"]
    service.approve("SHIP-452", plan["id"], 1, "demo-operator")
    for change, message in (
        ({"source": "teleport"}, "Unknown allocation source"),
        ({"units": 14}, "does not account for the full order"),
        ({"order_id": "ORD-999"}, "unknown order"),
    ):
        tampered = {**plan, "allocations": [{**plan["allocations"][-1], **change}, *plan["allocations"][:-1]]}
        with service._connection(write=True) as connection:
            connection.execute("UPDATE plans SET plan_json = ? WHERE plan_id = ?", (json.dumps(tampered), plan["id"]))
        with pytest.raises(WorkflowError, match=message):
            service.execute("SHIP-452", plan["id"], 1)
    assert service.get("SHIP-452")["state"]["inventory"]["lima"]["available"] == 25  # nothing changed


def test_the_stock_control_targets_each_incident_own_warehouse(tmp_path):
    async def run():
        async with client_for(tmp_path / "stock.sqlite3") as client:
            changed = await client.post("/demo/inventory", json={"incident_id": "SHIP-460", "available": 20})
            assert changed.status_code == 200 and changed.json()["source_version"] == 2
            kinds = {item["kind"] for item in (await client.post("/incidents/SHIP-460/investigate")).json()["plans"]}
            assert kinds == {"priority-first", "first-come"}
            assert (await client.get("/incidents/SHIP-421")).json()["source_version"] == 1
            no_stock = await client.post("/demo/inventory", json={"incident_id": "SHIP-433", "available": 5})
            assert no_stock.status_code == 422
            await client.post("/demo/inventory", json={"incident_id": "SHIP-460", "available": 10})
            infeasible = await client.post("/incidents/SHIP-460/investigate")
            assert infeasible.status_code == 409 and "No feasible plan" in infeasible.json()["detail"]

    asyncio.run(run())


def test_reset_restores_one_incident_or_all_of_them(tmp_path):
    service = LogiOpsService(tmp_path / "reset.sqlite3")
    service.set_local_inventory("SHIP-452", 3)
    service.set_local_inventory("SHIP-421", 3)
    service.reset("SHIP-452")
    assert service.get("SHIP-452")["state"]["inventory"]["lima"]["available"] == 25
    assert service.get("SHIP-421")["source_version"] == 2
    service.reset()
    for incident_id in INCIDENT_IDS:
        snapshot = service.get(incident_id)
        assert snapshot["source_version"] == 1 and [e["name"] for e in snapshot["events"]] == ["scenario_reset"]


def test_an_older_single_incident_database_is_rebuilt_once(tmp_path):
    path = tmp_path / "v1.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.executescript(
            "CREATE TABLE snapshot (incident_id TEXT PRIMARY KEY, version INTEGER, state_json TEXT);"
            "CREATE TABLE plans (plan_id TEXT PRIMARY KEY, source_version INTEGER, plan_json TEXT);"
            "CREATE TABLE events (sequence INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, data_json TEXT, recorded_at TEXT);"
            "INSERT INTO snapshot VALUES ('SHIP-421', 7, '{}');"
        )
    service = LogiOpsService(path)
    assert [item["incident_id"] for item in service.list_incidents()] == ["SHIP-421", "SHIP-452", "SHIP-433", "SHIP-460"]
    assert [e["name"] for e in service.get("SHIP-433")["events"]] == ["scenario_reset", "schema_migrated"]
    plans = service.investigate("SHIP-421")
    reopened = LogiOpsService(path)  # the current layout is kept as it is
    assert [plan["id"] for plan in reopened.get("SHIP-421")["plans"]] == [plan["id"] for plan in plans]


def test_known_figures_are_the_numbers_an_answer_may_quote():
    assert known_figures(seed_state("SHIP-421")) == {"dollars": [80, 120], "hours": [12]}
    assert known_figures(seed_state("SHIP-460")) == {"dollars": [300], "hours": [6, 30, 48]}


# --- Consistent reads and bounded inputs (2026-10-08) -----------------------------


def test_a_snapshot_is_read_in_one_transaction(tmp_path, monkeypatch):
    # A reset that commits while get() is between two reads must not mix the old state with the new rows.
    service = LogiOpsService(tmp_path / "consistent.sqlite3")
    plan = service.investigate("SHIP-421")[0]
    service.approve("SHIP-421", plan["id"], plan["source_version"], "demo-operator")
    original = LogiOpsService._snapshot
    writer: dict[str, threading.Thread] = {}

    def snapshot_then_reset(connection, incident_id):
        result = original(connection, incident_id)
        if not writer:
            writer["thread"] = threading.Thread(target=service.reset, args=("SHIP-421",))
            writer["thread"].start()
            time.sleep(0.3)
        return result

    monkeypatch.setattr(LogiOpsService, "_snapshot", staticmethod(snapshot_then_reset))
    snapshot = service.get("SHIP-421")
    writer["thread"].join(timeout=10)
    assert snapshot["state"]["status"] == "approved"
    assert [approval["plan_id"] for approval in snapshot["approvals"]] == [plan["id"]]
    assert {event["name"] for event in snapshot["events"]} >= {"incident_investigated", "plan_approved"}
    # The reset still lands, right after the read.
    assert service.get("SHIP-421")["state"]["status"] == "detected"


def test_approver_names_are_bounded(tmp_path):
    service = LogiOpsService(tmp_path / "approver.sqlite3")
    plan = service.investigate("SHIP-421")[0]
    with pytest.raises(WorkflowError, match="at most 80 characters") as error:
        service.approve("SHIP-421", plan["id"], plan["source_version"], "x" * 81)
    assert error.value.status_code == 422
    approved = service.approve("SHIP-421", plan["id"], plan["source_version"], " " + "y" * 80 + " ")
    assert approved["approved_by"] == "y" * 80


def test_the_api_rejects_oversized_approval_fields(tmp_path):
    async def scenario():
        async with client_for(tmp_path / "oversized.sqlite3") as client:
            plan = next(iter((await plans_from(client)).values()))
            too_long_name = await client.post("/incidents/SHIP-421/approvals", json={
                "plan_id": plan["id"], "source_version": plan["source_version"], "approved_by": "x" * 100_000,
            })
            too_long_plan = await client.post("/incidents/SHIP-421/approvals", json={
                "plan_id": "p" * 201, "source_version": plan["source_version"], "approved_by": "demo-operator",
            })
            return too_long_name.status_code, too_long_plan.status_code

    assert asyncio.run(scenario()) == (422, 422)


def test_an_agent_run_keeps_its_checks_and_model(tmp_path):
    service = LogiOpsService(tmp_path / "agent-checks.sqlite3")
    service.investigate("SHIP-421")
    evaluations = [{"attempt": 1, "passed": False, "issues": ["$95 is not a plan cost"]}, {"attempt": 2, "passed": True}]
    service.record_agent_run("SHIP-421", 1, {
        "answer": "ok", "tool_trace": [], "usage": {}, "mode": "replay",
        "model": "scripted", "evaluations": evaluations, "grounded": True,
    })
    service.record_agent_run("SHIP-421", 1, {"answer": "plain", "tool_trace": [], "usage": {}, "mode": "replay"})
    checked, plain = [event["data"] for event in service.get("SHIP-421")["events"]
                      if event["name"] == "agent_investigation_completed"]
    assert (checked["model"], checked["evaluations"], checked["grounded"]) == ("scripted", evaluations, True)
    assert not {"model", "evaluations", "grounded"} & plain.keys()
