"""A daily cap on live model calls, shared by every visitor (review, 2026-10-08)."""

import asyncio
import json
from datetime import datetime

import httpx
import pytest

import logiops.api as api_module
from logiops.api import create_app
from logiops.bedrock import BedrockError, BedrockUnavailable
from logiops.budget import BudgetedConverse, DailyModelBudget
from logiops.replay import ReplayConverse
from logiops.scenario import LIMA


def test_reservations_are_atomic_per_local_day_and_released(tmp_path):
    now = [datetime(2026, 10, 20, 23, 30, tzinfo=LIMA)]
    budget = DailyModelBudget(tmp_path / "budget.sqlite3", limit=10, clock=lambda: now[0])
    day = budget.reserve(8)
    assert day == "2026-10-20" and budget.used() == 8
    assert budget.reserve(4) is None and budget.used() == 8
    budget.release(day, 5)
    assert budget.used() == 3 and budget.reserve(4) == "2026-10-20"
    now[0] = datetime(2026, 10, 21, 0, 5, tzinfo=LIMA)
    budget.release(day, 4)
    assert budget.used() == 0 and budget.used("2026-10-20") == 3
    assert DailyModelBudget(tmp_path / "budget.sqlite3", limit=10, clock=lambda: now[0]).used("2026-10-20") == 3


def test_the_budget_creates_its_directory_and_reads_the_limit(tmp_path, monkeypatch):
    monkeypatch.setenv("LOGIOPS_DAILY_MODEL_CALLS", "7")
    assert DailyModelBudget.from_env(tmp_path / "new" / "dir" / "env.sqlite3").limit == 7
    monkeypatch.delenv("LOGIOPS_DAILY_MODEL_CALLS")
    assert DailyModelBudget.from_env(tmp_path / "env.sqlite3").limit == 150
    monkeypatch.setenv("LOGIOPS_DAILY_MODEL_CALLS", "lots")
    with pytest.raises(RuntimeError, match="LOGIOPS_DAILY_MODEL_CALLS"):
        DailyModelBudget.from_env(tmp_path / "env.sqlite3")


def test_concurrent_runs_never_exceed_the_cap_together(tmp_path):
    budget = DailyModelBudget(tmp_path / "race.sqlite3", limit=20)

    class Answers:
        async def converse(self, messages, system, tools, skill=None):
            await asyncio.sleep(0)
            return {"stopReason": "end_turn"}

    async def run_one():
        day = budget.reserve(8)
        if day is None:
            return 0
        client = BudgetedConverse(Answers(), budget, day, 8)
        try:
            for _ in range(8):
                await client.converse([], "", [])
        finally:
            client.settle()
        return client.calls

    async def all_runs():
        return await asyncio.gather(*(run_one() for _ in range(10)))

    made = asyncio.run(all_runs())
    assert sum(made) <= 20 and budget.used() == sum(made) == 16


def test_failed_calls_are_released_so_an_outage_never_looks_like_a_used_budget(tmp_path):
    budget = DailyModelBudget(tmp_path / "outage.sqlite3", limit=8)

    class Down:
        async def converse(self, messages, system, tools, skill=None):
            raise BedrockError("Bedrock Converse failed (AccessDeniedException)")

    for _ in range(5):
        day = budget.reserve(8)
        client = BudgetedConverse(Down(), budget, day, 8)
        with pytest.raises(BedrockError, match="AccessDenied"):
            asyncio.run(client.converse([], "", []))
        client.settle()
    assert budget.used() == 0


def test_a_call_cancelled_in_flight_stays_counted(tmp_path):
    budget = DailyModelBudget(tmp_path / "cancelled.sqlite3", limit=8)

    class Slow:
        async def converse(self, messages, system, tools, skill=None):
            await asyncio.sleep(60)

    async def run():
        day = budget.reserve(8)
        client = BudgetedConverse(Slow(), budget, day, 8)
        task = asyncio.create_task(client.converse([], "", []))
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        client.settle()

    asyncio.run(run())
    assert budget.used() == 1


def test_a_guest_run_holds_calls_in_both_pools_and_releases_both(tmp_path):
    budget = DailyModelBudget(tmp_path / "pool.sqlite3", limit=10, guest_limit=4)
    day = budget.reserve(3, guest=True)
    assert day and budget.used() == 3 and budget.used(guest=True) == 3
    assert budget.reserve(2, guest=True) is None and budget.used() == 3, "a refused guest hold leaves the shared row alone"
    assert budget.reserve(6) and budget.used() == 9 and budget.used(guest=True) == 3
    budget.release(day, 2, guest=True)
    assert budget.used() == 7 and budget.used(guest=True) == 1
    assert budget.reserve(4, guest=True) is None and budget.used() == 7, "the day's cap still binds a guest"
    assert budget.reserve(3, guest=True) and budget.used() == 10 and budget.used(guest=True) == 4


def test_the_guest_share_reads_its_limit_from_env(tmp_path, monkeypatch):
    monkeypatch.setenv("LOGIOPS_GUEST_DAILY_MODEL_CALLS", "12")
    assert DailyModelBudget.from_env(tmp_path / "g.sqlite3").guest_limit == 12
    monkeypatch.delenv("LOGIOPS_GUEST_DAILY_MODEL_CALLS")
    assert DailyModelBudget.from_env(tmp_path / "g2.sqlite3").guest_limit == 0
    monkeypatch.setenv("LOGIOPS_GUEST_DAILY_MODEL_CALLS", "lots")
    with pytest.raises(RuntimeError, match="LOGIOPS_GUEST_DAILY_MODEL_CALLS"):
        DailyModelBudget.from_env(tmp_path / "g3.sqlite3")


class FakeBedrock(ReplayConverse):
    """Stands in for Bedrock (no AWS): the replay answers, counted like real calls."""

    calls = 0

    async def converse(self, messages, system, tools, skill=None):
        FakeBedrock.calls += 1
        return await super().converse(messages, system, tools, skill)


def _session(tmp_path, monkeypatch, limit):
    monkeypatch.setenv("LOGIOPS_AGENT_MODE", "bedrock")
    monkeypatch.setenv("LOGIOPS_DAILY_MODEL_CALLS", str(limit))
    monkeypatch.setattr(api_module, "BedrockConverse", FakeBedrock)
    FakeBedrock.calls = 0

    async def run():
        app = create_app(tmp_path / f"live-{limit}.sqlite3")
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as http:
                first = (await http.post("/incidents/SHIP-421/agent/investigate", json={})).json()
                briefing = (await http.post("/agent/briefing", json={})).json()
                events = (await http.get("/incidents/SHIP-421")).json()["events"]
        recorded = next(event["data"] for event in events if event["name"] == "agent_investigation_completed")
        return first, briefing, recorded

    return asyncio.run(run())


def test_live_calls_are_counted_and_the_unused_reservation_released(tmp_path, monkeypatch):
    first, briefing, recorded = _session(tmp_path, monkeypatch, limit=150)
    assert first["mode"] == briefing["mode"] == "bedrock" and "fallback" not in first
    assert recorded["mode"] == "bedrock" and "fallback" not in recorded
    assert FakeBedrock.calls >= 4
    assert DailyModelBudget(tmp_path / "live-150.sqlite3", limit=150).used() == FakeBedrock.calls


def test_a_used_budget_falls_back_to_the_replay_and_says_so(tmp_path, monkeypatch):
    first, briefing, recorded = _session(tmp_path, monkeypatch, limit=4)
    assert FakeBedrock.calls == 0
    assert first["mode"] == briefing["mode"] == "replay" and first["fallback"] == briefing["fallback"] == "daily_budget"
    assert recorded["mode"] == "replay" and recorded["fallback"] == "daily_budget"
    assert first["recommended_plan_id"].startswith("SHIP-421:") and "Recommended plan" not in first["answer"]


class FlakyBedrock(ReplayConverse):
    """Answers the first `answers` calls, then fails the way the service does: throttled, refused or timed out."""

    answers = 2
    calls = 0
    error: BedrockError = BedrockUnavailable("Bedrock Converse failed (ThrottlingException); check model access and region")

    async def converse(self, messages, system, tools, skill=None):
        FlakyBedrock.calls += 1
        if FlakyBedrock.calls > FlakyBedrock.answers:
            raise FlakyBedrock.error
        return await super().converse(messages, system, tools, skill)


def _flaky(tmp_path, monkeypatch, error):
    monkeypatch.setenv("LOGIOPS_AGENT_MODE", "bedrock")
    monkeypatch.setenv("LOGIOPS_DAILY_MODEL_CALLS", "150")
    monkeypatch.setattr(api_module, "BedrockConverse", FlakyBedrock)
    monkeypatch.setattr(FlakyBedrock, "calls", 0)
    monkeypatch.setattr(FlakyBedrock, "error", error)
    return create_app(tmp_path / "outage.sqlite3")


def sse_kinds(text):
    return [line.removeprefix("event: ") for line in text.splitlines() if line.startswith("event: ")]


def test_an_outage_answers_every_job_from_the_replay_and_says_so(tmp_path, monkeypatch):
    app = _flaky(tmp_path, monkeypatch, FlakyBedrock.error)

    async def run():
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as http:
                streamed = (await http.post("/incidents/SHIP-421/agent/investigate/stream", json={})).text
                calls = FlakyBedrock.calls
                plain = (await http.post("/incidents/SHIP-433/agent/investigate", json={})).json()
                ask = (await http.post("/incidents/SHIP-421/agent/ask", json={"question": "How much is the reroute?", "history": []})).json()
                briefing = (await http.post("/agent/briefing", json={})).json()
                events = (await http.get("/incidents/SHIP-421")).json()["events"]
        return streamed, calls, plain, ask, briefing, events

    streamed, calls, plain, ask, briefing, events = asyncio.run(run())
    kinds = sse_kinds(streamed)
    restart = kinds.index("restart")
    assert restart > 0 and set(kinds[:restart]) == {"step"} and "step" in kinds[restart:] and kinds[-1] == "done"
    done = json.loads(streamed.rsplit("data: ", 1)[1])
    assert (done["mode"], done["fallback"]) == ("replay", "model_unavailable") and done["recommended_plan_id"].startswith("SHIP-421:")
    assert calls == 3 and FlakyBedrock.calls == 3, "after an outage the next jobs go straight to the replay"
    assert all((item["mode"], item["fallback"]) == ("replay", "model_unavailable") for item in (plain, ask, briefing))
    assert DailyModelBudget(tmp_path / "outage.sqlite3", limit=150).used() == 2, "the failed call is given back"
    failed = [event["data"] for event in events if event["name"] == "agent_run_failed"]
    completed = [event["data"] for event in events if event["name"] == "agent_investigation_completed"]
    assert [(item["job"], item["mode"], item["fallback"]) for item in failed] == [("investigate", "bedrock", "model_unavailable")]
    assert [(item["mode"], item["fallback"]) for item in completed] == [("replay", "model_unavailable")]


def test_the_agent_guards_still_fail_the_request_instead_of_falling_back(tmp_path, monkeypatch):
    app = _flaky(tmp_path, monkeypatch, BedrockError("Bedrock requested a disallowed tool: execute_approved_plan"))

    async def run():
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as http:
                response = await http.post("/incidents/SHIP-421/agent/investigate", json={})
                events = (await http.get("/incidents/SHIP-421")).json()["events"]
        return response, events

    response, events = asyncio.run(run())
    assert response.status_code == 502 and "disallowed tool" in response.json()["detail"]
    [failed] = [event["data"] for event in events if event["name"] == "agent_run_failed"]
    assert failed["mode"] == "bedrock" and "fallback" not in failed
    assert not [event for event in events if event["name"] == "agent_investigation_completed"]


def test_an_invalid_mode_is_rejected_even_with_a_custom_client(tmp_path, monkeypatch):
    monkeypatch.setenv("LOGIOPS_AGENT_MODE", "typo")

    async def run():
        app = create_app(tmp_path / "typo.sqlite3", ReplayConverse())
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as http:
                return await http.post("/incidents/SHIP-421/agent/investigate", json={})

    response = asyncio.run(run())
    assert response.status_code == 502 and "LOGIOPS_AGENT_MODE" in response.json()["detail"]
