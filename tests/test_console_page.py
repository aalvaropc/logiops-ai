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
    for absent in ('id="device"', "A delay is a decision", 'id="mcp-app"', "logiops-sandbox-origin", "/assets/device.js", "/assets/route.js"):
        assert absent not in console, absent
    assert '<script src="/assets/demo.js" type="module"></script>' in console
    assert console.index("/assets/intent.js") < console.index("/assets/demo.js")
    assert 'href="/console"' in demo and 'id="mcp-app"' in demo
    assert set(re.findall(r'/assets/([\w./-]+)', console)) <= {path.relative_to(STATIC).as_posix() for path in STATIC.rglob("*") if path.is_file()}


def test_the_page_script_works_without_the_card_or_the_device():
    script = (STATIC / "demo.js").read_text()
    assert 'const mcpHost = $("mcp-app-slot") && createMcpAppHost({' in script
    assert "if (!step || !mcpHost) return;" in script and "if (mcpHost) mcpHost.hide(reason);" in script
    assert '$("mcp-app-theme")?.addEventListener' in script
    assert 'returnTo: location.pathname === "/console" ? "/console" : null' in script
    assert 'if (outcome.path.startsWith("/console")) {' in script
