"""Run the complete synthetic incident over a deployed HTTPS endpoint."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

import httpx


LOCAL_SECRET = Path(__file__).resolve().parents[1] / ".secrets" / "access-token"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("base_url", help="https://<distribution>.cloudfront.net")
    args = parser.parse_args()
    if not args.base_url.startswith("https://"):
        raise SystemExit("A remote HTTPS URL is required")
    token = os.environ.get("LOGIOPS_ACCESS_TOKEN")
    if not token and LOCAL_SECRET.exists():
        token = LOCAL_SECRET.read_text().strip()
    if not token:
        raise SystemExit("Set LOGIOPS_ACCESS_TOKEN or run create_access_token.py")

    with httpx.Client(
        base_url=args.base_url.rstrip("/"),
        headers={"Authorization": f"Bearer {token}"},
        timeout=125,
    ) as client:
        reset = client.post("/demo/reset")
        reset.raise_for_status()
        inbox = client.get("/incidents")
        inbox.raise_for_status()
        if len(inbox.json()["incidents"]) != 4:
            raise RuntimeError("The deployed inbox does not list the four synthetic incidents")
        investigated = client.post("/incidents/SHIP-421/agent/investigate", json={})
        investigated.raise_for_status()
        run = investigated.json()
        if run.get("fallback") == "daily_budget":
            raise RuntimeError("Today's live model budget is used (LOGIOPS_DAILY_MODEL_CALLS), so the deployment "
                               "answered from replay; try after midnight Lima time or raise the limit")
        if run["mode"] != "bedrock" or len(run["plans"]) != 3:
            raise RuntimeError("The live Bedrock agent did not produce three plans")
        if not any(step["tool"] == "investigate_incident" and not step["is_error"] for step in run["tool_trace"]):
            raise RuntimeError("The agent did not call the MCP investigation tool")
        plan = next(item for item in run["plans"] if item["kind"] == "split-express")
        approval = client.post("/incidents/SHIP-421/approvals", json={
            "plan_id": plan["id"], "source_version": plan["source_version"],
            "approved_by": "remote-verification",
        })
        approval.raise_for_status()
        execution_request = {"plan_id": plan["id"], "source_version": plan["source_version"]}
        first = client.post("/incidents/SHIP-421/execute", json=execution_request)
        first.raise_for_status()
        second = client.post("/incidents/SHIP-421/execute", json=execution_request)
        second.raise_for_status()
        if first.json() != second.json():
            raise RuntimeError("Repeated execution was not idempotent")
        snapshot = client.get("/incidents/SHIP-421")
        snapshot.raise_for_status()
        state = snapshot.json()
        if len(state["executions"]) != 1 or state["state"]["status"] != "verified":
            raise RuntimeError("Operational verification failed")
        if not any(event["name"] == "agent_investigation_completed" for event in state["events"]):
            raise RuntimeError("Agent trace was not persisted")
        print(f"Verified Bedrock run: {len(run['plans'])} plans, {len(run['tool_trace'])} MCP calls")
        print(f"Plan: {plan['kind']}; projected ETA: {plan['projected_completion_eta']}")
        print(f"Token usage: {run['usage']}; one execution; audit events: {len(state['events'])}")


if __name__ == "__main__":
    main()
