"""Scenario packs over HTTP and at start-up: uploaded incidents join the inbox, the agent, the MCP server and the alerts."""

import asyncio
import copy
import json
from pathlib import Path

import httpx
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from pydantic import AnyUrl

from logiops.api import create_app
from logiops.scenario import incident_ids

PACK = json.loads((Path(__file__).resolve().parent / "fixtures" / "scenario_pack.json").read_text())
BASE_URL = "http://127.0.0.1:8000"
TOKEN = "t" * 40


def run(coroutine):
    return asyncio.run(coroutine)


async def client_for(app, token=None):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE_URL, headers=headers)


def test_the_built_in_template_is_served_and_an_uploaded_pack_runs_the_whole_flow_in_replay(tmp_path, monkeypatch):
    monkeypatch.setenv("LOGIOPS_AGENT_MODE", "replay")

    async def go():
        app = create_app(tmp_path / "packs.sqlite3")
        async with app.router.lifespan_context(app):
            async with await client_for(app) as client:
                template = await client.get("/scenario/packs/builtin")
                assert template.status_code == 200
                assert [item["id"] for item in template.json()["incidents"]] == ["SHIP-421", "SHIP-433", "SHIP-452", "SHIP-460"]
                assert template.json()["version"] == 1 and "options" in template.json()["incidents"][0]

                uploaded = await client.post("/scenario/packs", json=PACK)
                assert uploaded.status_code == 201, uploaded.text
                assert uploaded.json()["registered"] == ["SHIP-470"]
                assert "SHIP-470" in [item["incident_id"] for item in uploaded.json()["incidents"]]
                inbox = (await client.get("/incidents")).json()["incidents"]
                found = next(item for item in inbox if item["incident_id"] == "SHIP-470")
                assert found["kind_label"] == "Port strike" and found["status"] == "detected"

                briefing = await client.post("/agent/briefing", json={"question": "Any delays today?"})
                assert briefing.status_code == 200 and "SHIP-470" in briefing.json()["answer"]
                run_ = await client.post("/incidents/SHIP-470/agent/investigate", json={})
                assert run_.status_code == 200, run_.text
                body = run_.json()
                assert body["mode"] == "replay" and len(body["plans"]) == 3 and body["grounded"] is True
                assert [step["tool"] for step in body["tool_trace"]][0] == "get_shipment" and "SHIP-470" in body["spoken"]
                plan = next(item for item in body["plans"] if item["kind"] == "priority-local")
                approved = await client.post("/incidents/SHIP-470/approvals", json={"plan_id": plan["id"], "source_version": plan["source_version"], "approved_by": "judge"})
                executed = await client.post("/incidents/SHIP-470/execute", json={"plan_id": plan["id"], "source_version": plan["source_version"]})
                assert approved.status_code == 200 and executed.status_code == 200, executed.text
                assert executed.json()["accounted_units"] == 50

                metrics = (await client.get("/metrics")).json()
                mine = next(item for item in metrics["incidents"] if item["incident_id"] == "SHIP-470")
                assert mine["executed"] and mine["kind"] == "port_strike"
                briefing = await client.post("/agent/briefing", json={"question": "Any delays today?"})
                assert briefing.status_code == 200 and "1 resolved" in briefing.json()["answer"]

                again = await client.post("/scenario/packs", json=PACK)
                assert again.status_code == 422 and again.json()["detail"]["errors"][0]["incident"] == "SHIP-470"
                assert incident_ids() == ("SHIP-421", "SHIP-433", "SHIP-452", "SHIP-460", "SHIP-470")

    run(go())


def test_a_bad_pack_answers_422_with_every_path_and_registers_nothing(tmp_path):
    broken = copy.deepcopy(PACK)
    broken["incidents"][0]["orders"][0]["priority"] = "urgent"
    broken["incidents"][0]["carriers"]["refrigerated-truck"]["capacity"] = 0

    async def go():
        app = create_app(tmp_path / "bad.sqlite3")
        async with await client_for(app) as client:
            response = await client.post("/scenario/packs", json=broken)
            shape = await client.post("/scenario/packs", json={"version": 2, "incidents": []})
            extra = await client.post("/scenario/packs", json={"version": 1, "incidents": [{**PACK["incidents"][0], "surprise": 1}]})
            inbox = (await client.get("/incidents")).json()["incidents"]
        return response, shape, extra, inbox

    response, shape, extra, inbox = run(go())
    assert response.status_code == 422
    paths = {item["path"] for item in response.json()["detail"]["errors"]}
    assert "orders[0].priority" in paths and "carriers.refrigerated-truck.capacity" in paths
    assert all(item["incident"] == "SHIP-470" for item in response.json()["detail"]["errors"])
    assert shape.status_code == 422 and extra.status_code == 422
    assert [item["incident_id"] for item in inbox] == ["SHIP-433", "SHIP-460", "SHIP-421", "SHIP-452"]
    assert incident_ids() == ("SHIP-421", "SHIP-433", "SHIP-452", "SHIP-460")


def test_a_pack_named_in_the_environment_loads_at_start_and_a_bad_one_refuses_to_start(tmp_path, monkeypatch):
    path = tmp_path / "pack.json"
    path.write_text(json.dumps(PACK))
    monkeypatch.setenv("LOGIOPS_SCENARIO_PACK", str(path))
    app = create_app(tmp_path / "env.sqlite3")
    assert incident_ids()[-1] == "SHIP-470"

    async def go():
        async with await client_for(app) as client:
            return (await client.get("/incidents/SHIP-470")).status_code

    assert run(go()) == 200
    broken = tmp_path / "broken.json"
    broken.write_text("{not json")
    monkeypatch.setenv("LOGIOPS_SCENARIO_PACK", str(broken))
    with pytest.raises(RuntimeError, match="LOGIOPS_SCENARIO_PACK"):
        create_app(tmp_path / "env2.sqlite3")


def test_the_mcp_server_the_completions_and_the_alerts_see_the_new_incident(tmp_path):
    async def go():
        app = create_app(tmp_path / "mcp.sqlite3")
        async with app.router.lifespan_context(app):
            async with await client_for(app) as client:
                assert (await client.post("/scenario/packs", json=PACK)).status_code == 201
                async with streamable_http_client(f"{BASE_URL}/mcp", http_client=client) as (read, write, _):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        record = await session.read_resource(AnyUrl("incident://SHIP-470"))
                        assert "Paita" in record.contents[0].text
                        listed = await session.call_tool("list_incidents", {})
                        assert "SHIP-470" in [item["incident_id"] for item in listed.structuredContent["incidents"]]
                        order = await session.call_tool("get_order", {"order_id": "ORD-470"})
                        assert order.isError is False and order.structuredContent["priority"] == "critical"
                        missing = await session.call_tool("get_shipment", {"shipment_id": "SHIP-999"})
                        assert missing.isError and "SHIP-470" in missing.content[0].text
                        investigated = await session.call_tool("investigate_incident", {"shipment_id": "SHIP-470"})
                        assert len(investigated.structuredContent["plans"]) == 3
                changed = await client.post("/demo/inventory", json={"incident_id": "SHIP-470", "available": 5})
                assert changed.status_code == 200
                alerts = (await client.get("/alerts")).json()["alerts"]
                assert [alert["incident_id"] for alert in alerts] == ["SHIP-470"]

    run(go())


def test_uploading_needs_the_operator_and_reading_the_template_does_not_need_a_pack(tmp_path):
    async def go():
        app = create_app(tmp_path / "guard.sqlite3", access_token=TOKEN)
        async with await client_for(app) as guest:
            refused = await guest.post("/scenario/packs", json=PACK)
            template = await guest.get("/scenario/packs/builtin")
        async with await client_for(app, TOKEN) as operator:
            accepted = await operator.post("/scenario/packs", json=PACK)
        return refused.status_code, template.status_code, accepted.status_code

    assert run(go()) == (401, 401, 201)
