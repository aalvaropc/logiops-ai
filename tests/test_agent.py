"""Bedrock receives real MCP tool results but cannot approve or execute."""

import asyncio
from copy import deepcopy

import httpx

from logiops.api import create_app


BASE_URL = "http://127.0.0.1:8000"


class FakeConverse:
    def __init__(self):
        self.calls = []

    async def converse(self, messages, system, tools):
        self.calls.append({"messages": deepcopy(messages), "system": system, "tools": deepcopy(tools)})
        if len(self.calls) == 1:
            return {
                "stopReason": "tool_use",
                "usage": {"inputTokens": 120, "outputTokens": 90},
                "output": {"message": {"role": "assistant", "content": [
                    {"toolUse": {"toolUseId": "s1", "name": "get_shipment", "input": {"shipment_id": "SHIP-421"}}},
                    {"toolUse": {"toolUseId": "o1", "name": "get_order", "input": {"order_id": "ORD-421"}}},
                    {"toolUse": {"toolUseId": "i1", "name": "get_inventory", "input": {"warehouse_id": "arequipa", "sku": "LAPTOP-01"}}},
                    {"toolUse": {"toolUseId": "c1", "name": "find_alternative_carriers", "input": {"shipment_id": "SHIP-421"}}},
                    {"toolUse": {"toolUseId": "p1", "name": "investigate_incident", "input": {"shipment_id": "SHIP-421"}}},
                ]}},
            }
        return {
            "stopReason": "end_turn",
            "usage": {"inputTokens": 800, "outputTokens": 100},
            "output": {"message": {"role": "assistant", "content": [
                {"text": "The shipment is delayed. Compare three plans; I recommend split-express. Delivery remains projected. Human approval is required."}
            ]}},
        }


def test_agent_uses_mcp_and_persists_trace(tmp_path):
    async def run():
        fake = FakeConverse()
        app = create_app(tmp_path / "agent.sqlite3", fake)
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE_URL) as http:
                response = await http.post("/incidents/SHIP-421/agent/investigate", json={})
                assert response.status_code == 200, response.text
                body = response.json()
                assert len(body["plans"]) == 3
                assert body["source_version"] == 1
                assert body["usage"] == {"inputTokens": 920, "outputTokens": 190}
                assert {step["tool"] for step in body["tool_trace"]} == {
                    "get_shipment", "get_order", "get_inventory",
                    "find_alternative_carriers", "investigate_incident",
                }
                assert all(not step["is_error"] for step in body["tool_trace"])
                tool_names = {tool["toolSpec"]["name"] for tool in fake.calls[0]["tools"]}
                assert "execute_approved_plan" not in tool_names
                assert "approve_plan" not in tool_names
                tool_results = fake.calls[1]["messages"][-1]["content"]
                assert len(tool_results) == 5
                plans_result = next(
                    result["toolResult"]["content"][0]["json"]
                    for result in tool_results if result["toolResult"]["toolUseId"] == "p1"
                )
                assert len(plans_result["plans"]) == 3
                snapshot = (await http.get("/incidents/SHIP-421")).json()
                assert snapshot["state"]["status"] == "investigated"
                assert not snapshot["approvals"] and not snapshot["executions"]
                assert snapshot["events"][-1]["name"] == "agent_investigation_completed"
                assert snapshot["events"][-1]["data"]["tool_trace"] == body["tool_trace"]

    asyncio.run(run())


def test_agent_rejects_model_requested_execution(tmp_path):
    class UnsafeConverse:
        async def converse(self, messages, system, tools):
            return {
                "stopReason": "tool_use",
                "output": {"message": {"role": "assistant", "content": [
                    {"toolUse": {"toolUseId": "x1", "name": "execute_approved_plan", "input": {
                        "shipment_id": "SHIP-421", "plan_id": "P1", "source_version": 1,
                    }}}
                ]}},
            }

    async def run():
        app = create_app(tmp_path / "unsafe.sqlite3", UnsafeConverse())
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE_URL) as http:
                response = await http.post("/incidents/SHIP-421/agent/investigate", json={})
                assert response.status_code == 502
                assert "disallowed tool" in response.json()["detail"]
                snapshot = (await http.get("/incidents/SHIP-421")).json()
                assert snapshot["state"]["status"] == "detected"
                assert not snapshot["executions"]

    asyncio.run(run())


def test_explicit_replay_produces_three_live_plans_without_aws(tmp_path, monkeypatch):
    monkeypatch.setenv("LOGIOPS_AGENT_MODE", "replay")

    async def run():
        app = create_app(tmp_path / "replay.sqlite3")
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE_URL) as http:
                response = await http.post("/incidents/SHIP-421/agent/investigate", json={})
                assert response.status_code == 200, response.text
                body = response.json()
                assert body["mode"] == "replay"
                assert len(body["plans"]) == 3
                assert body["usage"] == {"inputTokens": 0, "outputTokens": 0}
                assert body["plans"][2]["id"] in body["answer"]
                assert len(body["tool_trace"]) == 5

    asyncio.run(run())


def test_public_agent_can_reach_internal_mcp_with_token(tmp_path, monkeypatch):
    monkeypatch.setenv("LOGIOPS_PUBLIC", "1")
    monkeypatch.setenv("LOGIOPS_PUBLIC_HOST", "d123example.cloudfront.net")
    monkeypatch.setenv("LOGIOPS_AGENT_MODE", "replay")

    async def run():
        app = create_app(tmp_path / "public-agent.sqlite3", access_token="a" * 40)
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="https://d123example.cloudfront.net",
                headers={"Authorization": f"Bearer {'a' * 40}"},
            ) as http:
                response = await http.post("/incidents/SHIP-421/agent/investigate", json={})
                assert response.status_code == 200, response.text
                assert len(response.json()["plans"]) == 3

    asyncio.run(run())


def test_agent_fails_clearly_when_the_deadline_passes(tmp_path):
    from logiops.agent import investigate_with_bedrock
    from logiops.bedrock import BedrockError

    class SlowConverse:
        async def converse(self, messages, system, tools):
            await asyncio.sleep(5)

    async def run():
        app = create_app(tmp_path / "slow.sqlite3")
        async with app.router.lifespan_context(app):
            try:
                await investigate_with_bedrock(app, SlowConverse(), "SHIP-421", "?", deadline_seconds=0.2)
            except BedrockError as exc:
                return str(exc)
        return "no error"

    assert "did not finish within" in asyncio.run(run())


def test_truncated_final_answer_is_kept_but_flagged(tmp_path):
    class TruncatingConverse(FakeConverse):
        async def converse(self, messages, system, tools):
            response = await super().converse(messages, system, tools)
            if response["stopReason"] == "end_turn":
                response["stopReason"] = "max_tokens"
            return response

    async def run():
        app = create_app(tmp_path / "truncated.sqlite3", TruncatingConverse())
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE_URL) as http:
                response = await http.post("/incidents/SHIP-421/agent/investigate", json={})
                assert response.status_code == 200, response.text
                assert response.json()["truncated"] is True

    asyncio.run(run())
