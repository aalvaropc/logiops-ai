"""The operator console is its own public page with the full operator view and a developer drawer."""

import asyncio
import re
from pathlib import Path

import httpx

from logiops.api import create_app

STATIC = Path(__file__).resolve().parents[1] / "logiops" / "static"


def get(app, path, **headers):
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8000") as http:
            return await http.get(path, headers={"host": "127.0.0.1:8000", **headers})
    return asyncio.run(run())


def test_the_console_is_public_and_its_actions_are_not(tmp_path):
    app = create_app(tmp_path / "console.sqlite3", access_token="c" * 40)
    page = get(app, "/console")
    assert page.status_code == 200 and page.headers["content-type"].startswith("text/html")
    assert get(app, "/assets/console.css").status_code == 200
    assert get(app, "/incidents").status_code == 401


def test_the_console_has_the_operator_view_without_the_device_or_the_hero():
    console, demo = (STATIC / "console.html").read_text(), (STATIC / "demo.html").read_text()
    for marker in ('id="inbox"', 'id="incident-id"', 'id="conversation"', 'id="plans"', 'id="approve"', 'id="execute"', 'id="booking"',
                   'id="pref-form"', 'id="timeline"', 'id="alerts-bell"', 'id="account"', 'id="developer"', 'id="access-token"',
                   'id="stock-input"', 'id="reset"', 'href="/mcp"', 'href="/demo"'):
        assert marker in console, marker
    for absent in ('id="device"', "A delay is a decision", 'id="mcp-app"', "logiops-sandbox-origin", "/assets/device.js"):
        assert absent not in console, absent
    assert '<script src="/assets/console.js" type="module"></script>' in console
    assert console.index("/assets/intent.js") < console.index("/assets/console.js")
    assert 'href="/console"' in demo and 'id="mcp-app"' in demo
    assert set(re.findall(r'/assets/([\w./-]+)', console)) <= {path.relative_to(STATIC).as_posix() for path in STATIC.rglob("*") if path.is_file()}


def test_the_console_script_has_no_card_and_signs_in_through_the_device_page():
    script, device = (STATIC / "console.js").read_text(), (STATIC / "device" / "main.js").read_text()
    assert "createMcpAppHost" not in script and "LogiOpsDevice" not in script and "mcp-app" not in script
    assert 'returnTo: "/console"' in script and "finishSignIn" not in script
    assert 'if (outcome.path.startsWith("/console")) {' in device and "location.replace(outcome.path);" in device


def test_the_developer_drawer_imports_a_scenario_pack():
    console, script, api = (STATIC / "console.html").read_text(), (STATIC / "console.js").read_text(), (STATIC / "app" / "api.js").read_text()
    assert 'id="pack-file" type="file" accept="application/json,.json"' in console and 'id="import-pack"' in console
    assert 'id="pack-result" class="developer-links" role="status" aria-live="polite"' in console
    assert 'request("/scenario/packs", "POST", pack)' in script and "error.detail?.errors" in script
    assert "Nothing was registered." in script and "until the server restarts" in script
    assert "error.detail = detail;" in api and 'typeof detail === "string" ? detail : listed || detail?.message' in api


def test_the_console_shows_who_the_approval_was_recorded_under():
    script = (STATIC / "console.js").read_text()
    assert 'import { recordedNote } from "./app/approval.js";' in script
    assert 'const approval = await request(incidentPath("/approvals")' in script
    assert 'recordedNote(approvedBy, approval)' in script and '$("approver").value = approval.approved_by' in script
    assert '$("approver").readOnly = Boolean(' in script, "a signed-in name is the server's to set, so the field is not editable"
