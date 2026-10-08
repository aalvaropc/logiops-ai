"""A daily cap on live model calls, shared by every visitor (review, 2026-10-08)."""

import asyncio
from datetime import datetime, timedelta, timezone

import httpx

import logiops.api as api_module
from logiops.api import create_app
from logiops.budget import DailyModelBudget
from logiops.replay import ReplayConverse

LIMA = timezone(timedelta(hours=-5))


def test_calls_are_counted_per_lima_day(tmp_path):
    now = [datetime(2026, 10, 20, 23, 30, tzinfo=LIMA)]
    budget = DailyModelBudget(tmp_path / "budget.sqlite3", limit=2, clock=lambda: now[0])
    assert budget.available() and budget.spend() == 1 and budget.spend() == 2
    assert not budget.available() and budget.used() == 2
    # 00:30 in Lima is still the 20th in some zones and already the 21st here: a new day, a new budget.
    now[0] = datetime(2026, 10, 21, 0, 30, tzinfo=LIMA)
    assert budget.available() and budget.used() == 0
    # The count lives in the database, so a restart does not reset it.
    again = DailyModelBudget(tmp_path / "budget.sqlite3", limit=2, clock=lambda: now[0])
    again.spend()
    assert again.used() == 1 and DailyModelBudget(tmp_path / "budget.sqlite3", limit=2, clock=lambda: now[0]).used() == 1


def test_the_limit_comes_from_the_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("LOGIOPS_DAILY_MODEL_CALLS", "7")
    assert DailyModelBudget.from_env(tmp_path / "env.sqlite3").limit == 7
    monkeypatch.delenv("LOGIOPS_DAILY_MODEL_CALLS")
    assert DailyModelBudget.from_env(tmp_path / "env.sqlite3").limit == 150


class FakeBedrock(ReplayConverse):
    """Stands in for Bedrock (no AWS): the replay answers, counted like real calls."""

    calls = 0

    async def converse(self, messages, system, tools):
        FakeBedrock.calls += 1
        return await super().converse(messages, system, tools)


def _investigate(tmp_path, monkeypatch, limit):
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
        return first, briefing

    return asyncio.run(run())


def test_live_calls_are_counted_against_the_daily_budget(tmp_path, monkeypatch):
    first, briefing = _investigate(tmp_path, monkeypatch, limit=150)
    assert first["mode"] == "bedrock" and briefing["mode"] == "bedrock" and FakeBedrock.calls >= 4
    budget = DailyModelBudget(tmp_path / "live-150.sqlite3", limit=150)
    assert budget.used() == FakeBedrock.calls


def test_a_used_up_budget_falls_back_to_a_labelled_replay(tmp_path, monkeypatch):
    first, briefing = _investigate(tmp_path, monkeypatch, limit=0)
    assert FakeBedrock.calls == 0
    assert first["mode"] == briefing["mode"] == "replay (daily live budget used)"
    assert first["answer"].rstrip().splitlines()[-1].startswith("Recommended plan: SHIP-421:")
