"""Browser walkthroughs in replay mode, run only with LOGIOPS_BROWSER=1 and the browser extra installed."""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

if os.environ.get("LOGIOPS_BROWSER") != "1":
    collect_ignore_glob = ["test_*.py"]

ROOT = Path(__file__).resolve().parents[2]
WIDTHS = (1440, 390)
REPLY_TIMEOUT_MS = 20000


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def start_replay_server(tmp_path_factory: pytest.TempPathFactory, **settings: str):
    """A replay-mode API on a free port with a fresh database; no model or speech call is ever made."""
    port = free_port()
    env = {name: value for name, value in os.environ.items() if not name.startswith(("LOGIOPS_", "AWS_"))}
    env.update(LOGIOPS_AGENT_MODE="replay", LOGIOPS_AGENT_LIMIT_PER_MINUTE="60", LOGIOPS_MCP_LIMIT_PER_MINUTE="600",
               LOGIOPS_DB_PATH=str(tmp_path_factory.mktemp("replay") / "logiops.sqlite3"), **settings)
    log = (tmp_path_factory.mktemp("logs") / "server.log").open("w")
    process = subprocess.Popen([sys.executable, "-m", "uvicorn", "logiops.api:app", "--host", "127.0.0.1", "--port", str(port)],
                               cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
    url = f"http://127.0.0.1:{port}"
    try:
        for _ in range(100):
            try:
                with urllib.request.urlopen(f"{url}/healthz", timeout=1):
                    break
            except OSError:
                if process.poll() is not None:
                    raise RuntimeError(f"the replay server exited with {process.returncode}; see {log.name}")
                time.sleep(0.2)
        else:
            raise RuntimeError(f"the replay server did not answer on {url}; see {log.name}")
        yield url
    finally:
        process.terminate()
        process.wait(timeout=10)
        log.close()


@pytest.fixture(scope="session")
def replay_server(tmp_path_factory: pytest.TempPathFactory):
    yield from start_replay_server(tmp_path_factory)


@pytest.fixture
def fresh_replay_server(tmp_path_factory: pytest.TempPathFactory):
    """A server of its own for a test that changes the process, such as registering a scenario pack."""
    yield from start_replay_server(tmp_path_factory)


@pytest.fixture
def token_server(tmp_path_factory: pytest.TempPathFactory):
    """A server that needs an access token, so the console's approver is named by the server."""
    yield from start_replay_server(tmp_path_factory, LOGIOPS_ACCESS_TOKEN="t" * 40)


@pytest.fixture
def page_errors(page):
    """Uncaught exceptions and console errors raised by the page; a walkthrough expects none."""
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on("console", lambda message: errors.append(f"console: {message.text}") if message.type == "error" else None)
    return errors


@pytest.fixture
def reset_demo(page, replay_server):
    response = page.request.post(f"{replay_server}/demo/reset")
    assert response.ok, response.text()
    yield
    page.request.post(f"{replay_server}/demo/reset")


def say(page, text: str) -> str:
    """Send one line to the agent and return the reply once the page is idle again."""
    before = page.locator("#conversation > li.user").count()
    page.fill("#ask-input", text)
    page.click("#ask")
    page.wait_for_function(
        """(n) => {
            const items = [...document.querySelectorAll("#conversation > li")];
            return items.filter((item) => item.classList.contains("user")).length > n
                && items.at(-1).classList.contains("assistant") && !document.querySelector("#ask").disabled;
        }""",
        arg=before, timeout=REPLY_TIMEOUT_MS)
    return " ".join(page.locator("#conversation > li").last.inner_text().split())


def assert_accessible(page) -> None:
    """axe reports no violation, nothing overflows the viewport."""
    from axe_playwright_python.sync_playwright import Axe

    results = Axe().run(page, options={"resultTypes": ["violations"], "iframes": False})
    assert results.violations_count == 0, results.generate_report()
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), "the page overflows the viewport"
