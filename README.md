# LogiOps AI

An agent that investigates and resolves logistics exceptions from an incident
inbox: a delayed truck, a carrier that stopped departures, an import held at
customs, two orders competing for the same stock. For each one it queries
orders, inventory and routes, compares alternatives by cost, ETA and order
priority, requests human approval, executes the chosen plan, and verifies the
result.

It behaves like an assistant you talk to, not a form: ask "any delays today?"
for a briefing on the whole queue, say "remember my spend cap is $250" and that
preference steers every later pick (it never approves anything), and each reply
ends in one short spoken line for a voice assistant to read aloud.

Built for the **Amazon Developer Hackathon**, Alexa+ track (self-hosted MCP
server, Streamable HTTP) + AWS Builder Mini Challenge. Runtime: Amazon
Bedrock.

## Submission

| Tag | Devpost | Live demo |
|---|---|---|
| _pending_ | _pending_ | Deployed on AWS; URL and token in the Devpost testing instructions (hosting is optional, D-AMZ-1) |

## For judges

No AWS account is needed: `docker compose up --build` (or `uv sync --extra dev` and
the replay command in `docs/hackathon/testing-instructions.md`) runs the whole demo.
`uv run python scripts/rehearse_api.py` walks through it headless and prints PASS or FAIL.

## Architecture

```text
 Browser (/demo): Alexa+ device screen, conversation, voice, inbox, preferences, MCP App card
        |  REST (approve, execute, preferences)    |  MCP over Streamable HTTP (/mcp)
        v                                          v
 +--------------------------------------------------------------+
 |  FastAPI app: bearer token, rate limits, no-store            |
 |  +-----------------------+   +----------------------------+  |
 |  | MCP server (8 tools,  |   | Workflow core + SQLite     |  |
 |  | no approval tool)     |-->| versioned plans, approvals |  |
 |  +-----------------------+   | bound to plan + version,   |  |
 |        ^                     | idempotent execution,      |  |
 |        | in-process MCP      | audit events; operator     |  |
 |        |                     | preferences (fixed rules)  |  |
 |  +-----------------------+   +----------------------------+  |
 |  | Agent: Bedrock        |                                   |
 |  | Converse tool loop:   |  (replay mode: scripted model)    |
 |  | investigate, ask,     |                                   |
 |  | briefing              |                                   |
 +--+-----------------------+-----------------------------------+
```

More detail in `docs/architecture.md`.

## Settings

| Variable | Purpose | Default |
|---|---|---|
| `LOGIOPS_AGENT_MODE` | `bedrock` or `replay` (scripted model, zero tokens) | `bedrock` |
| `LOGIOPS_DB_PATH` | SQLite database | `data/logiops.sqlite3` |
| `LOGIOPS_SCENARIO_ANCHOR` | when the synthetic incidents are due: `relative` (the first orders due tomorrow, Lima time; stale dates move forward on their own), `fixed` (the seed's own dates) or a `YYYY-MM-DD` day | `relative` |
| `LOGIOPS_PUBLIC` | `1` for public mode (requires the token and `LOGIOPS_PUBLIC_HOST`) | off |
| `LOGIOPS_ACCESS_TOKEN` | bearer token, at least 32 characters in public mode | none |
| `LOGIOPS_PUBLIC_HOST` | the one public hostname (also the MCP allowed host) | none |
| `LOGIOPS_SANDBOX_HOST` | second hostname that serves only the MCP Apps sandbox proxy | `127.0.0.1`/`localhost` pair locally |
| `LOGIOPS_TRUST_CLOUDFRONT` | identify viewers by `CloudFront-Viewer-Address` | off |
| `LOGIOPS_AGENT_LIMIT_PER_MINUTE` | paid agent calls per viewer per minute | `10` |
| `LOGIOPS_DAILY_MODEL_CALLS` | live model calls per day (Lima time) for the whole demo; each request reserves its run's maximum and releases what it did not use, and a run that no longer fits answers from replay with `fallback: "daily_budget"` | `150` |
| `AWS_REGION`, `BEDROCK_MODEL_ID` | Bedrock region and model profile | `us-east-1`, `global.anthropic.claude-sonnet-4-6` |

## Status

Four synthetic incidents (see `docs/demo-scenario.md`), the MCP Streamable
HTTP endpoint, the Bedrock Converse tool loop, the approval gate, and
operational verification run locally. Each incident is isolated: its plans,
approvals, executions and audit events never mix with another's. A replay mode
runs the same MCP calls without AWS charges. A browser interface is available
at `/demo`. See `docs/hackathon/decisions.md` for decisions and
`docs/demo-scenario.md` for the synthetic data.

Operator preferences (`GET`/`PUT`/`DELETE /operator/preferences`) persist in
the same SQLite file across sessions and restarts; fixed rules turn them into a
preferred plan, which `investigate_incident` reports to every MCP client. A
briefing (`POST /agent/briefing`) ranks the open incidents with read tools
only. Every agent reply carries a short `spoken` line.

A public HTTPS deployment runs on AWS (CloudFront, EC2, Bedrock); its URL and
access token are in the submission's testing instructions. The infrastructure
and deployment procedure live in [`infra/amazon/README.md`](infra/amazon/README.md).
Local tests make no live Bedrock call.

Every pull request targets `main` (CI fails otherwise), and
`scripts/deploy_ec2.py` deploys only a clean checkout of `origin/main`.

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

Open the browser demo at <http://127.0.0.1:8000/demo>. It opens on a
simulated Alexa+ screen (an Echo Show-style device): a voice orb that shows
Ready, Listening, Thinking (with the real seconds elapsed) and Speaking; what was
heard and the short spoken reply in large type; chips for the incident, its
critical units at risk and the plan on screen; the plan's legs on a map of Peru;
each order's promise against its projected arrival; and, after each reply, the
recorded tool trace replayed step by step with the result of the data check.
Below it, the operator view shows the same incident in full. The inbox
lists the four incidents, open ones first, then by critical units at risk
(units of critical orders that nothing on hand delivers on time), priority and
due time; pick one (or link to it, as in
`/demo#SHIP-433`, or just name it: "what about SHIP-452?"). Each incident keeps
its own conversation. The demo simulates the Alexa+ experience as a
conversation: ask "What's happening with SHIP-421?" by text, or by voice in browsers with speech recognition (Chrome, Edge), and
optionally have replies read aloud. Say "approve the recommended plan"; the
assistant reads the plan back (price, delay, any critical order left late) and
approves only after "yes". Then say "execute it". Those requests use the same
REST approval and execution endpoints as the buttons, so the version checks are
identical. The plan cards, timeline, and a stock-change control show how a data
change invalidates an earlier approval. A chat message acts only when the whole
message comes from a closed grammar: a verb and words that name a plan by kind,
price or pick ("approve the split plan", "approve the cheapest plan", "approve
the $240 plan", "ok, execute it"). Questions, negations ("please don't execute it
yet"), commands buried in a longer sentence and any other word ("approve
nothing", "execute it tomorrow") go to the agent and never act. On the public deployment, paste the
operator token into the page to connect. It is kept for that browser tab only
(`sessionStorage`), so a reload does not ask again and closing the tab forgets it.

The API reference is at <http://127.0.0.1:8000/docs>. The MCP endpoint is
<http://127.0.0.1:8000/mcp> and negotiates MCP protocol version 2025-11-25
(the core protocol; MCP Apps, below, is an extension with its own version).
The SQLite database is created at
`data/logiops.sqlite3` and survives server restarts. Set `LOGIOPS_DB_PATH` to
change the location. The default configuration is **local only**. Do not bind
it to a public interface without `LOGIOPS_PUBLIC=1`, a random
`LOGIOPS_ACCESS_TOKEN` of at least 32 characters, and HTTPS. In public mode the
token guards both REST and MCP. In a single process, MCP requests are limited
to 60 per minute and agent calls (investigations, follow-ups and briefings,
each one calls a paid model) share a budget of 10 per minute per viewer. Behind CloudFront, set `LOGIOPS_TRUST_CLOUDFRONT=1` so viewers are
identified by the `CloudFront-Viewer-Address` header instead of the shared
edge IP; only do this when the origin accepts traffic exclusively from
CloudFront. The agent's own in-process MCP calls are exempt from the MCP
limit. Responses carry `Cache-Control: no-store`. A production deployment
needs shared rate limiting.

### Agent investigation

```sh
curl -sS http://127.0.0.1:8000/incidents        # the inbox
curl -sS -X POST http://127.0.0.1:8000/demo/reset  # every incident, and clears the preferences
curl -sS -X POST http://127.0.0.1:8000/demo/reset \
  -H 'Content-Type: application/json' -d '{"incident_id": "SHIP-433"}'  # one incident
curl -sS -X POST http://127.0.0.1:8000/incidents/SHIP-433/agent/investigate \
  -H 'Content-Type: application/json' -d '{}'
curl -sS -X POST http://127.0.0.1:8000/demo/reset
curl -sS -X POST http://127.0.0.1:8000/incidents/SHIP-421/agent/investigate \
  -H 'Content-Type: application/json' -d '{}'
curl -sS http://127.0.0.1:8000/incidents/SHIP-421
```

The agent receives only read and investigation tools. Its MCP tool results,
response, and token usage are recorded in the incident's events. The API
returns the calculated plans separately from the model's explanation.

Before an answer is shown, a deterministic grounding check (`logiops/evaluator.py`)
reads it, spoken line included, against the incident's data: it must end with
`Recommended plan:` naming a real plan; every dollar amount, hour value and
unit count must match the plans, orders, stock, carrier quotes or the saved
preferences (spend cap and note), or the gap between two of them; every
SHIP-/ORD- id must belong to the incident and every timestamp must be one in
its data; and it must not claim that anything was approved, executed or
delivered. A failed check goes back to the model once with the reasons, if at
least 18 of the 50 seconds remain; an answer that still fails is returned with
`grounded: false`. The response and the recorded event carry `evaluations`
(one per attempt) and `grounded`. For a
deterministic rehearsal, launch the server with `LOGIOPS_AGENT_MODE=replay`;
the response says `mode: replay` and reports zero tokens. Normal mode is
`bedrock`. It calls Converse through boto3 with SDK retries, and a run stops
with a clear error after 50 seconds so it always answers before CloudFront's
60-second origin timeout. Live calls share a daily budget for the whole demo
(`LOGIOPS_DAILY_MODEL_CALLS`): when a run no longer fits, the response says
`mode: replay` with `fallback: "daily_budget"`, and the page says so above the
conversation until midnight, Lima time.

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
A follow-up passes the same data check without needing a pick
(`evaluator.check_facts`): its figures may also come from the question and
earlier user turns (a hypothetical "only 11 units"), and once the record shows
an approval or execution it may say so in the passive voice ("was executed").

### Queue briefing

```sh
curl -sS -X POST http://127.0.0.1:8000/agent/briefing \
  -H 'Content-Type: application/json' -d '{"question": "Any delays today?"}'
```

The agent calls `list_incidents` (and, if it needs to, the other read tools),
keeps the inbox order (open first, then the most critical units at risk,
priority and due time) and ends with `Start with: <incident id>`,
returned as `start_with`. It cannot calculate plans: `investigate_incident`
is not in its toolset, so a briefing changes nothing and stores nothing. In
the browser, "Any delays today?" or "brief me" runs it and marks that incident
"Start here" in the inbox. The first message on the page also summarises the
queue, from the inbox itself, at no cost. The briefing passes the data check
against every incident's facts (amounts, delays, units, ids and times), with one
revision. In the browser, every checked reply carries a badge: "Checked against
the data", "… after one revision", or, in red, "Did not pass the data check"
with the first reason, plus a notice that the plan cards are the reference.

### Operator preferences

```sh
curl -sS -X PUT http://127.0.0.1:8000/operator/preferences \
  -H 'Content-Type: application/json' \
  -d '{"rule": "balanced", "max_cost_usd": 250, "note": "Hospitals first"}'
curl -sS -X POST http://127.0.0.1:8000/incidents/SHIP-433/investigate  # the plans to pick from
curl -sS http://127.0.0.1:8000/incidents/SHIP-433   # "preference": the plan it points to, and why
```

Two rules: `balanced` (the default ranking: critical orders, then the worst
delay, then late units, then cost) and `cheapest_unless_critical_late`, plus an optional spend cap per
incident and a note of up to 200 characters. `logiops/preferences.py` applies
them to the calculated plans by fixed rules, never by the model: with a $250
cap, SHIP-433, SHIP-452 and SHIP-460 move to a cheaper plan, and the result
says what that trades away and warns if a critical order ends up late.
`investigate_incident` returns the same result as `operator_preferences`, so
the agent, the MCP App card and any other MCP host see one answer; the agent
recommends the preferred plan and the note reaches it as quoted data.
A preference never approves or executes anything. In the browser, say
"remember my spend cap is $250", "from now on pick the cheapest plan unless a
critical order would be late", or "forget my preferences", or use the panel.
Resetting one incident keeps the preferences; resetting everything clears
them.

### Short spoken replies

Every investigation, follow-up and briefing prompt asks the model for a
`Spoken:` line of one or two sentences without ids or tables (in an
investigation, the `Recommended plan:` line still comes last). The server
removes it from the answer (so the stored assessment and the chat stay clean)
and returns it as `spoken`; if the model forgets it, `spoken` is the first
sentence of prose. With "Read replies aloud" on, the browser reads `spoken`,
which is what an Alexa+ device would say, instead of the whole Markdown answer.

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
