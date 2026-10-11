"""A daily cap on live model calls, shared by every visitor (review, 2026-10-08)."""

import asyncio
from datetime import datetime

import httpx
import pytest

import logiops.api as api_module
from logiops.api import create_app
from logiops.bedrock import BedrockError
from logiops.budget import BudgetedConverse, DailyModelBudget
from logiops.replay import ReplayConverse
from logiops.scenario import LIMA


def test_reservations_are_atomic_per_lima_day_and_released(tmp_path):
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
        async def converse(self, messages, system, tools):
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
        async def converse(self, messages, system, tools):
            raise BedrockError("Bedrock Converse failed (AccessDeniedException)")

    for _ in range(5):
        day = budget.reserve(8)
        client = BudgetedConverse(Down(), budget, day, 8)
        with pytest.raises(BedrockError, match="AccessDenied"):
            asyncio.run(client.converse([], "", []))
        client.settle()
    assert budget.used() == 0


class FakeBedrock(ReplayConverse):
    """Stands in for Bedrock (no AWS): the replay answers, counted like real calls."""

    calls = 0

    async def converse(self, messages, system, tools):
        FakeBedrock.calls += 1
        return await super().converse(messages, system, tools)


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


def test_an_invalid_mode_is_rejected_even_with_a_custom_client(tmp_path, monkeypatch):
    monkeypatch.setenv("LOGIOPS_AGENT_MODE", "typo")

    async def run():
        app = create_app(tmp_path / "typo.sqlite3", ReplayConverse())
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as http:
                return await http.post("/incidents/SHIP-421/agent/investigate", json={})

    response = asyncio.run(run())
    assert response.status_code == 502 and "LOGIOPS_AGENT_MODE" in response.json()["detail"]
