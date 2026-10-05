"""The demo's financial, inventory, approval, and retry invariants."""

import asyncio
from contextlib import asynccontextmanager

import httpx
import pytest

from logiops.api import create_app


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
            changed = await client.post("/demo/inventory", json={"available": 11})
            assert changed.status_code == 200
            assert changed.json()["source_version"] == 2
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
