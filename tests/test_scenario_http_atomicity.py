import asyncio

import httpx

from logiops.api import create_app
from logiops.scenario import INCIDENT_IDS, incident_ids, reset_registry
from tests.test_scenario_registry import pack_incident


def test_invalid_nested_source_answers_422_and_metrics_stay_available(tmp_path):
    async def work():
        app = create_app(tmp_path / "atomic.sqlite3")
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test") as client:
            response = await client.post("/scenario/packs", json={"version": 1, "incidents": [
                pack_incident(), pack_incident(id="SHIP-471", **{"options.0.sources": [{}]}),
            ]})
            assert response.status_code == 422
            assert incident_ids() == INCIDENT_IDS
            assert (await client.get("/metrics")).status_code == 200
            assert (await client.get("/incidents")).status_code == 200
    asyncio.run(work())


def test_a_pack_with_timestamp_like_text_is_seeded_and_the_inbox_and_metrics_keep_working(tmp_path, monkeypatch):
    monkeypatch.setenv("LOGIOPS_SCENARIO_ANCHOR", "2026-10-22")

    async def work():
        app = create_app(tmp_path / "text.sqlite3")
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test") as client:
            response = await client.post("/scenario/packs", json={"version": 1, "incidents": [
                pack_incident(title="2026-10-12T14:00 port strike"),
            ]})
            assert response.status_code == 201
            assert (await client.get("/incidents/SHIP-470")).json()["state"]["title"] == "2026-10-12T14:00 port strike"
            assert (await client.get("/metrics")).status_code == 200
    try:
        asyncio.run(work())
    finally:
        reset_registry()
