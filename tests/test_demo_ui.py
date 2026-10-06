"""The browser demo is reachable without exposing incident data or losing assets on deploy."""

import asyncio
import tarfile

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
