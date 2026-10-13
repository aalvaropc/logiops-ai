"""Headless walkthrough of the whole demo in replay mode; prints PASS or FAIL per step.

    uv run python scripts/rehearse_api.py                    # starts its own replay server
    uv run python scripts/rehearse_api.py --url http://127.0.0.1:8000

With --url the server must already run in replay mode (the script resets its demo data).
It never calls a paid model. Set LOGIOPS_ACCESS_TOKEN if the server requires a token.
"""

from __future__ import annotations

import argparse
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Callable

import httpx

INCIDENT = "SHIP-421"
failures: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    print(f"{'PASS' if condition else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not condition else ""))
    if not condition:
        failures.append(name)


def walk(client: httpx.Client) -> None:
    def post(path: str, **body: Any) -> httpx.Response:
        return client.post(path, json=body)

    def kind(plans: list[dict[str, Any]], wanted: str) -> dict[str, Any]:
        return next(plan for plan in plans if plan["kind"] == wanted)

    def investigate() -> dict[str, Any]:
        """The agent run, or a clear failure (for example HTTP 429 from the agent rate limit)."""
        response = post(f"/incidents/{INCIDENT}/agent/investigate")
        if response.status_code != 200:
            raise SystemExit(f"FAIL  investigation returned HTTP {response.status_code}: {response.text[:150]}"
                             + ("\n(The agent rate limit is 10 per minute; start the server with"
                                " LOGIOPS_AGENT_LIMIT_PER_MINUTE=60 for repeated walkthroughs.)"
                                if response.status_code == 429 else ""))
        return response.json()

    check("server is healthy", client.get("/healthz").status_code == 200)
    check("reset the synthetic incident", post("/demo/reset").status_code == 200)

    run = investigate()
    plans = run.get("plans", [])
    check("replay investigation: three plans, zero tokens, grounded-style answer",
          len(plans) == 3 and run.get("mode") == "replay" and run["usage"] == {"inputTokens": 0, "outputTokens": 0},
          str(run.get("mode")))
    check("the agent used the MCP tools", len(run.get("tool_trace", [])) == 5)

    follow = post(f"/incidents/{INCIDENT}/agent/ask", question="How much is the reroute?", history=[])
    check("follow-up answered from the stored investigation", follow.status_code == 200 and "$80" in follow.json()["answer"])

    split = kind(plans, "split-express")
    body = {"plan_id": split["id"], "source_version": split["source_version"]}
    check("approve the recommended plan", post(f"/incidents/{INCIDENT}/approvals", approved_by="rehearsal", **body).status_code == 200)
    executed = post(f"/incidents/{INCIDENT}/execute", **body)
    check("execute it (20 units accounted for)", executed.status_code == 200, executed.text[:120])
    again = post(f"/incidents/{INCIDENT}/execute", **body)
    check("executing twice is idempotent", again.status_code == 200 and again.json() == executed.json())
    state = client.get(f"/incidents/{INCIDENT}").json()
    check("one execution and one approval recorded", len(state["executions"]) == 1 and len(state["approvals"]) == 1)

    post("/demo/reset")
    plans = investigate()["plans"]
    split = kind(plans, "split-express")
    body = {"plan_id": split["id"], "source_version": split["source_version"]}
    post(f"/incidents/{INCIDENT}/approvals", approved_by="rehearsal", **body)
    changed = post("/demo/inventory", available=11)
    check("stock change accepted", changed.status_code == 200)
    refused = post(f"/incidents/{INCIDENT}/execute", **body)
    check("the stale approval is refused", refused.status_code == 409, str(refused.status_code))
    replanned = investigate()["plans"]
    check("a new investigation offers only the feasible plans (no split)",
          {plan["kind"] for plan in replanned} == {"wait", "reroute"}, str({plan["kind"] for plan in replanned}))
    post("/demo/reset")

    inbox = client.get("/incidents").json()["incidents"]
    builtin = {"SHIP-421", "SHIP-433", "SHIP-452", "SHIP-460"}
    check("the inbox lists the four built-in incidents of different kinds, plus any registered pack",
          builtin <= {item["incident_id"] for item in inbox} and len({item["kind"] for item in inbox}) == len(inbox),
          str([item["incident_id"] for item in inbox]))
    outage = post("/incidents/SHIP-433/agent/investigate")
    pick = outage.json()["plans"] if outage.status_code == 200 else []
    best = kind(pick, "priority-air-ground") if pick else None
    check("a carrier outage with a critical order: the hospital flies, the store is rebooked",
          bool(best) and outage.json().get("recommended_plan_id") == best["id"] and best["label"] in outage.json()["answer"])
    body = {"plan_id": best["id"], "source_version": best["source_version"]}
    post("/incidents/SHIP-433/approvals", approved_by="rehearsal", **body)
    done = post("/incidents/SHIP-433/execute", **body)
    check("executing it accounts for both orders (30 units)", done.status_code == 200 and done.json()["accounted_units"] == 30)
    quoted = post("/incidents/SHIP-433/bookings/quote")
    quote = quoted.json() if quoted.status_code == 200 else {}
    check("booking its carriers is quoted with IGV: $390 + $5 fee + $71.10 = $466.10",
          quote.get("total_usd") == 466.1 and "IGV 18% $71.10" in quote.get("summary", ""), quoted.text[:120])
    wrong = post(f"/quotes/{quote.get('quote_id')}/confirm", confirmed_total_usd=400, idempotency_key="rehearsal-booking")
    check("a different amount is refused and nothing is charged", wrong.status_code == 409, str(wrong.status_code))
    paid = post(f"/quotes/{quote.get('quote_id')}/confirm", confirmed_total_usd=466.1, idempotency_key="rehearsal-booking")
    retried = post(f"/quotes/{quote.get('quote_id')}/confirm", confirmed_total_usd=466.1, idempotency_key="rehearsal-booking")
    number = paid.json().get("number", "") if paid.status_code == 200 else ""
    check("paying the quoted total books it once, with a confirmation number",
          number.startswith("LGO-") and retried.status_code == 200 and retried.json()["number"] == number, paid.text[:120])
    receipt = client.get(f"/bookings/{number}/receipt")
    check("the receipt shows the total charged", receipt.status_code == 200 and "$466.10" in receipt.text)
    untouched = client.get(f"/incidents/{INCIDENT}").json()
    check("SHIP-421 is untouched by another incident", [e["name"] for e in untouched["events"]] == ["scenario_reset"])
    post("/demo/reset")

    briefing = post("/agent/briefing", question="Any delays today?")
    check("the briefing ranks the queue and changes nothing",
          briefing.status_code == 200 and briefing.json()["start_with"] in {item["incident_id"] for item in inbox}
          and all(not client.get(f"/incidents/{item['incident_id']}").json()["plans"] for item in inbox),
          briefing.text[:120])
    saved = client.put("/operator/preferences", json={"rule": "balanced", "max_cost_usd": 250})
    check("a $250 spend cap is saved", saved.status_code == 200)
    capped = post("/incidents/SHIP-433/agent/investigate")
    cheaper = kind(capped.json()["plans"], "priority-air") if capped.status_code == 200 else None
    check("with the cap, the agent recommends the $240 plan that still flies the hospital order",
          bool(cheaper) and capped.json().get("recommended_plan_id") == cheaper["id"] and cheaper["label"] in capped.json()["answer"]
          and capped.json()["spoken"])
    state = client.get("/incidents/SHIP-433").json()
    check("the preference points to it and approves nothing",
          state["preference"]["preferred_plan_id"] == cheaper["id"] and not state["approvals"])
    post("/demo/reset")
    check("resetting everything forgets the preferences",
          client.get("/operator/preferences").json()["preferences"] is None)


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--url", help="use a running replay server instead of starting one")
    args = parser.parse_args()
    token = os.environ.get("LOGIOPS_ACCESS_TOKEN")
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    server: subprocess.Popen[bytes] | None = None
    with tempfile.TemporaryDirectory(prefix="logiops-rehearse-") as directory:
        try:
            if args.url:
                url = args.url.rstrip("/")
            else:
                port = free_port()
                url = f"http://127.0.0.1:{port}"
                env = {k: v for k, v in os.environ.items() if not k.startswith("LOGIOPS_")}
                env.update(LOGIOPS_AGENT_MODE="replay", LOGIOPS_DB_PATH=str(Path(directory) / "rehearse.sqlite3"))
                server = subprocess.Popen(
                    [sys.executable, "-m", "uvicorn", "logiops.api:app", "--host", "127.0.0.1", "--port", str(port)],
                    env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
            with httpx.Client(base_url=url, headers=headers, timeout=30) as client:
                wait_until(lambda: client.get("/healthz").status_code == 200)
                walk(client)
        finally:
            if server is not None:
                server.terminate()
                server.wait(timeout=10)
    print(f"\n{'All steps passed.' if not failures else f'{len(failures)} step(s) failed.'}")
    return 1 if failures else 0


def wait_until(probe: Callable[[], bool], seconds: float = 20.0) -> None:
    deadline = time.monotonic() + seconds
    while True:
        try:
            if probe():
                return
        except httpx.HTTPError:
            pass
        if time.monotonic() > deadline:
            raise SystemExit("The server did not become healthy in time.")
        time.sleep(0.3)


if __name__ == "__main__":
    raise SystemExit(main())
