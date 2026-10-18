"""Proactive alerts: a data change after an investigation is re-planned and reported, never approved."""

import asyncio
import re

import httpx
import jsonschema
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from logiops.alerts import AlertWatcher
from logiops.api import create_app
from logiops.preferences import PreferenceStore, preference_for
from logiops.scenario import best_plan
from logiops.service import LogiOpsService

BASE_URL = "http://127.0.0.1:8000"
PLAN_ID = re.compile(r"SHIP-\d+:[0-9a-f][0-9a-f-]{7,}:[a-z][a-z-]*:v\d+")


def watcher(tmp_path):
    path = tmp_path / "alerts.sqlite3"
    service = LogiOpsService(path)
    preferences = PreferenceStore(path)
    return service, preferences, AlertWatcher(path, service, preferences)


def approve(service, incident_id, kind):
    plan = next(item for item in service.investigate(incident_id) if item["kind"] == kind)
    service.approve(incident_id, plan["id"], plan["source_version"], "operator")
    return plan


def test_a_stock_drop_under_an_approved_plan_proposes_a_new_pick_and_approves_nothing(tmp_path):
    service, _preferences, alerts = watcher(tmp_path)
    approved = approve(service, "SHIP-421", "split-express")
    service.set_local_inventory("SHIP-421", 3)
    [alert] = alerts.scan()
    assert alert["id"] == "SHIP-421-v2" and alert["change"] == "Arequipa stock is now 3 units"
    assert alert["approval_invalidated"] is True and alert["previous_plan"]["label"] == approved["label"]
    assert alert["previous_plan"]["incremental_cost_usd"] == approved["incremental_cost_usd"]
    assert alert["new_plan"]["label"] == "Move the full order to an alternative carrier" and alert["new_plan"]["incremental_cost_usd"] == 80
    assert f"your approved plan “{approved['label']}” no longer applies" in alert["message"]
    assert "The new pick is “Move the full order to an alternative carrier”: $80, 3 h late." in alert["message"]
    assert "Nothing was approved" in alert["message"] and "Nothing was approved" in alert["spoken"]
    assert "$80, 3 hours late" in alert["spoken"]
    assert not PLAN_ID.search(alert["message"] + alert["spoken"])
    snapshot = service.get("SHIP-421")
    assert not [item for item in snapshot["approvals"] if item["is_current"]] and not snapshot["executions"]
    assert {plan["source_version"] for plan in snapshot["plans"]} == {1, 2}
    decision = [event for event in snapshot["events"] if event["name"] == "autopilot_decision"]
    assert len(decision) == 1 and decision[0]["data"]["decision"] == "propose" and decision[0]["data"]["approved"] is False
    assert alerts.scan() == [] and len(alerts.open_alerts()) == 1


def test_only_stale_unexecuted_investigations_raise_alerts(tmp_path):
    service, _preferences, alerts = watcher(tmp_path)
    service.set_local_inventory("SHIP-452", 3)
    assert alerts.scan() == [], "never investigated"
    service.investigate("SHIP-421")
    assert alerts.scan() == [], "plans are current"
    executed = approve(service, "SHIP-433", "reroute")
    service.execute("SHIP-433", executed["id"], executed["source_version"])
    assert alerts.scan() == [], "executed"


def test_an_unapproved_investigation_reports_whether_the_pick_still_works(tmp_path):
    service, _preferences, alerts = watcher(tmp_path)
    service.investigate("SHIP-452")
    service.set_local_inventory("SHIP-452", 3)
    [alert] = alerts.scan()
    assert alert["approval_invalidated"] is False and "the plans I gave you are out of date" in alert["message"]
    assert alert["previous_plan"]["label"] == alert["new_plan"]["label"]
    assert "still works and is still my pick" in alert["message"]


def test_the_new_pick_follows_the_saved_preferences(tmp_path):
    service, preferences, alerts = watcher(tmp_path)
    service.investigate("SHIP-452")
    preferences.put("cheapest_unless_critical_late", None)
    service.set_local_inventory("SHIP-452", 3)
    [alert] = alerts.scan()
    plans = [plan for plan in service.get("SHIP-452")["plans"] if plan["source_version"] == 2]
    preferred = preference_for(plans, preferences.get())
    assert alert["new_plan"]["plan_id"] == preferred["preferred_plan_id"] != best_plan(plans)["id"]


def test_when_no_plan_works_the_alert_says_so(tmp_path):
    service, _preferences, alerts = watcher(tmp_path)
    approve(service, "SHIP-460", "priority-first")
    service.set_local_inventory("SHIP-460", 0)
    [alert] = alerts.scan()
    assert alert["new_plan"] is None and "no plan works with the new data" in alert["message"]
    assert "Trujillo stock is now 0 units" in alert["spoken"]


def test_the_api_alerts_right_after_a_stock_change_and_reset_forgets(tmp_path, monkeypatch):
    monkeypatch.setenv("LOGIOPS_ALERT_SCAN_SECONDS", "0")

    async def run():
        app = create_app(tmp_path / "api.sqlite3")
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE_URL) as http:
            plan = (await http.post("/incidents/SHIP-421/investigate")).json()["plans"][2]
            await http.post("/incidents/SHIP-421/approvals", json={
                "plan_id": plan["id"], "source_version": plan["source_version"], "approved_by": "operator"})
            changed = await http.post("/demo/inventory", json={"incident_id": "SHIP-421", "available": 3})
            listed = (await http.get("/alerts")).json()["alerts"]
            dismissed = await http.post(f"/alerts/{listed[0]['id']}/dismiss")
            after_dismiss = (await http.get("/alerts")).json()["alerts"]
            await http.post("/incidents/SHIP-421/investigate")
            await http.post("/demo/inventory", json={"incident_id": "SHIP-421", "available": 2})
            before_reset = (await http.get("/alerts")).json()["alerts"]
            await http.post("/demo/reset")
            after_reset = (await http.get("/alerts")).json()["alerts"]
            missing = await http.post("/alerts/nope/dismiss")
            return changed, listed, dismissed, after_dismiss, before_reset, after_reset, missing

    changed, listed, dismissed, after_dismiss, before_reset, after_reset, missing = asyncio.run(run())
    assert changed.status_code == 200 and changed.json()["state"]["status"] == "investigated"
    assert [alert["id"] for alert in listed] == ["SHIP-421-v2"]
    assert dismissed.json()["dismissed"] is True and after_dismiss == []
    assert [alert["id"] for alert in before_reset] == ["SHIP-421-v3"] and after_reset == []
    assert missing.status_code == 404


def test_mcp_lists_alerts_that_match_the_output_schema(tmp_path, monkeypatch):
    monkeypatch.setenv("LOGIOPS_ALERT_SCAN_SECONDS", "0")

    async def run():
        app = create_app(tmp_path / "mcp.sqlite3")
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE_URL) as http:
                await http.post("/incidents/SHIP-460/investigate")
                await http.post("/demo/inventory", json={"incident_id": "SHIP-460", "available": 0})
                await http.post("/incidents/SHIP-421/investigate")
                await http.post("/demo/inventory", json={"incident_id": "SHIP-421", "available": 3})
                async with streamable_http_client(f"{BASE_URL}/mcp", http_client=http) as (read, write, _):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        tool = next(item for item in (await session.list_tools()).tools if item.name == "list_alerts")
                        result = await session.call_tool("list_alerts", {})
                        return tool, result

    tool, result = asyncio.run(run())
    assert tool.annotations.readOnlyHint is True
    jsonschema.validate(result.structuredContent, tool.outputSchema)
    assert {alert["incident_id"] for alert in result.structuredContent["alerts"]} == {"SHIP-421", "SHIP-460"}


def test_the_background_watcher_finds_changes_made_elsewhere(tmp_path, monkeypatch):
    monkeypatch.setenv("LOGIOPS_ALERT_SCAN_SECONDS", "0.05")

    async def run():
        app = create_app(tmp_path / "watch.sqlite3")
        service = LogiOpsService(tmp_path / "watch.sqlite3")
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE_URL) as http:
                service.investigate("SHIP-452")
                service.set_local_inventory("SHIP-452", 3)
                for _ in range(60):
                    found = (await http.get("/alerts")).json()["alerts"]
                    if found:
                        return found
                    await asyncio.sleep(0.05)
        return []

    found = asyncio.run(run())
    assert [alert["id"] for alert in found] == ["SHIP-452-v2"]
