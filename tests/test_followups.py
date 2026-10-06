"""Follow-up questions reuse the latest investigation instead of re-running it."""

import asyncio
import json

import httpx

from logiops.api import create_app
from logiops.replay import ReplayConverse

BASE_URL = "http://127.0.0.1:8000"


class CountingReplay(ReplayConverse):
    def __init__(self):
        self.calls = []

    async def converse(self, messages, system, tools):
        self.calls.append({"messages": messages, "system": system})
        return await super().converse(messages, system, tools)


def client(app, **headers):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE_URL, headers=headers)


def test_follow_up_answers_from_context_without_tools(tmp_path, monkeypatch):
    monkeypatch.setenv("LOGIOPS_AGENT_MODE", "replay")
    followups = CountingReplay()

    async def run():
        app = create_app(tmp_path / "ask.sqlite3", followup_client=followups)
        async with app.router.lifespan_context(app):
            async with client(app) as http:
                assert (await http.post("/incidents/SHIP-421/agent/investigate", json={})).status_code == 200
                response = await http.post("/incidents/SHIP-421/agent/ask", json={
                    "question": "How much is the reroute?",
                    "history": [{"role": "user", "text": "What's happening?"}, {"role": "assistant", "text": "Delayed 12 h."}],
                })
                assert response.status_code == 200, response.text
                body = response.json()
                assert "$80" in body["answer"] and "reroute" in body["answer"]
                assert body["tool_trace"] == [] and body["source_version"] == 1
                assert len(followups.calls) == 1
                text = followups.calls[0]["messages"][0]["content"][0]["text"]
                context = json.loads(text.split("<context>")[1].split("</context>")[0])
                assert {plan["kind"] for plan in context["plans"]} == {"wait", "reroute", "split-express"}
                assert context["latest_assessment"] and context["current_approval"] is None
                assert json.loads(text.split("<history>")[1].split("</history>")[0])[1]["text"] == "Delayed 12 h."

    asyncio.run(run())


def test_follow_up_needs_an_investigation_of_the_current_data(tmp_path, monkeypatch):
    monkeypatch.setenv("LOGIOPS_AGENT_MODE", "replay")

    async def run():
        app = create_app(tmp_path / "ask-409.sqlite3")
        async with app.router.lifespan_context(app):
            async with client(app) as http:
                before = await http.post("/incidents/SHIP-421/agent/ask", json={"question": "And the cost?"})
                assert before.status_code == 409
                await http.post("/incidents/SHIP-421/agent/investigate", json={})
                await http.post("/demo/inventory", json={"available": 11})
                after = await http.post("/incidents/SHIP-421/agent/ask", json={"question": "And the cost?"})
                assert after.status_code == 409  # the stored assessment is for older data

    asyncio.run(run())


def test_follow_ups_share_the_paid_agent_limit_and_cap_history(tmp_path, monkeypatch):
    monkeypatch.setenv("LOGIOPS_AGENT_MODE", "replay")
    token = "f" * 40

    async def run():
        app = create_app(tmp_path / "ask-limit.sqlite3", access_token=token, agent_limit_per_minute=2)
        async with app.router.lifespan_context(app):
            async with client(app, Authorization=f"Bearer {token}") as http:
                too_long = [{"role": "user", "text": "hi"}] * 9
                assert (await http.post("/incidents/SHIP-421/agent/ask", json={"question": "?", "history": too_long})).status_code == 422
                assert (await http.post("/incidents/SHIP-421/agent/investigate", json={})).status_code == 200
                assert (await http.post("/incidents/SHIP-421/agent/ask", json={"question": "wait?"})).status_code == 429

    asyncio.run(run())


def test_follow_up_after_execution_refers_to_the_executed_plans(tmp_path, monkeypatch):
    monkeypatch.setenv("LOGIOPS_AGENT_MODE", "replay")

    async def run():
        app = create_app(tmp_path / "ask-done.sqlite3")
        async with app.router.lifespan_context(app):
            async with client(app) as http:
                run_ = (await http.post("/incidents/SHIP-421/agent/investigate", json={})).json()
                plan = next(p for p in run_["plans"] if p["kind"] == "split-express")
                body = {"plan_id": plan["id"], "source_version": plan["source_version"]}
                await http.post("/incidents/SHIP-421/approvals", json={**body, "approved_by": "op"})
                await http.post("/incidents/SHIP-421/execute", json=body)
                response = await http.post("/incidents/SHIP-421/agent/ask", json={"question": "What did the express part cost?"})
                assert response.status_code == 200, response.text
                assert "$120" in response.json()["answer"] and response.json()["source_version"] == 1

    asyncio.run(run())
