"""Capture the README screenshots from a replay server, headless; needs the `browser` extra and Chromium.

    uv sync --extra dev --extra browser && uv run playwright install --only-shell chromium
    uv run python scripts/screenshots.py                     # starts its own replay server
    uv run python scripts/screenshots.py --url http://127.0.0.1:8000 --out docs/img

Zero model calls: the server runs in replay mode. The demo data is reset before and after.
"""

from __future__ import annotations

import argparse
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DESKTOP = {"width": 1440, "height": 900}
PHONE = {"width": 390, "height": 844}


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def start_server(db_path: Path) -> tuple[subprocess.Popen, str]:
    port = free_port()
    env = {name: value for name, value in os.environ.items() if not name.startswith(("LOGIOPS_", "AWS_"))}
    env.update(LOGIOPS_AGENT_MODE="replay", LOGIOPS_AGENT_LIMIT_PER_MINUTE="60", LOGIOPS_MCP_LIMIT_PER_MINUTE="600", LOGIOPS_DB_PATH=str(db_path))
    process = subprocess.Popen([sys.executable, "-m", "uvicorn", "logiops.api:app", "--host", "127.0.0.1", "--port", str(port)],
                               cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    url = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try:
            with urllib.request.urlopen(f"{url}/healthz", timeout=1):
                return process, url
        except OSError:
            time.sleep(0.2)
    process.terminate()
    raise SystemExit("the replay server did not start")


def say(page, text: str) -> None:
    page.fill("#ask-input", text)
    page.click("#ask")
    page.wait_for_function("""(t) => document.querySelector("#device-heard").textContent === t && !document.querySelector("#ask").disabled""",
                           arg=text, timeout=30000)


def settled(page) -> None:
    page.wait_for_selector("#agent-stage", state="hidden", timeout=15000)
    page.wait_for_timeout(1500)


def checked(response, what: str) -> None:
    """Raise when the request behind the response did not succeed."""
    if response is None or not response.ok:
        raise RuntimeError(f"{what} failed: {response.status if response else 'no response'}")


def card_ready(page) -> None:
    """Wait for the MCP App card to show its picked plan, or raise."""
    for _ in range(50):
        outer = next((frame for frame in page.frames if "/mcp-app/sandbox.html" in frame.url), None)
        inner = outer.child_frames[0] if outer and outer.child_frames else None
        if inner:
            try:
                if inner.evaluate("""document.querySelectorAll(".plan.pick").length"""):
                    return
            except Exception:
                pass
        page.wait_for_timeout(200)
    raise RuntimeError("the MCP App card never rendered a picked plan")


def stage_shown(page) -> None:
    """Raise unless the agent stage is on screen with its stations and the check."""
    stage = page.locator("#agent-stage")
    shown = stage.is_visible() and stage.evaluate(
        """(root) => !root.classList.contains("leaving")
            && root.querySelectorAll(".agent-stations li:not(.check)").length > 0
            && root.querySelector(".agent-stations li.check") !== null""")
    if not shown:
        raise RuntimeError("the agent stage is not on screen with its stations and check")


def capture(base: str, out: Path) -> list[Path]:
    from playwright.sync_api import sync_playwright

    out.mkdir(parents=True, exist_ok=True)
    shots: list[Path] = []

    def shot(page, name: str, ready=None, **options) -> None:
        path = out / f"{name}.png"
        page.wait_for_timeout(400)
        if ready:
            ready(page)
        page.screenshot(path=str(path), **options)
        shots.append(path)

    def reset(page) -> None:
        checked(page.request.post(f"{base}/demo/reset"), "POST /demo/reset")

    def visit(page, path: str) -> None:
        checked(page.goto(f"{base}{path}"), f"GET {path}")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        phone = browser.new_page(viewport=PHONE)
        reset(phone)
        visit(phone, "/demo#SHIP-433")
        phone.wait_for_function("document.querySelector('#connection').textContent === 'Connected'")
        phone.wait_for_selector('[data-surface="incident"] #device-map')
        settled(phone)
        shot(phone, "device-phone")
        page = browser.new_page(viewport=DESKTOP)
        reset(page)
        visit(page, "/demo")
        page.wait_for_function("document.querySelector('#connection').textContent === 'Connected'")
        page.wait_for_selector(".session-strip")
        settled(page)
        shot(page, "device-home")
        page.click('.incident-card[data-incident="SHIP-433"]')
        page.wait_for_selector('[data-surface="incident"] #device-map')
        settled(page)
        page.fill("#ask-input", "What's happening with SHIP-433, and which plan should we choose?")
        page.click("#ask")
        page.wait_for_selector("#agent-stage .agent-stations li.check", timeout=30000)
        page.wait_for_timeout(500)
        shot(page, "device-agent", ready=stage_shown)
        settled(page)
        card_ready(page)
        page.wait_for_timeout(600)
        shot(page, "device-plans")
        say(page, "show the incident")
        settled(page)
        shot(page, "device-journey")
        say(page, "show the plans")
        settled(page)
        say(page, "approve the recommended plan")
        settled(page)
        shot(page, "device-confirm")
        page.click("#confirm-yes")
        page.wait_for_function("!document.querySelector('#ask').disabled && document.querySelector('#plans-state').textContent.includes('Approved')")
        say(page, "execute it")
        page.wait_for_selector(".result-card .times")
        settled(page)
        shot(page, "device-result")
        visit(page, "/console#SHIP-433")
        page.wait_for_function("document.querySelector('#connection').textContent === 'Connected'")
        page.wait_for_selector("#metrics:not([hidden])")
        settled(page)
        shot(page, "console", clip={"x": 0, "y": 0, "width": DESKTOP["width"], "height": 900})
        reset(page)
        browser.close()
    return shots


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--url", help="a replay server that already runs (the demo data is reset)")
    parser.add_argument("--out", default=str(ROOT / "docs" / "img"), help="folder for the PNG files")
    args = parser.parse_args()
    process = None
    base = args.url
    if base is None:
        import tempfile

        process, base = start_server(Path(tempfile.mkdtemp(prefix="logiops-shots-")) / "replay.sqlite3")
    try:
        for path in capture(base, Path(args.out)):
            print(f"{path.relative_to(ROOT) if path.is_relative_to(ROOT) else path}  {path.stat().st_size // 1024} KB")
    finally:
        if process is not None:
            process.terminate()
            process.wait(timeout=10)


if __name__ == "__main__":
    main()
