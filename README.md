# LogiOps AI

An agent that investigates and resolves logistics exceptions
(e.g. a delayed shipment): it queries orders, inventory and routes, compares
alternatives by cost and ETA, requests human approval, executes the chosen
plan, and verifies the result.

Built for the **Amazon Developer Hackathon**, Alexa+ track (self-hosted MCP
server, Streamable HTTP) + AWS Builder Mini Challenge. Runtime: Amazon
Bedrock.

## Submission

| Tag | Devpost | Live demo |
|---|---|---|
| _pending_ | _pending_ | _pending (hosting optional, see docs/hackathon/decisions.md D-AMZ-1)_ |

## For judges

No AWS account is needed: `docker compose up --build` (or `uv sync --extra dev` and
the replay command in `docs/hackathon/testing-instructions.md`) runs the whole demo.
`uv run python scripts/rehearse_api.py` walks through it headless and prints PASS or FAIL.

## Architecture

```text
 Browser (/demo): conversation, voice, MCP App card in a sandbox proxy (other origin)
        |  REST (approve, execute, reset)          |  MCP over Streamable HTTP (/mcp)
        v                                          v
 +--------------------------------------------------------------+
 |  FastAPI app: bearer token, rate limits, no-store            |
 |  +-----------------------+   +----------------------------+  |
 |  | MCP server (7 tools,  |   | Workflow core + SQLite     |  |
 |  | no approval tool)     |-->| versioned plans, approvals |  |
 |  +-----------------------+   | bound to plan + version,   |  |
 |        ^                     | idempotent execution,      |  |
 |        | in-process MCP      | audit events               |  |
 |  +-----------------------+   +----------------------------+  |
 |  | Agent: Bedrock        |                                   |
 |  | Converse tool loop    |  (replay mode: scripted model)    |
 +--+-----------------------+-----------------------------------+
```

More detail in `docs/architecture.md`.

## Settings

| Variable | Purpose | Default |
|---|---|---|
| `LOGIOPS_AGENT_MODE` | `bedrock` or `replay` (scripted model, zero tokens) | `bedrock` |
| `LOGIOPS_DB_PATH` | SQLite database | `data/logiops.sqlite3` |
| `LOGIOPS_PUBLIC` | `1` for public mode (requires the token and `LOGIOPS_PUBLIC_HOST`) | off |
| `LOGIOPS_ACCESS_TOKEN` | bearer token, at least 32 characters in public mode | none |
| `LOGIOPS_PUBLIC_HOST` | the one public hostname (also the MCP allowed host) | none |
| `LOGIOPS_SANDBOX_HOST` | second hostname that serves only the MCP Apps sandbox proxy | `127.0.0.1`/`localhost` pair locally |
| `LOGIOPS_TRUST_CLOUDFRONT` | identify viewers by `CloudFront-Viewer-Address` | off |
| `LOGIOPS_AGENT_LIMIT_PER_MINUTE` | paid agent calls per viewer per minute | `5` |
| `AWS_REGION`, `BEDROCK_MODEL_ID` | Bedrock region and model profile | `us-east-1`, `global.anthropic.claude-sonnet-4-6` |

## Status

The SHIP-421 workflow, MCP Streamable HTTP endpoint, Bedrock Converse tool
loop, approval gate, and operational verification run locally. A replay mode
runs the same MCP calls without AWS charges. A browser interface is available
at `/demo`; public HTTPS deployment is pending. See
`docs/hackathon/decisions.md` for decisions and
`docs/demo-scenario.md` for the synthetic data.

The AWS demo infrastructure and deployment procedure live in
[`infra/amazon/README.md`](infra/amazon/README.md). It has not been provisioned
yet; local tests do not claim a remote or live Bedrock run.

## Run with Docker

```sh
docker compose up --build
```

Then open <http://127.0.0.1:8000/demo>. The container runs in replay mode: the
full MCP workflow with a scripted model, no AWS credentials and no cost. The
port is published on loopback only. See `compose.yaml` for running against
live Bedrock with short-lived credentials passed at runtime.

## Setup

Install Python 3.12 or newer and [uv](https://docs.astral.sh/uv/). For a
reproducible demo without AWS credentials, run:

```sh
uv sync --extra dev
LOGIOPS_AGENT_MODE=replay uv run uvicorn logiops.api:app --host 127.0.0.1 --port 8000
```

For the live agent, sign in with `aws login` (boto3 picks up that session, or
any other credentials in its default chain) and ensure
`global.anthropic.claude-sonnet-4-6` is accessible in `us-east-1`. Start the
same server without `LOGIOPS_AGENT_MODE=replay`.

Open the browser demo at <http://127.0.0.1:8000/demo>. It simulates the
Alexa+ experience as a conversation: ask "What's happening with SHIP-421?" by
text, or by voice in browsers with speech recognition (Chrome, Edge), and
optionally have replies read aloud. Say "approve the recommended plan" and
then "execute it"; those requests use the same REST approval and execution
endpoints as the buttons, so the version checks are identical. The plan
cards, timeline, and a stock-change control show how a data change
invalidates an earlier approval. On the public deployment, paste the operator
token into the page to connect. It stays in browser memory until the page is
reloaded.

The API reference is at <http://127.0.0.1:8000/docs>. The MCP endpoint is
<http://127.0.0.1:8000/mcp> and negotiates MCP protocol version 2025-11-25
(the core protocol; MCP Apps, below, is an extension with its own version).
The SQLite database is created at
`data/logiops.sqlite3` and survives server restarts. Set `LOGIOPS_DB_PATH` to
change the location. The default configuration is **local only**. Do not bind
it to a public interface without `LOGIOPS_PUBLIC=1`, a random
`LOGIOPS_ACCESS_TOKEN` of at least 32 characters, and HTTPS. In public mode the
token guards both REST and MCP. In a single process, MCP requests are limited
to 60 per minute and agent calls (investigations and follow-ups, each one
calls a paid model) share a budget of 5 per minute per viewer. Behind CloudFront, set `LOGIOPS_TRUST_CLOUDFRONT=1` so viewers are
identified by the `CloudFront-Viewer-Address` header instead of the shared
edge IP; only do this when the origin accepts traffic exclusively from
CloudFront. The agent's own in-process MCP calls are exempt from the MCP
limit. Responses carry `Cache-Control: no-store`. A production deployment
needs shared rate limiting.

### Agent investigation

```sh
curl -sS -X POST http://127.0.0.1:8000/demo/reset
curl -sS -X POST http://127.0.0.1:8000/incidents/SHIP-421/agent/investigate \
  -H 'Content-Type: application/json' -d '{}'
curl -sS http://127.0.0.1:8000/incidents/SHIP-421
```

The agent receives only read and investigation tools. Its MCP tool results,
response, and token usage are recorded in the incident's events. The API
returns the calculated plans separately from the model's explanation. For a
deterministic rehearsal, launch the server with `LOGIOPS_AGENT_MODE=replay`;
the response says `mode: replay` and reports zero tokens. Normal mode is
`bedrock`. It calls Converse through boto3 with SDK retries, and a run stops
with a clear error after 50 seconds so it always answers before CloudFront's
60-second origin timeout.

### Follow-up questions

```sh
curl -sS -X POST http://127.0.0.1:8000/incidents/SHIP-421/agent/ask \
  -H 'Content-Type: application/json' \
  -d '{"question": "How much is the reroute?", "history": []}'
```

A follow-up answers from the latest investigation of the data being shown
(plans, assessment, approval and execution), with read tools only, so it never
recalculates plans. It returns 409 if there is no investigation for the
current data. The question and up to 8 history turns are sent as quoted JSON
after the context, so user text cannot open or close a block. Answers change
nothing and are not stored; failed calls are audited as `agent_run_failed`
with `job: "ask"`. The browser routes questions (anything ending in `?` or
starting with how/what/should/…) to the agent, never to approve or execute.

### Interactive plan card (MCP Apps)

`investigate_incident` declares an MCP Apps view (`_meta.ui.resourceUri` =
`ui://logiops/resolution-options.html`, served as `text/html;profile=mcp-app`).
A host that supports MCP Apps (extension version 2026-01-26) renders the
calculated plans as cards next to the conversation. The card can only ask the
host to **select** a plan: there is no approval tool, and
`execute_approved_plan` is marked model-only (`_meta.ui.visibility`), so no
view can call it in any host. Approval stays with the operator.

The browser demo is a spec-conformant web host. It reads the resource over
`/mcp` and loads it through a **sandbox proxy** served from a different
origin: `/mcp-app/sandbox.html` on `localhost` when the page is on
`127.0.0.1` (and the reverse), or on `LOGIOPS_SANDBOX_HOST` in public mode.
The proxy puts the view in an inner `allow-scripts` iframe (opaque origin)
under a CSP with no network access, relays messages, and drops the view if it
navigates away. The host checks the proxy's origin on every message, sends
`ui/resource-teardown` before removing the view, and shows no card at all if
no separate sandbox origin is available.

In Swagger, run `POST /demo/reset`, `POST /incidents/SHIP-421/agent/investigate`
(or the deterministic `/investigate` endpoint),
`POST /incidents/SHIP-421/approvals`, `POST /incidents/SHIP-421/execute`, and
`GET /incidents/SHIP-421`, in that order. Copy `plan_id` and `source_version`
from the `split-express` plan into approval and execution requests. Use
`approved_by: "demo-operator"`. `POST /demo/inventory` can change local stock
to demonstrate that an old approval cannot execute a stale plan.

The result verifies operational state changes, **not physical delivery**. The
zero-hour customer delay is a projection from the synthetic carrier times.
Run tests with `uv run pytest`, in a shell without `LOGIOPS_ACCESS_TOKEN`,
`LOGIOPS_AGENT_MODE`, or `LOGIOPS_TRUST_CLOUDFRONT` exported. The MCP
interoperability tests use the official Python MCP client against the
in-process ASGI app, and the Bedrock tests validate request shapes against
botocore's service model without a paid call.

## License

MIT — see [LICENSE](LICENSE).
