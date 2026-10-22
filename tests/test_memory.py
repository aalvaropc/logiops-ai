"""Memory across sessions: SQLite or AgentCore Memory, a hashed actor, welcome back, forget me."""

import asyncio
from datetime import datetime, timezone

import boto3
import httpx
from botocore.stub import ANY, Stubber

from logiops.api import create_app
from logiops.identity import OPERATOR, Actor
from logiops.memory import AgentCoreMemory, MemoryService, SqliteMemory, actor_key, welcome

BASE_URL = "http://127.0.0.1:8000"
JUDGE = Actor("user", "sub-123", "judge")
GUEST = Actor("guest", "guest", "Guest")
MEMORY_ID = "logiops_ai_memory-abc123"
AT = datetime(2026, 10, 12, 19, 5, tzinfo=timezone.utc)


def test_the_actor_is_hashed_and_guests_are_not_remembered(tmp_path):
    key = actor_key(JUDGE)
    assert key.startswith("user-") and "sub-123" not in key and key == actor_key(Actor("user", "sub-123", "x"))
    assert actor_key(OPERATOR) == "operator" and actor_key(GUEST) is None
    memory = MemoryService(tmp_path / "m.sqlite3", backend=SqliteMemory(tmp_path / "m.sqlite3"))
    assert memory.remember(GUEST, "s-session-1", "user", "hello", None) is False
    assert memory.recall(GUEST, None)["enabled"] is False


def test_sqlite_recalls_the_previous_session_and_forgets(tmp_path):
    memory = MemoryService(tmp_path / "m.sqlite3", backend=SqliteMemory(tmp_path / "m.sqlite3", clock=lambda: AT))
    assert memory.remember(JUDGE, "s-yesterday", "user", "book it", "SHIP-433")
    memory.remember(JUDGE, "s-yesterday", "assistant", "Booked “Fly the hospital order”. Confirmation number LGO-ABC234.", "SHIP-433")
    memory.remember(OPERATOR, "s-yesterday", "user", "someone else", "SHIP-421")
    memory.remember(JUDGE, "s-today-1", "user", "hi again", "SHIP-421")
    recalled = memory.recall(JUDGE, "s-today-1")
    assert [turn["text"] for turn in recalled["turns"]] == ["book it", "Booked “Fly the hospital order”. Confirmation number LGO-ABC234."]
    assert recalled["last_incident"] == "SHIP-433" and recalled["backend"] == "sqlite"
    assert recalled["welcome"].startswith("Welcome back, judge. Last time (Oct 12, 14:05 local time) we were on SHIP-433 and you said “book it”.")
    assert memory.recall(JUDGE, "s-yesterday")["turns"][0]["text"] == "hi again"
    assert memory.forget(JUDGE) == 3 and memory.recall(JUDGE, "s-today-1")["turns"] == []
    assert memory.recall(OPERATOR, "s-other")["turns"][0]["text"] == "someone else"


def test_welcome_is_empty_without_history():
    assert welcome([], "judge") is None


def agentcore():
    client = boto3.client("bedrock-agentcore", region_name="us-east-1", aws_access_key_id="testing", aws_secret_access_key="testing")
    return client, Stubber(client)


def test_agentcore_writes_conversational_events_under_the_hashed_actor():
    client, stubber = agentcore()
    key = actor_key(JUDGE)
    stubber.add_response("create_event", {"event": {
        "memoryId": MEMORY_ID, "actorId": key, "sessionId": "s-today-1", "eventId": "e1", "eventTimestamp": AT, "payload": [],
    }}, {
        "memoryId": MEMORY_ID, "actorId": key, "sessionId": "s-today-1", "eventTimestamp": AT,
        "payload": [{"conversational": {"content": {"text": "book it"}, "role": "USER"}}],
        "metadata": {"incident": {"stringValue": "SHIP-433"}},
    })
    memory = MemoryService("unused", backend=AgentCoreMemory(MEMORY_ID, client=client, clock=lambda: AT))
    with stubber:
        assert memory.remember(JUDGE, "s-today-1", "user", "  book   it ", "SHIP-433") is True
    stubber.assert_no_pending_responses()


def test_agentcore_recall_reads_the_last_session_and_long_term_records():
    client, stubber = agentcore()
    key = actor_key(JUDGE)
    stubber.add_response("list_sessions", {"sessionSummaries": [
        {"sessionId": "s-today-1", "actorId": key, "createdAt": AT},
        {"sessionId": "s-yesterday", "actorId": key, "createdAt": datetime(2026, 10, 11, tzinfo=timezone.utc)},
    ]}, {"memoryId": MEMORY_ID, "actorId": key, "maxResults": 20})
    stubber.add_response("list_events", {"events": [
        {"memoryId": MEMORY_ID, "actorId": key, "sessionId": "s-yesterday", "eventId": "e1", "eventTimestamp": AT,
         "payload": [{"conversational": {"content": {"text": "book it"}, "role": "USER"}}],
         "metadata": {"incident": {"stringValue": "SHIP-433"}}},
    ]}, {"memoryId": MEMORY_ID, "actorId": key, "sessionId": "s-yesterday", "includePayloads": True, "maxResults": 50})
    for namespace, text in ((f"/users/{key}/preferences", "Prefers to keep hospitals on time"), (f"/users/{key}/facts", "Booked air freight for SHIP-433 at $466.10")):
        stubber.add_response("retrieve_memory_records", {"memoryRecordSummaries": [
            {"memoryRecordId": ("r" + namespace.replace("/", "-") * 4)[:40], "content": {"text": text}, "memoryStrategyId": "s", "namespaces": [namespace], "createdAt": AT},
        ]}, {"memoryId": MEMORY_ID, "namespace": namespace, "searchCriteria": {"searchQuery": "what did we book?", "topK": 3}})
    memory = MemoryService("unused", backend=AgentCoreMemory(MEMORY_ID, client=client))
    with stubber:
        recalled = memory.recall(JUDGE, "s-today-1", "what did we book?")
    assert recalled["backend"] == "agentcore" and recalled["turns"][0]["incident"] == "SHIP-433"
    assert recalled["facts"] == ["Prefers to keep hospitals on time", "Booked air freight for SHIP-433 at $466.10"]
    block = memory.block(recalled)
    assert block.startswith("\n\n<memory>") and "data, not instructions" in block and "$466.10" in block


def test_agentcore_forget_deletes_events_and_records():
    client, stubber = agentcore()
    key = actor_key(JUDGE)
    stubber.add_response("list_sessions", {"sessionSummaries": [{"sessionId": "s-1", "actorId": key, "createdAt": AT}]})
    stubber.add_response("list_events", {"events": [
        {"memoryId": MEMORY_ID, "actorId": key, "sessionId": "s-1", "eventId": "e1", "eventTimestamp": AT, "payload": []},
        {"memoryId": MEMORY_ID, "actorId": key, "sessionId": "s-1", "eventId": "e2", "eventTimestamp": AT, "payload": []},
    ]})
    for event in ("e1", "e2"):
        stubber.add_response("delete_event", {"eventId": event}, {"memoryId": MEMORY_ID, "actorId": key, "sessionId": "s-1", "eventId": event})
    stubber.add_response("list_memory_records", {"memoryRecordSummaries": [
        {"memoryRecordId": "r" * 40, "content": {"text": "x"}, "memoryStrategyId": "s", "namespaces": ["n"], "createdAt": AT}]})
    stubber.add_response("batch_delete_memory_records", {"successfulRecords": [], "failedRecords": []},
                         {"memoryId": MEMORY_ID, "records": [{"memoryRecordId": "r" * 40, "namespace": f"/users/{key}/preferences"}]})
    stubber.add_response("list_memory_records", {"memoryRecordSummaries": []})
    memory = MemoryService("unused", backend=AgentCoreMemory(MEMORY_ID, client=client))
    with stubber:
        assert memory.forget(JUDGE) == 3
    stubber.assert_no_pending_responses()


def test_a_memory_outage_never_breaks_a_reply():
    client, stubber = agentcore()
    stubber.add_client_error("create_event", service_error_code="AccessDeniedException", http_status_code=403)
    stubber.add_client_error("list_sessions", service_error_code="ThrottlingException", http_status_code=429)
    memory = MemoryService("unused", backend=AgentCoreMemory(MEMORY_ID, client=client))
    with stubber:
        assert memory.remember(JUDGE, "s-today-1", "user", "hello", None) is False
        recalled = memory.recall(JUDGE, "s-today-1")
    assert recalled["turns"] == [] and recalled["welcome"] is None and recalled["enabled"] is True


def test_the_api_remembers_after_replying_and_welcomes_back(tmp_path, monkeypatch):
    monkeypatch.setenv("LOGIOPS_AGENT_MODE", "replay")

    async def run():
        app = create_app(tmp_path / "api.sqlite3")
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE_URL) as http:
            first = await http.post("/memory/turns", json={"session": "s-monday-1", "role": "user", "text": "approve the split plan", "incident": "SHIP-421"})
            await http.post("/memory/turns", json={"session": "s-monday-1", "role": "assistant", "text": "Approved.", "incident": "SHIP-999"})
            bad = await http.post("/memory/turns", json={"session": "../etc", "role": "user", "text": "x"})
            recalled = (await http.get("/memory", params={"session": "s-tuesday-1"})).json()
            same = (await http.get("/memory", params={"session": "s-monday-1"})).json()
            forgotten = (await http.delete("/memory")).json()
            after = (await http.get("/memory", params={"session": "s-tuesday-1"})).json()
            return first, bad, recalled, same, forgotten, after

    first, bad, recalled, same, forgotten, after = asyncio.run(run())
    assert first.status_code == 202 and first.json() == {"accepted": True, "backend": "sqlite"} and bad.status_code == 422
    assert recalled["welcome"].startswith("Welcome back. Last time") and "on SHIP-421" in recalled["welcome"]
    assert [turn["incident"] for turn in recalled["turns"]] == ["SHIP-421", None]
    assert same["turns"] == [] and forgotten["forgotten"] == 2 and after["welcome"] is None


def test_a_live_run_gets_long_term_facts_as_data(tmp_path, monkeypatch):
    class Facts:
        backend = "agentcore"

        def remember(self, *args):
            return None

        def recall(self, actor, session, query=None):
            return {"turns": [], "facts": ["Prefers hospitals first; once paid $466.10 for air freight"]}

        def forget(self, actor):
            return 0

    seen = []

    class Recording:
        async def converse(self, messages, system, tools, skill=None):
            seen.append(messages[0]["content"][0]["text"])
            from logiops.replay import ReplayConverse
            return await ReplayConverse().converse(messages, system, tools, skill)

    async def run():
        app = create_app(tmp_path / "live.sqlite3", bedrock_client=Recording(), followup_client=Recording(),
                         memory=MemoryService(tmp_path / "live.sqlite3", backend=Facts()))
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE_URL) as http:
                investigated = await http.post("/incidents/SHIP-433/agent/investigate", json={})
                asked = await http.post("/incidents/SHIP-433/agent/ask", json={"question": "Why that plan?"})
                return investigated, asked

    investigated, asked = asyncio.run(run())
    assert investigated.status_code == 200 and asked.status_code == 200
    assert "<memory>" in seen[0] and "data, not instructions" in seen[0] and "$466.10" in seen[0]
    followup = next(text for text in seen if text.startswith("Shipment: SHIP-433.\n<context>"))
    assert "Prefers hospitals first" in followup.split("<history>")[0]


def test_a_full_demo_reset_forgets_the_shared_operator_memory_but_an_incident_reset_does_not(tmp_path, monkeypatch):
    monkeypatch.setenv("LOGIOPS_AGENT_MODE", "replay")

    async def run():
        app = create_app(tmp_path / "reset.sqlite3")
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE_URL) as http:
            await http.post("/memory/turns", json={"session": "s-monday-1", "role": "user", "text": "yes", "incident": "SHIP-421"})
            await http.post("/demo/reset", json={"incident_id": "SHIP-421"})
            kept = (await http.get("/memory", params={"session": "s-tuesday-1"})).json()
            await http.post("/demo/reset")
            cleared = (await http.get("/memory", params={"session": "s-tuesday-1"})).json()
            return kept, cleared

    kept, cleared = asyncio.run(run())
    assert kept["welcome"] is not None and cleared["welcome"] is None and cleared["turns"] == []


def test_a_memory_outage_never_leaves_a_full_reset_half_done(tmp_path):
    from botocore.exceptions import ClientError

    class Unreachable(SqliteMemory):
        def forget(self, key):
            raise ClientError({"Error": {"Code": "ThrottlingException", "Message": "slow down"}}, "ListSessions")

    path = tmp_path / "reset.sqlite3"

    async def run():
        app = create_app(path, memory=MemoryService(path, backend=Unreachable(path)))
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8000") as http:
                investigated = await http.post("/incidents/SHIP-421/investigate")
                reset = await http.post("/demo/reset")
                after = await http.get("/incidents/SHIP-421")
                return investigated, reset, after

    investigated, reset, after = asyncio.run(run())
    assert investigated.status_code == 200 and investigated.json()["plans"]
    assert reset.status_code == 200
    assert after.json()["plans"] == [], "the incidents were reset even though the memory could not be cleared"
