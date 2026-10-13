"""Outcome metrics come from the recorded events and bookings, per incident and for the session, and guests can read them."""

import asyncio

import httpx

from logiops.api import create_app
from logiops.booking import BookingStore
from logiops.identity import OPERATOR
from logiops.metrics import incident_metrics, session_metrics
from logiops.service import LogiOpsService


def decided_and_executed(tmp_path, incident_id="SHIP-421", kind="split-express"):
    service = LogiOpsService(tmp_path / "metrics.sqlite3")
    bookings = BookingStore(tmp_path / "metrics.sqlite3", service)
    plan = next(item for item in service.investigate(incident_id) if item["kind"] == kind)
    service.record_agent_run(incident_id, plan["source_version"], {
        "answer": "Recommended plan: x", "tool_trace": [{}] * 5, "usage": {"inputTokens": 1200, "outputTokens": 300}, "mode": "bedrock",
    })
    service.approve(incident_id, plan["id"], plan["source_version"], "judge")
    service.execute(incident_id, plan["id"], plan["source_version"])
    quote = bookings.quote(incident_id, None, OPERATOR)
    booking = bookings.confirm(quote["quote_id"], quote["total_usd"], "buy-metrics-1", OPERATOR)
    return service, bookings, plan, booking


def test_an_untouched_incident_has_no_decision_and_no_spend(tmp_path):
    service = LogiOpsService(tmp_path / "fresh.sqlite3")
    metrics = incident_metrics(service.get("SHIP-433"), [])
    assert metrics["incident_id"] == "SHIP-433" and metrics["status"] == "detected" and metrics["kind"] == "carrier_outage"
    assert metrics["units"] == 30 and metrics["critical_units"] == 12
    assert metrics["investigations"] == 0 and metrics["model_calls"] == 0 and metrics["tokens"] == 0 and metrics["mode"] is None
    assert metrics["decided"] is False and metrics["executed"] is False
    for field in ("time_to_decision_s", "time_to_execution_s", "chosen_plan_id", "chosen_plan_label", "chosen_plan_cost_usd",
                  "customer_delay_hours", "critical_units_on_time", "late_units", "booking_number", "booking_total_usd"):
        assert metrics[field] is None, field


def test_a_decided_executed_and_booked_incident_reports_its_outcome(tmp_path):
    service, bookings, plan, booking = decided_and_executed(tmp_path)
    metrics = incident_metrics(service.get("SHIP-421"), bookings.for_incident("SHIP-421"))
    assert metrics["status"] == "verified" and metrics["decided"] and metrics["executed"]
    assert metrics["chosen_plan_id"] == plan["id"] and metrics["chosen_plan_label"] == plan["label"]
    assert metrics["chosen_plan_cost_usd"] == 120 and metrics["customer_delay_hours"] == 0
    assert metrics["critical_units_on_time"] == 0 and metrics["late_units"] == 0 and metrics["units"] == 20
    assert metrics["investigations"] == 1 and metrics["model_calls"] == 1 and metrics["tokens"] == 1500 and metrics["mode"] == "bedrock"
    assert metrics["time_to_decision_s"] is not None and 0 <= metrics["time_to_decision_s"] <= metrics["time_to_execution_s"] < 60
    assert metrics["booking_number"] == booking["number"] and metrics["booking_total_usd"] == 147.5


def test_the_critical_outcome_follows_the_chosen_plan(tmp_path):
    service = LogiOpsService(tmp_path / "critical.sqlite3")
    plans = service.investigate("SHIP-433")
    wait = next(plan for plan in plans if plan["kind"] == "wait")
    fly = next(plan for plan in plans if plan["kind"] == "priority-air-ground")
    service.approve("SHIP-433", wait["id"], wait["source_version"], "judge")
    waited = incident_metrics(service.get("SHIP-433"))
    assert waited["decided"] and not waited["executed"] and waited["chosen_plan_cost_usd"] == 0
    assert waited["critical_units_on_time"] == 0 and waited["late_units"] == 30 and waited["time_to_execution_s"] is None
    service.reset("SHIP-433")
    plans = service.investigate("SHIP-433")
    fly = next(plan for plan in plans if plan["kind"] == "priority-air-ground")
    service.approve("SHIP-433", fly["id"], fly["source_version"], "judge")
    service.execute("SHIP-433", fly["id"], fly["source_version"])
    flown = incident_metrics(service.get("SHIP-433"))
    assert flown["executed"] and flown["chosen_plan_cost_usd"] == 390 and flown["critical_units_on_time"] == 12 and flown["late_units"] == 18


def test_session_totals_count_only_what_happened(tmp_path):
    service, bookings, _plan, _booking = decided_and_executed(tmp_path)
    items = [incident_metrics(service.get(incident_id), bookings.for_incident(incident_id)) for incident_id in ("SHIP-421", "SHIP-433", "SHIP-452", "SHIP-460")]
    totals = session_metrics(items)
    assert totals["incidents"] == 4 and totals["investigated"] == 1 and totals["decided"] == 1 and totals["executed"] == 1
    assert totals["extra_cost_usd"] == 120 and totals["booked_usd"] == 147.5
    assert totals["critical_units_on_time"] == 0 and totals["late_units"] == 0
    assert totals["model_calls"] == 1 and totals["tokens"] == 1500
    assert totals["median_time_to_decision_s"] == items[0]["time_to_decision_s"]
    assert session_metrics([])["median_time_to_execution_s"] is None and session_metrics([])["extra_cost_usd"] == 0


def test_metrics_are_served_to_guests_and_cover_every_registered_incident(tmp_path, monkeypatch):
    monkeypatch.setenv("LOGIOPS_AGENT_MODE", "replay")

    async def run():
        app = create_app(tmp_path / "api.sqlite3")
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8000") as client:
                before = (await client.get("/metrics")).json()
                investigated = await client.post("/incidents/SHIP-421/agent/investigate", json={})
                assert investigated.status_code == 200
                plan = next(item for item in investigated.json()["plans"] if item["kind"] == "split-express")
                approved = await client.post("/incidents/SHIP-421/approvals", json={"plan_id": plan["id"], "source_version": plan["source_version"], "approved_by": "judge"})
                executed = await client.post("/incidents/SHIP-421/execute", json={"plan_id": plan["id"], "source_version": plan["source_version"]})
                assert approved.status_code == 200 and executed.status_code == 200
                after = (await client.get("/metrics")).json()
        return before, after

    before, after = asyncio.run(run())
    assert [item["incident_id"] for item in before["incidents"]] == ["SHIP-421", "SHIP-433", "SHIP-452", "SHIP-460"]
    assert before["session"]["executed"] == 0 and before["session"]["investigated"] == 0
    first = after["incidents"][0]
    assert first["executed"] and first["mode"] == "replay" and first["model_calls"] == 0 and first["investigations"] == 1
    assert after["session"]["executed"] == 1 and after["session"]["extra_cost_usd"] == 120 and after["session"]["tokens"] == 0


def test_a_guest_can_read_metrics_on_a_token_protected_server(tmp_path):
    async def run():
        app = create_app(tmp_path / "guest.sqlite3", access_token="a" * 40)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8000") as client:
            return await client.get("/metrics")

    response = asyncio.run(run())
    assert response.status_code == 200 and response.json()["session"]["incidents"] == 4
