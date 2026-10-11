"""Interop with the official MCP client over Streamable HTTP."""

import asyncio

import httpx
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from logiops.api import create_app


BASE_URL = "http://127.0.0.1:8000"


def test_mcp_protocol_and_human_approval_boundary(tmp_path):
    async def run():
        app = create_app(tmp_path / "mcp.sqlite3")
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url=BASE_URL
            ) as http_client:
                async with streamable_http_client(
                    f"{BASE_URL}/mcp", http_client=http_client
                ) as (read, write, _):
                    async with ClientSession(read, write) as session:
                        initialized = await session.initialize()
                        assert initialized.protocolVersion == "2025-11-25"
                        listed = await session.list_tools()
                        names = {tool.name for tool in listed.tools}
                        assert {"get_shipment", "investigate_incident", "execute_approved_plan"} <= names
                        assert "approve_plan" not in names

                        shipment = await session.call_tool("get_shipment", {"shipment_id": "SHIP-421"})
                        assert shipment.structuredContent["units_on_delayed_route"] == 20
                        investigated = await session.call_tool(
                            "investigate_incident", {"shipment_id": "SHIP-421"}
                        )
                        plans = investigated.structuredContent["plans"]
                        assert len(plans) == 3
                        plan = next(item for item in plans if item["kind"] == "split-express")
                        arguments = {
                            "shipment_id": "SHIP-421",
                            "plan_id": plan["id"],
                            "source_version": plan["source_version"],
                        }
                        blocked = await session.call_tool("execute_approved_plan", arguments)
                        assert blocked.isError is True
                        assert not (await http_client.get("/incidents/SHIP-421")).json()["executions"]

                        approval = await http_client.post(
                            "/incidents/SHIP-421/approvals",
                            json={
                                "plan_id": plan["id"],
                                "source_version": plan["source_version"],
                                "approved_by": "demo-operator",
                            },
                        )
                        assert approval.status_code == 200
                        executed = await session.call_tool("execute_approved_plan", arguments)
                        assert executed.isError is False
                        assert executed.structuredContent["status"] == "verified_operationally"
                        repeated = await session.call_tool("execute_approved_plan", arguments)
                        assert repeated.structuredContent == executed.structuredContent
                        snapshot = (await http_client.get("/incidents/SHIP-421")).json()
                        assert len(snapshot["executions"]) == 1
                        status = (await session.call_tool(
                            "get_execution_status", {"shipment_id": "SHIP-421"}
                        )).structuredContent
                        assert status["status"] == "verified"
                        assert status["source_version"] == 2 and status["approvals"] == []
                        assert status["events"] and all(set(e) == {"sequence", "name", "recorded_at"} for e in status["events"])

    asyncio.run(run())


def test_mcp_rejects_untrusted_browser_origin(tmp_path):
    async def run():
        app = create_app(tmp_path / "origin.sqlite3")
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url=BASE_URL
            ) as client:
                response = await client.post(
                    "/mcp",
                    headers={
                        "Origin": "https://untrusted.example",
                        "Accept": "application/json, text/event-stream",
                        "MCP-Protocol-Version": "2025-11-25",
                    },
                    json={
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "initialize",
                        "params": {
                            "protocolVersion": "2025-11-25",
                            "capabilities": {},
                            "clientInfo": {"name": "test", "version": "1"},
                        },
                    },
                )
                assert response.status_code == 403

    asyncio.run(run())


def test_public_mcp_accepts_only_configured_cloudfront_host(tmp_path, monkeypatch):
    host = "d123example.cloudfront.net"
    monkeypatch.setenv("LOGIOPS_PUBLIC", "1")
    monkeypatch.setenv("LOGIOPS_PUBLIC_HOST", host)

    async def run():
        app = create_app(tmp_path / "public.sqlite3", access_token="a" * 40)
        async with app.router.lifespan_context(app):
            headers = {"Authorization": f"Bearer {'a' * 40}"}
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url=f"https://{host}", headers=headers
            ) as client:
                async with streamable_http_client(
                    f"https://{host}/mcp", http_client=client
                ) as (read, write, _):
                    async with ClientSession(read, write) as session:
                        assert (await session.initialize()).protocolVersion == "2025-11-25"
                        shipment = await session.call_tool("get_shipment", {"shipment_id": "SHIP-421"})
                        assert shipment.structuredContent["id"] == "SHIP-421"
                request = {
                    "jsonrpc": "2.0", "id": 1, "method": "initialize",
                    "params": {
                        "protocolVersion": "2025-11-25", "capabilities": {},
                        "clientInfo": {"name": "host-test", "version": "1"},
                    },
                }
                bad_host = await client.post(
                    "/mcp", headers={"Host": "attacker.example", "Accept": "application/json, text/event-stream"},
                    json=request,
                )
                assert bad_host.status_code == 421
                bad_origin = await client.post(
                    "/mcp", headers={"Origin": "https://attacker.example", "Accept": "application/json, text/event-stream"},
                    json=request,
                )
                assert bad_origin.status_code == 403
                good_origin = await client.post(
                    "/mcp", headers={"Origin": f"https://{host}", "Accept": "application/json, text/event-stream"},
                    json=request,
                )
                assert good_origin.status_code == 200

    asyncio.run(run())


def test_public_mode_requires_exact_host_and_token(tmp_path, monkeypatch):
    monkeypatch.setenv("LOGIOPS_PUBLIC", "1")
    with pytest.raises(RuntimeError, match="ACCESS_TOKEN"):
        create_app(tmp_path / "missing-token.sqlite3")
    with pytest.raises(RuntimeError, match="PUBLIC_HOST"):
        create_app(tmp_path / "missing-host.sqlite3", access_token="a" * 40)
    monkeypatch.setenv("LOGIOPS_PUBLIC_HOST", "*.cloudfront.net")
    with pytest.raises(RuntimeError, match="exact hostname"):
        create_app(tmp_path / "wildcard.sqlite3", access_token="a" * 40)


def test_tool_errors_carry_hints_so_the_model_can_correct_itself(tmp_path):
    async def run():
        app = create_app(tmp_path / "hints.sqlite3")
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE_URL) as http_client:
                async with streamable_http_client(f"{BASE_URL}/mcp", http_client=http_client) as (read, write, _):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        shipment = await session.call_tool("get_shipment", {"shipment_id": "ship-421"})
                        assert shipment.structuredContent["order_id"] == "ORD-421"
                        wrong = await session.call_tool("get_order", {"order_id": "SHIP-421"})
                        assert wrong.isError and "ORD-421" in wrong.content[0].text
                        stock = await session.call_tool("get_inventory", {"warehouse_id": "Arequipa", "sku": "laptop-01"})
                        assert stock.isError is False and stock.structuredContent["available"] == 12
                        for name in ("find_alternative_carriers", "investigate_incident", "get_execution_status"):
                            result = await session.call_tool(name, {"shipment_id": " ship-421 "})
                            assert result.isError is False, (name, result.content)

    asyncio.run(run())


def test_tools_serve_every_incident(tmp_path):
    async def run():
        app = create_app(tmp_path / "incidents.sqlite3")
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE_URL) as http_client:
                async with streamable_http_client(f"{BASE_URL}/mcp", http_client=http_client) as (read, write, _):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        names = {tool.name for tool in (await session.list_tools()).tools}
                        assert "list_incidents" in names and len(names) == 8
                        inbox = (await session.call_tool("list_incidents", {})).structuredContent["incidents"]
                        assert [item["incident_id"] for item in inbox][:2] == ["SHIP-433", "SHIP-460"]
                        assert inbox[0]["critical_units_at_risk"] == 12
                        shipment = (await session.call_tool("get_shipment", {"shipment_id": "SHIP-433"})).structuredContent
                        assert shipment["order_ids"] == ["ORD-433A", "ORD-433B"] and "order_id" not in shipment
                        assert shipment["warehouse_id"] is None
                        order = (await session.call_tool("get_order", {"order_id": "ord-433a"})).structuredContent
                        assert order["priority"] == "critical" and order["quantity"] == 12
                        hint = await session.call_tool("get_order", {"order_id": "SHIP-433"})
                        assert hint.isError and "ORD-433A and ORD-433B" in hint.content[0].text
                        stock = (await session.call_tool("get_inventory", {"warehouse_id": "lima", "sku": "ROUTER-05"})).structuredContent
                        assert stock["available"] == 25
                        none = await session.call_tool("get_inventory", {"warehouse_id": "cusco", "sku": "TABLET-03", "shipment_id": "SHIP-433"})
                        assert none.isError and "no local warehouse" in none.content[0].text
                        unknown = await session.call_tool("get_shipment", {"shipment_id": "SHIP-999"})
                        assert unknown.isError and "SHIP-460" in unknown.content[0].text

    asyncio.run(run())


def test_investigate_incident_reports_the_saved_preference(tmp_path):
    import json

    from logiops.mcp_server import create_mcp_server
    from logiops.preferences import PreferenceStore
    from logiops.service import LogiOpsService

    async def run():
        service = LogiOpsService(tmp_path / "prefs-mcp.sqlite3")
        preferences = PreferenceStore(tmp_path / "prefs-mcp.sqlite3")
        server = create_mcp_server(service, preferences=preferences)
        plain = (await server.call_tool("investigate_incident", {"shipment_id": "SHIP-460"}))[1]
        assert "operator_preferences" not in plain
        preferences.put("balanced", 250)
        result = (await server.call_tool("investigate_incident", {"shipment_id": "SHIP-460"}))[1]
        preference = result["operator_preferences"]
        assert preference["preferred_plan_id"].split(":")[2] == "priority-first" and preference["changes_pick"]
        assert json.dumps(preference)

    asyncio.run(run())
