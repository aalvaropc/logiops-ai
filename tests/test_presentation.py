"""What a person reads and hears never carries internal plan ids, raw timestamps or the pick line."""

import asyncio
import re

import httpx
import pytest

from logiops.api import create_app
from logiops.presentation import customer_text
from logiops.scenario import INCIDENT_IDS, build_plans, seed_state

INTERNAL_ID = re.compile(r"SHIP-\d+:[0-9a-f-]{8,}", re.I)
ISO = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}")


def test_plan_ids_become_labels_times_become_local_and_the_pick_line_goes():
    plans = build_plans(seed_state("SHIP-421"), 1)
    split = next(plan for plan in plans if plan["kind"] == "split-express")
    raw = (f"I recommend `{split['id']}` ({split['label']}): on time, ETA 2026-10-12T13:00:00-05:00, "
           f"or 2026-10-12T18:00Z. Unknown SHIP-421:00000000-0000:other:v9.\n\n\n**Recommended plan:** `{split['id']}`")
    shown = customer_text(raw, plans)
    assert shown == (f"I recommend “{split['label']}”: on time, ETA Oct 12, 13:00 local time, "
                     "or Oct 12, 13:00 local time. Unknown the plan.")
    assert customer_text("Arrives 2026-10-12T13:00:00-05:00 local time.", plans) == "Arrives Oct 12, 13:00 local time."
    assert customer_text("", plans) == "" and customer_text("No plans here.", []) == "No plans here."


@pytest.mark.parametrize("incident_id", INCIDENT_IDS)
def test_replay_answers_spoken_lines_and_reloads_are_customer_text(tmp_path, monkeypatch, incident_id):
    monkeypatch.setenv("LOGIOPS_AGENT_MODE", "replay")

    async def run():
        app = create_app(tmp_path / "shown.sqlite3", agent_limit_per_minute=100)
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as http:
                investigated = (await http.post(f"/incidents/{incident_id}/agent/investigate", json={})).json()
                asked = (await http.post(f"/incidents/{incident_id}/agent/ask",
                                         json={"question": "Why not the cheaper one?", "history": []})).json()
                briefing = (await http.post("/agent/briefing", json={"question": "Any delays today?"})).json()
                snapshot = (await http.get(f"/incidents/{incident_id}")).json()
        return investigated, asked, briefing, snapshot

    investigated, asked, briefing, snapshot = asyncio.run(run())
    for run_ in (investigated, asked, briefing):
        for text in (run_["answer"], run_["spoken"]):
            assert text and not INTERNAL_ID.search(text) and not ISO.search(text), text
            assert "Recommended plan" not in text
    assert investigated["recommended_plan_id"] in {plan["id"] for plan in investigated["plans"]}
    event = [item for item in snapshot["events"] if item["name"] == "agent_investigation_completed"][-1]["data"]
    assert event["answer"].rstrip().endswith(f"Recommended plan: {investigated['recommended_plan_id']}")
    assert event["display_answer"] == investigated["answer"]
