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
 |  | MCP server (12 tools, |   | Workflow core + SQLite     |  |
 |  | no approval tool,     |-->| versioned plans, approvals |  |
 |  | Agent Skill resource) |   | bound to plan + version,   |  |
 |  +-----------------------+   | idempotent execution,      |  |
 |        ^                     | audit events; operator     |  |
 |        | in-process MCP      | preferences (fixed rules)  |  |
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
| `LOGIOPS_MCP_LIMIT_PER_MINUTE` | MCP and memory requests per viewer per minute | `60` |
| `LOGIOPS_DAILY_MODEL_CALLS` | live model calls per day (Lima time) for the whole demo; each request reserves its run's maximum and releases what it did not use, and a run that no longer fits answers from replay with `fallback: "daily_budget"` | `150` |
| `AWS_REGION`, `BEDROCK_MODEL_ID` | Bedrock region and model profile | `us-east-1`, `global.anthropic.claude-sonnet-4-6` |
| `LOGIOPS_VOICE` | `polly` (Amazon Polly) or `browser` (the browser's own voice) | `polly` with `bedrock`, `browser` with `replay` |
| `LOGIOPS_POLLY_VOICE`, `LOGIOPS_POLLY_ENGINE` | Polly voice and engine | `Ruth`, `generative` |
| `LOGIOPS_DAILY_SPEECH_CHARS` | characters Polly may synthesize per day (Lima time) for the whole demo; repeated lines come from the cache and cost nothing | `30000` |
| `LOGIOPS_COGNITO_ISSUER`, `LOGIOPS_COGNITO_DOMAIN`, `LOGIOPS_COGNITO_CLIENT_ID` | turn on OAuth 2.1 sign-in: the user pool's issuer URL, its hosted domain, and the public PKCE app client (`LOGIOPS_COGNITO_EXTRA_CLIENT_IDS` allows more clients) | off |
| `LOGIOPS_MEMORY_ID` | the Amazon Bedrock AgentCore Memory that keeps conversations across sessions; without it they are kept in SQLite | SQLite |
| `LOGIOPS_ALERT_SCAN_SECONDS` | how often the proactive alert watcher scans; `0` turns the background scan off (a stock change is still scanned at once) | `30` |

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

Open the browser demo at <http://127.0.0.1:8000/demo>. It is a simulated
Alexa+ device (an Echo Show-style screen, full-screen on a phone) that shows
one card at a time: the home card with the incident inbox as a carousel (open
ones first, then by critical units at risk, priority and due time; "Start
here" marks the briefing's pick); the incident card with its ETAs, local stock,
the plan's legs on a map of Peru and each order's promise against its projected
arrival; the plans card with the interactive MCP App; a confirmation card that
reads an approval or a price back with Yes / No; the receipt; a proactive
alert; and the result card after execution. Below the card, the device shows
what it heard and the short spoken reply in large type, a voice orb (Ready,
Listening, Thinking with the seconds elapsed, Speaking), suggestion chips, the
microphone (Chrome, Edge) and a text field; "More" opens the whole
conversation with the recorded tool trace and the data-check badge. Open an
incident by tapping its card, by linking to it (`/demo#SHIP-433`) or by naming
it ("what about SHIP-452?"); each incident keeps its own conversation.

Ask "What's happening with SHIP-421?" and say "approve the recommended plan":
the assistant reads the plan back (price, delay, any critical order left late)
and approves only after "yes" (spoken, typed or tapped on the card). Then say
"execute it". Those requests use the same REST approval and execution
endpoints as the operator console's buttons, so the version checks are
identical. A message acts only when the whole message comes from a closed
grammar: a verb and words that name a plan by kind, price or pick ("approve
the split plan", "approve the cheapest plan", "approve the $240 plan", "ok,
execute it"). Questions, negations ("please don't execute it yet"), commands
buried in a longer sentence and any other word ("approve nothing", "execute it
tomorrow") go to the agent and never act.

The operator console at <http://127.0.0.1:8000/console> shows the same
incident in full: inbox, plan cards with the Approve button, execution,
bookings, preferences, the audit trail and a Developer drawer (operator token,
stock-change control that invalidates an earlier approval, reset, links to the
MCP endpoint). On the public deployment, paste the operator token there to
connect; it is kept for that browser tab only (`sessionStorage`), so a reload
does not ask again and closing the tab forgets it.

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
`bedrock`. The tool loop runs on Strands Agents (`logiops/strands_runtime.py`):
a model provider over the same Converse client (boto3 with SDK retries), one
agent tool per allowed MCP tool on the in-process session, and hooks that keep
the loop's guards. A run stops
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
`ui://logiops/resolution-options.<sha8>.html`, served as
`text/html;profile=mcp-app`). The URI carries a hash of the view, so a host
never shows a stale cached copy after an update. A host that supports MCP Apps
(extension version 2026-01-26) renders the calculated plans as cards next to
the conversation, shows the tool's `invoking` and `invoked` status lines, and
the result repeats `_meta.ui` for hosts that read it there. The view follows
the host context: light or dark theme, the host's style variables, safe-area
insets, and a compact layout under 480 px. It shows five plans at a time,
always including the pick. The resource declares an empty CSP allowlist: the
view makes no network calls. The card can only ask the
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
no separate sandbox origin is available. Its MCP client runs `initialize` once
and then sends `MCP-Protocol-Version: 2025-11-25` on every request. It passes a
full `hostContext` (theme, display mode, container size, locale, Lima time
zone, device capabilities, safe-area insets), and its "Light card" toggle
sends `ui/notifications/host-context-changed`.

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
botocore's service model without a paid call. The browser walkthroughs
(`tests/browser/`, Playwright against a replay server, axe with zero
violations at 1440 and 390 px) need the `browser` extra and a browser:
`uv sync --extra dev --extra browser`, `uv run playwright install --only-shell chromium`,
then `LOGIOPS_BROWSER=1 uv run pytest -q tests/browser`. CI runs them in the
`browser` job.

### Carrier booking and payment

A plan that uses paid carriers or services can be booked and paid, with a
receipt (`logiops/booking.py`):

1. **Quote.** `POST /incidents/{id}/bookings/quote` (or the MCP tool
   `quote_carrier_booking`) prices one current plan, by default the approved
   one: the carriers' cost, a $5 service fee and IGV 18 % on both. It holds
   for ten minutes and charges nothing. Its `summary` is the read-back, for
   example "carriers and services $120.00, service fee $5.00, IGV 18% $22.50,
   total $147.50, charged to the corporate card ending 4242".
2. **Confirm.** `POST /quotes/{quote_id}/confirm` (MCP: `book_carrier`) takes
   the total the person confirmed and an idempotency key. The payment is
   simulated. It charges only when every check passes at that moment:
   - the amount equals the total recalculated now;
   - the quote has not expired;
   - the plan is the one a person approved on the current data (or it was
     already executed).

   Otherwise the answer is a 409 that says "Nothing was charged" and what to
   do. Over MCP, an unapproved plan returns the URL elicitation described
   below. The same key returns the same booking, and a plan is booked at most
   once.
3. **Receipt.** The booking carries a confirmation number (`LGO-` and six
   characters) and a written confirmation. `GET /bookings/{number}/receipt` is
   a printable page, and `receipt://logiops/{number}` is the same receipt in
   Markdown for MCP clients.

`book_carrier` is destructive, idempotent and model-only. `/demo/reset`
forgets the bookings, and the follow-up check accepts the booking's amounts.

In the demo, "book it" (or the "Book and pay" chip) reads the plan and the full
price back before anything happens. If the plan is not approved yet, a single
"yes" approves it and pays, because the read-back named both. The reply gives
the written confirmation and speaks the number character by character. The
receipt shows in the execute panel and on the device screen. Other commands:
- "no" drops the purchase;
- a bare "yes" with nothing pending does nothing;
- the idempotency key is chosen at read-back, so a retry after a network error
  cannot pay twice;
- the pending quote survives a reload in `sessionStorage`, and "resume" reads
  it back again.

### Sign-in (OAuth 2.1 with Amazon Cognito)

The MCP server is an OAuth 2.1 protected resource, as the Alexa+ account linking
guide and the MCP authorization spec ask (`logiops/oauth.py`). It is turned on
by the three `LOGIOPS_COGNITO_*` settings; without them nothing changes.

- **Discovery.**
  - `/.well-known/oauth-protected-resource/mcp` (RFC 9728) names the resource
    `https://<host>/mcp`, its authorization server and the two scopes:
    `…/mcp/incidents.operate` and `…/mcp/bookings.write`.
  - Cognito's own discovery document does not list PKCE methods, so
    `/.well-known/oauth-authorization-server` (RFC 8414) is served here. It has
    `code_challenge_methods_supported: ["S256"]`, Cognito's authorize endpoint,
    and a token endpoint here (`/auth/token`). That endpoint forwards only
    authorization-code grants (with their PKCE verifier) and refresh grants of
    the allowed public clients.
- **Tokens.** Access tokens are Cognito JWTs. Each one is checked for:
  - an RS256 signature against the pool's JWKS (cached, refetched at most once
    a minute for an unknown key);
  - the issuer, the expiry, and `token_use: access`;
  - an allowed `client_id`;
  - the scope that the action needs.

  The signed-in user's name is recorded on quotes and bookings.
- **Guests.** Without a token a visitor can read, ask the agent and use the
  read tools. On the public deployment the agent then runs on the replay model
  (`fallback: "sign_in"`), so a guest never spends a model call. Approving,
  executing, changing data, speaking with Polly, booking (and the MCP tools
  `execute_approved_plan`, `quote_carrier_booking`, `book_carrier`,
  `get_booking`) answer `401` with `WWW-Authenticate: Bearer
  resource_metadata="…", scope="…"`. A token without the scope gets `403
  insufficient_scope`, and a bad token gets `401 invalid_token`.
- **Static token.** The operator token still works, for scripts and the
  testing instructions.

**Linking the account in the demo.** The page acts as the Alexa+ app would. On
"Link account" (or "link my account"):
1. It creates a 64-character PKCE verifier, its S256 challenge and a random
   `state`, keeps them in `sessionStorage`, and opens Cognito's sign-in.
2. On the way back it checks the `state`, exchanges the code and verifier at
   `/auth/token`, and removes `?code` from the address with `replaceState`.
3. The tokens stay in `sessionStorage` (never `localStorage`) and travel as
   the bearer. A `401 invalid_token` refreshes once, then retries.

The approver name becomes the signed-in user. "Sign out" returns to guest.
**Preferences are per user**: a signed-in user's spend cap and rule belong to
their account (keyed by the token's `sub`). The agent's in-process MCP calls
carry that user's token, so `investigate_incident` applies their own
preferences. Guests and the operator token share the demo profile.

### Voice (Amazon Polly)

On a voice device every reply is heard, so the demo speaks with Amazon Polly
(`logiops/voice.py`, `POST /voice/speech`). The voice is `Ruth` on the
generative engine, on by default in Bedrock mode. Each reply's spoken line is
cleaned for speech (no Markdown, links or internal ids) and cut at a sentence
end under 600 characters. It is synthesized once and cached in SQLite by the
hash of the text, so repeated lines are free.

A daily character budget (`LOGIOPS_DAILY_SPEECH_CHARS`) bounds the cost for
everyone, and speech has its own per-minute limit. When Polly is off, over
budget or failing, the endpoint answers 503 with `fallback: "browser"` and the
page reads the line with the browser's voice. After a failure, such as a
missing permission, Polly rests for five minutes.

The person can always talk over it: the microphone, typing or a chip stops the
audio (barge-in). If the agent takes longer than 2.5 seconds, a short filler
("One moment, I'm checking the shipment and the carriers") is spoken while it
works. In replay mode the demo uses the browser's voice, so judges need no AWS
account.

### Memory across sessions (AgentCore Memory)

LogiOps remembers what each person said and decided, so the next session picks
up where the last one ended (`logiops/memory.py`). It has one interface and two
backends.

**Amazon Bedrock AgentCore Memory**, when `LOGIOPS_MEMORY_ID` is set:
- every turn is a conversational event (`CreateEvent`, role USER or ASSISTANT,
  with the incident as metadata) under the actor and the page's session;
- recall reads the latest earlier session's events (`ListSessions`,
  `ListEvents`) and the long-term records that the memory's strategies
  extracted (`RetrieveMemoryRecords` in `/users/{actorId}/preferences` and
  `/users/{actorId}/facts`).

**SQLite** otherwise keeps the same turns (the last 200 per person), without
long-term extraction.

- **Privacy.** The actor is a SHA-256 of the signed-in user's token subject,
  never the subject itself. The operator token shares one demo actor, and
  guests are never remembered.
- **Off the request path.** `POST /memory/turns` answers `202` and writes after
  the response. A memory outage is logged and never breaks a reply.
- **Welcome back.** A new browser session opens with "Welcome back, judge. Last
  time (Oct 12, 14:05 Lima time) we were on SHIP-433 and you said “book it”…".
  It is built only from what was said. "Pick up where we left off" reopens that
  incident.
- **Live runs.** The long-term facts reach the agent as a `<memory>` block in
  an investigation, or a `memory` field in a follow-up's context, both marked
  as data and never as a source of plan figures. Their figures join the
  grounding check. The replay model never sees them.
- **Forget me.** "Forget me" (`DELETE /memory`) deletes the person's events and
  long-term records, and that exchange itself is not remembered. Saved
  preferences stay until "forget my preferences".

### Proactive alerts

The agent does not wait to be asked when the data moves under a decision
(`logiops/alerts.py`). An incident qualifies when it was investigated, its
data changed afterwards (for example a stock change), and it was not executed.
The watcher then does four things:
1. recalculates the plans, which is deterministic and costs nothing;
2. applies the saved preferences;
3. compares the new pick with the plan that was approved, or picked, before;
4. stores one alert per data version and records an `autopilot_decision`
   event.

It never approves or books: the alert proposes, and a person decides. For
example: "Heads up on SHIP-421: Arequipa stock is now 3 units, so your
approved plan “Fulfill local stock and send the rest express” no longer
applies. I recalculated the plans. The new pick is “Move the full order to an
alternative carrier”: $80, 3 h late. Nothing was approved." If no plan works
any more, the alert says so.

It scans right after `POST /demo/inventory`, and in the background every
`LOGIOPS_ALERT_SCAN_SECONDS` (30 by default; 0 turns it off). The endpoints
are `GET /alerts` and `POST /alerts/{id}/dismiss`, and MCP clients read the
alerts with `list_alerts`. The demo checks every five seconds:
- an alert for the open incident is spoken and written in the conversation,
  with the new pick preselected for approval;
- an alert for another incident lights up a bell in the top bar that opens
  it.

### Agent Skill

[`skills/logiops-exception-desk/SKILL.md`](skills/logiops-exception-desk/SKILL.md)
is an [Agent Skill](https://agentskills.io): YAML frontmatter (`name`,
`description`, `license`, `compatibility`, `metadata`) and a playbook for these
tools. It covers the workflow, the rules (plans by label, projected delivery,
Lima time, no tool approves), how to speak on a voice device (at most five
options, a read-back before anything is approved), and what to do when a tool
fails. The MCP server serves it as the resource
`skill://logiops-exception-desk/SKILL.md` (`text/markdown`), and its
instructions point to it, so any MCP client can load the same playbook.

The agent reads that resource over MCP at the start of every run. It sends the
skill to Bedrock as the first system block, before the task prompt, followed by
a `cachePoint`, so later turns of a run read the tools, skill and prompt from
the prompt cache (`usage` reports `cacheReadInputTokens` and
`cacheWriteInputTokens`). The run reports which skill it loaded (`skill`: name,
URI and SHA-256), and the device screen lists it before the tool steps. In
replay mode the skill is loaded the same way, but the scripted model does not
read it. Tests check the frontmatter rules, that every tool it names exists,
and that the file, the MCP resource and the system block are byte-identical.
The release archive and the Docker image include it.

### Prompts, completions, incident records and URL elicitation

Beyond tools, the MCP server offers what a host needs to start a conversation:

- **Prompts.** `morning_briefing` ("any delays today?") and
  `investigate_incident(shipment_id)`. Each embeds the Agent Skill as a resource
  message, then asks for the briefing or the investigation. Neither approves
  anything.
- **Completions.** `completion/complete` suggests incident ids for the prompt
  argument and the resource template, in the order to work them. It accepts
  "43", "ship-46" or "case 45".
- **Incident records.** The resource template `incident://{shipment_id}` returns
  one incident as JSON: its summary, shipment, the plans for the current data
  version, the current approval and the executions.
- **URL elicitation.** `execute_approved_plan` on a current plan that no person
  has approved returns the MCP error `-32042` (URL elicitation required). It
  carries the operator panel's URL and a message that names the plan by its
  label. A host that supports URL elicitation can open the panel; any other
  client still gets a message that explains what to do. A stale or unknown plan
  is an ordinary tool error with a next step.

`scripts/check_mcp.py` lists the prompts, resources and templates, and fails
if the skill resource is missing.

## License

MIT — see [LICENSE](LICENSE).
