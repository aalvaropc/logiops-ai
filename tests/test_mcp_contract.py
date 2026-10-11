"""The MCP contract a host relies on: titles, annotations, described inputs, typed outputs, hints."""

import asyncio

import httpx
import jsonschema
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from logiops import __version__
from logiops.api import create_app
from logiops.mcp_server import normalized_incident
from logiops.scenario import INCIDENT_IDS

BASE_URL = "http://127.0.0.1:8000"
READ_ONLY = {"list_incidents", "get_shipment", "get_order", "get_inventory", "find_alternative_carriers", "get_execution_status"}


def _session(tmp_path, work):
    async def run():
        app = create_app(tmp_path / "contract.sqlite3")
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE_URL) as http_client:
                async with streamable_http_client(f"{BASE_URL}/mcp", http_client=http_client) as (read, write, _):
                    async with ClientSession(read, write) as session:
                        initialized = await session.initialize()
                        return await work(session, initialized, http_client)

    return asyncio.run(run())


def test_every_tool_declares_title_annotations_described_inputs_and_an_output_schema(tmp_path):
    async def work(session, initialized, _http):
        return initialized, (await session.list_tools()).tools

    initialized, tools = _session(tmp_path, work)
    assert initialized.serverInfo.name == "LogiOps AI" and initialized.serverInfo.version == __version__
    assert "human-only" in initialized.instructions and "projected" in initialized.instructions
    assert initialized.serverInfo.websiteUrl.startswith("https://") and initialized.serverInfo.icons[0].mimeType == "image/svg+xml"
    assert len(tools) == 8
    for tool in tools:
        assert tool.title and tool.annotations is not None, tool.name
        assert tool.outputSchema and tool.outputSchema["type"] == "object", tool.name
        for name, schema in tool.inputSchema.get("properties", {}).items():
            assert schema.get("description") or any(item.get("description") for item in schema.get("anyOf", [])), (tool.name, name)
        assert tool.annotations.readOnlyHint is (tool.name in READ_ONLY), tool.name
        assert tool.annotations.openWorldHint is False and tool.annotations.idempotentHint is True, tool.name
    execute = next(tool for tool in tools if tool.name == "execute_approved_plan")
    assert execute.annotations.destructiveHint is True and execute.meta["ui"]["visibility"] == ["model"]
    investigate = next(tool for tool in tools if tool.name == "investigate_incident")
    assert investigate.annotations.destructiveHint is False and investigate.meta["ui"]["resourceUri"].startswith("ui://")


def test_structured_content_conforms_to_each_output_schema_on_every_incident(tmp_path):
    async def work(session, _initialized, http):
        schemas = {tool.name: tool.outputSchema for tool in (await session.list_tools()).tools}
        checked = []

        async def call(name, arguments):
            result = await session.call_tool(name, arguments)
            assert result.isError is False, (name, arguments, result.content)
            jsonschema.validate(result.structuredContent, schemas[name])
            checked.append(name)
            return result.structuredContent

        await call("list_incidents", {})
        for incident_id in INCIDENT_IDS:
            shipment = await call("get_shipment", {"shipment_id": incident_id})
            for order_id in shipment["order_ids"]:
                await call("get_order", {"order_id": order_id})
            if shipment["warehouse_id"]:
                await call("get_inventory", {"warehouse_id": shipment["warehouse_id"], "sku": shipment["sku"],
                                             "shipment_id": incident_id})
            await call("find_alternative_carriers", {"shipment_id": incident_id})
            plans = await call("investigate_incident", {"shipment_id": incident_id})
            await call("get_execution_status", {"shipment_id": incident_id})
        plan = plans["plans"][0]
        approved = await http.post(f"/incidents/{incident_id}/approvals", json={
            "plan_id": plan["id"], "source_version": plan["source_version"], "approved_by": "operator"})
        assert approved.status_code == 200
        executed = await call("execute_approved_plan", {"shipment_id": incident_id, "plan_id": plan["id"],
                                                        "source_version": plan["source_version"]})
        again = await call("execute_approved_plan", {"shipment_id": incident_id, "plan_id": plan["id"],
                                                     "source_version": plan["source_version"]})
        return checked, executed, again

    checked, executed, again = _session(tmp_path, work)
    assert set(checked) == READ_ONLY | {"investigate_incident", "execute_approved_plan"}
    assert executed == again and executed["delivery_status"] == "projected"


@pytest.mark.parametrize("spoken", ["SHIP-433", "ship-433", "Ship 433", "433", " case 433 ", "shipment #433", "incident 433"])
def test_incident_ids_are_understood_the_way_people_say_them(spoken):
    assert normalized_incident(spoken) == "SHIP-433"


def test_every_failure_says_what_to_do_next(tmp_path):
    async def work(session, _initialized, _http):
        plans = (await session.call_tool("investigate_incident", {"shipment_id": "433"})).structuredContent["plans"]
        failures = {
            "unknown incident": await session.call_tool("get_shipment", {"shipment_id": "SHIP-999"}),
            "unknown order": await session.call_tool("get_order", {"order_id": "ORD-999"}),
            "unknown warehouse": await session.call_tool("get_inventory", {"warehouse_id": "cusco", "sku": "X"}),
            "not approved": await session.call_tool("execute_approved_plan", {
                "shipment_id": "SHIP-433", "plan_id": plans[0]["id"], "source_version": plans[0]["source_version"]}),
        }
        invalid = await session.call_tool("execute_approved_plan", {
            "shipment_id": "SHIP-433", "plan_id": plans[0]["id"], "source_version": 0})
        return failures, invalid

    failures, invalid = _session(tmp_path, work)
    for case, result in failures.items():
        assert result.isError is True and "Next step:" in result.content[0].text, case
    assert "SHIP-433" in failures["unknown incident"].content[0].text
    assert "no tool can approve" in failures["not approved"].content[0].text
    assert invalid.isError is True and "source_version" in invalid.content[0].text
