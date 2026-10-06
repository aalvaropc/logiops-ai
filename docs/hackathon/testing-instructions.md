# Testing instructions for judges

No AWS account and no hosted demo are needed (see `decisions.md` D-AMZ-1). Everything
below runs on a clean machine in replay mode, which drives the same MCP tools, plan
calculation, approval and audit trail with a scripted model and zero tokens.

## Option 1: Docker (one command)

```sh
docker compose up --build
```

Then open <http://127.0.0.1:8000/demo>. The container starts in replay mode and
publishes the port on `127.0.0.1` only.

## Option 2: Python

Requires Python 3.12+ and [`uv`](https://docs.astral.sh/uv/).

```sh
uv sync --extra dev
LOGIOPS_AGENT_MODE=replay uv run uvicorn logiops.api:app --host 127.0.0.1 --port 8000
```

## Walkthrough

1. **MCP check.** `uv run python scripts/check_mcp.py http://127.0.0.1:8000/mcp`
   performs `initialize`, `tools/list` and `tools/call(get_shipment)` and prints the
   negotiated protocol version (2025-11-25). The server exposes seven tools:
   `get_shipment`, `get_order`, `get_inventory`, `find_alternative_carriers`,
   `investigate_incident`, `get_execution_status` and `execute_approved_plan`.
   There is no approval tool: approval is a REST call made by a person.
2. **Open `/demo` on `127.0.0.1` or `localhost`.** The MCP Apps card is rendered
   through a sandbox proxy that must live on a *different origin*, so the page pairs
   `127.0.0.1` with `localhost`. On any other name (`[::1]`, a LAN IP, a tunnel) the
   card is not shown (it fails closed) and the rest of the demo still works.
3. **Ask.** Type, or speak in Chrome or Edge: "What's happening with SHIP-421?". The
   agent calls the MCP tools and the reply lists three plans: wait ($0, 12 h late),
   reroute ($80, 3 h late), split + express ($120, on time). An **MCP App** card with
   the three plans appears under the reply.
4. **Select, then approve.** "Select for approval" on the card only *selects* the plan;
   the Approve button then names it. Approval is bound to that plan and data version.
   Saying "approve the recommended plan" does the same.
5. **Follow-ups.** Ask "How much is the reroute?". It is answered from the stored
   investigation (`POST /incidents/SHIP-421/agent/ask`) without re-running it.
   Questions never act: "Should we approve the split plan?" gets an answer, not an approval.
6. **Execute.** "Execute it". The allocations are applied once, notifications are
   simulated and all 20 units are accounted for. The timeline records each step.
7. **Stale data.** Reset, investigate and approve again, then apply a stock change of
   11 units: the approval no longer applies, "execute it" is refused, and a new
   investigation offers only the plans that are still feasible.
8. **Idempotence.** Repeat `POST /incidents/SHIP-421/execute` with the approved
   `plan_id` and `source_version`: the response is identical and nothing is duplicated.

Or run the whole flow headless: `uv run python scripts/rehearse_api.py` prints PASS or
FAIL for each step against a replay server it starts itself.

## Tests

```sh
env -u LOGIOPS_ACCESS_TOKEN -u LOGIOPS_AGENT_MODE -u LOGIOPS_PUBLIC -u LOGIOPS_PUBLIC_HOST \
    -u LOGIOPS_SANDBOX_HOST uv run pytest -q
```

`scripts/clean_room.sh <ref>` clones a ref into a temporary directory and runs the
install, the tests, the Docker build and `check_mcp.py` from scratch.

## Live Bedrock (optional, costs a few cents)

Run `aws login --region us-east-1` and start the server without
`LOGIOPS_AGENT_MODE`; the meta line under each reply then says `bedrock mode` and
shows real token counts. A hosted deployment, if any, is described in the
submission together with its access token.
