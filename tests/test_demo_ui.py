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


def test_demo_has_basic_accessibility_hooks():
    root = Path(__file__).resolve().parents[1] / "logiops" / "static"
    script, style = (root / "demo.js").read_text(), (root / "demo.css").read_text()
    assert "prefers-reduced-motion: reduce" in style
    assert "grid-template-columns: minmax(0, 1fr)" in style  # no horizontal overflow on narrow screens
    assert 'aria-label="Conversation" tabindex="0"' in (root / "demo.html").read_text()  # scrollable, so focusable
    assert 'box.setAttribute("role", success || !text ? "status" : "alert")' in script  # errors are announced assertively
    assert 'container.setAttribute("role", "radiogroup")' in script
    html = (root / "demo.html").read_text()
    assert 'lang="en"' in html and 'aria-live="polite"' in html and 'frame.title = "Resolution options' in script


def _node(script: str) -> str:
    import shutil
    import subprocess

    node = shutil.which("node")
    if node is None:
        import pytest

        pytest.skip("node is not installed")
    root = Path(__file__).resolve().parents[1] / "logiops" / "static"
    return subprocess.run([node, "-e", f"const m = require({str(root / 'markdown.js')!r}); {script}"],
                          capture_output=True, text=True, check=True).stdout.strip()


def test_markdown_renders_the_models_replies_structurally():
    import json

    types = json.loads(_node(
        "console.log(JSON.stringify(m.parseBlocks('## T\\n\\n**x** `y`\\n\\n| A | B |\\n|---|---|\\n| 1 | 2 |\\n\\n- a\\n- b\\n\\n> q\\n---\\nend').map(b => b.type)))"))
    assert types == ["h", "p", "table", "ul", "quote", "hr", "p"]
    table = json.loads(_node(
        "console.log(JSON.stringify(m.parseBlocks('| A | B |\\n|---|---|\\n| 1 | 2 |')[0]))"))
    assert [cell[0]["v"] for cell in table["head"]] == ["A", "B"] and table["rows"][0][1][0]["v"] == "2"


def test_markdown_never_produces_html_and_speech_drops_the_markup():
    # The parser returns plain text parts only; demo.js builds nodes with textContent.
    parts = _node("console.log(JSON.stringify(m.parseInline('**<img src=x onerror=alert(1)>**')))")
    assert '"t":"strong"' in parts and '"v":"<img src=x onerror=alert(1)>"' in parts
    assert _node("console.log(m.plainText('## 📦 Status\\n\\n**Plan approved:** `split-express:v1`\\n\\n| S | U |\\n|---|---|\\n| Local | 12 |'))") \
        == "📦 Status. Plan approved: split-express:v1. Local, 12"
    script = (Path(__file__).resolve().parents[1] / "logiops" / "static" / "demo.js").read_text()
    assert "innerHTML" not in script and "insertAdjacentHTML" not in script
    assert "LogiOpsMarkdown.plainText(text)" in script  # read-aloud speaks the words, not the symbols


def test_markdown_asset_is_served_and_shipped(tmp_path):
    async def run():
        app = create_app(tmp_path / "md.sqlite3")
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            page = (await client.get("/demo")).text
            script = await client.get("/assets/markdown.js")
        assert '/assets/markdown.js' in page and script.status_code == 200 and "parseBlocks" in script.text

    asyncio.run(run())
    archive, _ = package()
    with tarfile.open(archive, "r:gz") as release:
        assert "logiops/static/markdown.js" in release.getnames()


def test_a_card_that_cannot_load_says_why():
    script = (Path(__file__).resolve().parents[1] / "logiops" / "static" / "demo.js").read_text()
    assert "showMcpAppNote(" in script and "could not be loaded" in script
    assert "showMcpApp(run).catch(() => hideMcpApp())" not in script  # no more silent failure
