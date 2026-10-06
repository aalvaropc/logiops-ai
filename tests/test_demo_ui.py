"""The browser demo is reachable without exposing incident data or losing assets on deploy."""

import asyncio
import tarfile
from pathlib import Path

import httpx

from logiops.api import create_app
from scripts.deploy_ec2 import package


def test_demo_assets_are_public_but_actions_require_token(tmp_path):
    async def run():
        app = create_app(tmp_path / "ui.sqlite3", access_token="a" * 40)
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8000"
            ) as client:
                page = await client.get("/demo")
                script = await client.get("/assets/demo.js")
                style = await client.get("/assets/demo.css")
                assert page.status_code == script.status_code == style.status_code == 200
                assert "Simulated Alexa+ experience" in page.text
                assert "approve selected plan" in page.text.lower()
                assert (await client.get("/incidents/SHIP-421")).status_code == 401
                assert (await client.post("/demo/reset")).status_code == 401

    asyncio.run(run())


def test_release_archive_contains_browser_demo():
    archive, _ = package()
    with tarfile.open(archive, "r:gz") as release:
        names = set(release.getnames())
    assert {"logiops/static/demo.html", "logiops/static/demo.css", "logiops/static/demo.js"} <= names


def test_questions_are_never_routed_to_actions():
    import re
    script = (Path(__file__).resolve().parents[1] / "logiops" / "static" / "demo.js").read_text()
    source = re.search(r"const QUESTION = /(.+)/;", script).group(1).replace("\\/", "/")
    question = re.compile(source)
    for text in ("should we approve the split plan?", "what happens if i execute it", "how do i reset?",
                 "can we do it tomorrow", "is the reroute approved?"):
        assert question.search(text), text
    for text in ("approve the recommended plan", "execute it", "reset", "approve the split plan.", "yes, do it"):
        assert not question.search(text), text
    for action in ("reset|start over", "\\bapprove\\b", "execute|go ahead"):
        line = next(line for line in script.splitlines() if action in line and "test(lower)" in line)
        assert "!question" in line, line
