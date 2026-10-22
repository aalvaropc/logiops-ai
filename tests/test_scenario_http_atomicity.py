import asyncio
import sqlite3

import httpx

from logiops.api import create_app
from logiops.scenario import INCIDENT_IDS, INCIDENTS, KIND_LABELS, PLAYBOOKS, incident_ids, reset_registry
from logiops.service import LogiOpsService
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


def test_a_failed_second_seed_rolls_back_the_database_and_registry(tmp_path, monkeypatch):
    seed = LogiOpsService._seed
    database = tmp_path / "failed.sqlite3"

    def fail_second(cls, connection, incident_id, *args, **kwargs):
        seed(connection, incident_id, *args, **kwargs)
        if incident_id == "SHIP-471":
            raise sqlite3.OperationalError("simulated write failure")

    async def work():
        app = create_app(database)
        monkeypatch.setattr(LogiOpsService, "_seed", classmethod(fail_second))
        second = pack_incident(id="SHIP-471")
        second["orders"] = [{**order, "id": order["id"].replace("ORD-47", "ORD-48")} for order in second["orders"]]
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test") as client:
            response = await client.post("/scenario/packs", json={"version": 1, "incidents": [pack_incident(), second]})
            assert response.status_code == 500
            assert incident_ids() == INCIDENT_IDS
            assert "SHIP-470" not in PLAYBOOKS and "SHIP-471" not in INCIDENTS
            assert "port_strike" not in KIND_LABELS
            with sqlite3.connect(database) as connection:
                assert {row[0] for row in connection.execute("SELECT incident_id FROM snapshot")} == set(INCIDENT_IDS)
                assert connection.execute("SELECT COUNT(*) FROM events WHERE incident_id IN ('SHIP-470', 'SHIP-471')").fetchone()[0] == 0
            assert (await client.get("/incidents")).status_code == 200
            assert (await client.get("/metrics")).status_code == 200
            monkeypatch.setattr(LogiOpsService, "_seed", classmethod(seed.__func__))
            assert (await client.post("/scenario/packs", json={"version": 1, "incidents": [pack_incident(), second]})).status_code == 201

    try:
        asyncio.run(work())
    finally:
        reset_registry()
