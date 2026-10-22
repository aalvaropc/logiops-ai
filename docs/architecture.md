# Architecture

LogiOps AI is a single FastAPI process that serves three things:
- a self-hosted MCP server;
- two web pages, the simulated Alexa+ device and the operator console;
- an AI agent.

One rule shapes the design:
- the model proposes;
- code calculates every plan and checks every answer;
- only a person approves;
- execution is bound to the exact plan and data version that person approved.

## The system at a glance

```text
 Simulated Alexa+ device      Operator console        Any MCP client
 (/demo)                      (/console)              (MCP Inspector, Claude, ...)
     | MCP + REST                 | REST                  | MCP over Streamable HTTP
     +----------------------------+-----------------------+
                                  |
+---------------------------------v-------------------------------------------+
| FastAPI app                                                                 |
|   access: operator token, OAuth 2.1 scopes (Amazon Cognito), read-only      |
|           guests, per-viewer limits, a daily model budget                   |
|                                                                             |
|   MCP server (/mcp)  ----------------->  Workflow core  ----->  SQLite      |
|   12 tools, 2 prompts, resources,        plans, approvals,       incidents, |
|   the MCP App view, the Agent Skill      execution, bookings,    events,    |
|          ^                               alerts, preferences     bookings   |
|          | in-process MCP                                                   |
|   Agent on Strands Agents  -->  data check  -->  answer + spoken line       |
+----------|------------------------------------------------------------------+
           v
 Amazon Bedrock (Claude Sonnet 4.6)   AgentCore Memory   Amazon Polly   Amazon Cognito
```

## Components

| Component | Responsibility | Code |
|---|---|---|
| Pages | The device (one card at a time, voice, the plans as an MCP App) and the console (a three-column desk). ES modules, no build step. | `logiops/static/` |
| MCP Apps host | Renders the plans card through a sandbox proxy on a second origin. | `logiops/static/app/mcp-host.js` (the [`mcp-apps-web-host`](https://github.com/aalvaropc/mcp-apps-web-host) library) |
| HTTP and access | Routes, the operator token, OAuth 2.1 scopes, guests, per-viewer limits. | `logiops/api.py`, `logiops/routes/`, `logiops/security.py`, `logiops/oauth.py` |
| MCP server | Tools, prompts, resources, the MCP App view, the Agent Skill, URL elicitation. | `logiops/mcp_server.py`, `logiops/mcp_transport.py`, `logiops/skill.py` |
| Workflow core | Calculates plans, binds approvals to plan and version, runs execution once, records events. | `logiops/service.py`, `logiops/scenario.py`, `logiops/tools.py` |
| Agent | Investigates, answers follow-ups and briefs the queue, on Strands Agents over the Bedrock Converse API. | `logiops/agent.py`, `logiops/strands_runtime.py`, `logiops/bedrock.py` |
| Data check | Checks every answer against the incident's data before it is shown. | `logiops/evaluator.py`, `logiops/presentation.py` |
| Replay | A scripted model with zero tokens, for local runs and fallbacks. | `logiops/replay.py` |
| Bookings | Quote, confirm once, receipt (simulated payment). | `logiops/booking.py` |
| Alerts | Watches investigated incidents and raises an alert when their data changes. | `logiops/alerts.py` |
| Preferences, memory, voice | A rule, a spend cap and a note; memory across sessions; spoken replies. | `logiops/preferences.py`, `logiops/memory.py`, `logiops/voice.py` |
| Budget and metrics | Daily model and speech budgets; outcomes derived from events. | `logiops/budget.py`, `logiops/metrics.py`, `logiops/telemetry.py` |

## The main flows

### Investigate

1. The page asks the agent to investigate. The app reserves the run's model calls
   from the daily budget. If the run does not fit, or the model service is down,
   the replay model answers and the page says so.
2. The agent loads the Agent Skill over MCP, then calls read tools through the
   same MCP server, in-process: the shipment, its orders and the carrier quotes.
   Each call streams to the page as a lit station.
3. `investigate_incident` calculates every feasible plan in code (cost, arrival,
   late units, critical orders) and records the plans against the incident's
   data version. The model compares the plans and explains its pick; it never
   prices anything.
4. The data check reads the answer, spoken line included:
   - the recommended plan must exist;
   - every amount, hour, unit count, id and timestamp must come from the data;
   - nothing may be claimed as approved, executed or delivered.

   A failed check goes back to the model once. An answer that still fails is
   marked `grounded: false`.
5. The page shows the plans card (an MCP App) and reads the spoken line aloud.

### Approve and execute

1. Only a person approves, through the REST API. No agent tool can approve. The
   approval names the plan id and the data version.
2. Execute runs only if that exact plan is approved on the current version.
3. It applies the plan, records the simulated notifications and verifies the
   result: every unit is accounted for.
4. A second execute returns the recorded result; nothing runs twice.

### Data changes under an approved plan

A stock change moves the incident's data version. That has three effects:
- the earlier approval no longer applies;
- the plans are recalculated, and an alert names the new pick on the device,
  the console and over MCP (`list_alerts`);
- execute is refused until a person approves again.

### Book and pay (simulated)

1. A quote prices one plan (carriers, a service fee and tax), holds for ten
   minutes and charges nothing.
2. Confirm charges only if the person confirmed the exact total and the plan is
   the one approved on the current data. An idempotency key makes it charge at
   most once.
3. A receipt follows, as a page and as an MCP resource.

## Guardrails

- **The model's tools are allowlisted per job.** It can read and run
  `investigate_incident`; it cannot approve, execute or book. A model turn that
  asks for another tool, another shipment or a malformed input ends the run
  before any tool executes.
- **Code calculates; the model explains.** Prices, delays and allocations come
  from the workflow core, and the data check holds every answer to them.
- **A person decides.** Approval is bound to plan and version; execution and
  booking are idempotent.
- **Access.** Guests read and ask. Approving, executing and booking need the
  operator token or a Cognito token with the right scope (`incidents.operate`,
  `bookings.write`). Over MCP, those tools answer `401` with the OAuth challenge.
- **Cost.** The deployment has a daily budget of 40 model calls:
  - 20 are a guest share;
  - each guest visitor gets 9;
  - Polly has its own daily character cap.

  When a budget is spent, the replay model answers and the page says so.

## Data

One SQLite file holds:
- each incident's state with its version;
- the plans per version;
- the approvals and executions;
- an append-only event log, which is the audit trail and the source of
  `GET /metrics`;
- bookings, alerts, preferences, the speech cache and the budgets.

Locally, memory turns are kept in the same file; on the deployment they live in
AgentCore Memory.

Incidents come from a registry: the four built-ins (`docs/demo-scenario.md`)
plus any scenario packs loaded over `POST /scenario/packs` or with
`LOGIOPS_SCENARIO_PACK`. Plans, approvals, executions and events carry their
incident id, so incidents never see or apply each other's plans.

The file records its schema version (`meta.schema_version`, now 2). A database
from an older layout is rebuilt once at startup, in one transaction, and logged
as `schema_migrated`. The data is synthetic, so it is reseeded rather than
converted, and the preferences survive.

## Deployment on AWS

```text
 Browser or MCP client
   |  HTTPS
   +--> CloudFront: the app --------------+  HTTP; the origin admits
   +--> CloudFront: the MCP App sandbox --+  only CloudFront
                                          v
                        EC2: FastAPI, MCP server, pages
                          |-- EBS volume: SQLite
                          |-- Amazon Bedrock, AgentCore Memory, Amazon Polly
                          |   (through the instance role)
                          '-- Amazon Cognito (OAuth 2.1)

 Releases: an S3 archive installed by Systems Manager, no SSH
 Backups:  daily SQLite snapshots in a private S3 bucket
 Guards:   an AWS Budgets action; Route 53 health check -> CloudWatch -> SNS
```

| Service | Purpose |
|---|---|
| Amazon Bedrock | Claude Sonnet 4.6 through the Converse API, with the prompt cache for the Agent Skill and the prompt. |
| Strands Agents | The agent loop: a model adapter over the Converse client, one tool per allowed MCP tool, guard hooks, optional OpenTelemetry. |
| AgentCore Memory | Each signed-in person's turns and long-term facts across sessions ("Welcome back"). |
| Amazon Polly | Reads the spoken line aloud (voice Ruth), cached per text and capped per day. |
| Amazon Cognito | OAuth 2.1 sign-in with PKCE for the pages and for MCP clients; the app publishes the RFC 9728 and RFC 8414 metadata. |
| EC2, EBS | One instance runs the app; SQLite sits on its own volume, so the data survives restarts. |
| CloudFront | A stable HTTPS address; the instance accepts traffic only from CloudFront. |
| S3, Systems Manager | Checksum-verified releases installed without SSH or long-lived keys, and verified database backups. |
| AWS Budgets, Route 53, CloudWatch, SNS | A budget action cuts Bedrock and Polly if a month passes US$60; an alarm e-mails when the demo is down. |

Everything is defined with Terraform in [`infra/amazon/`](../infra/amazon/README.md);
the [decisions log](hackathon/decisions.md) records when each part was provisioned.

## Production path

What stays, what changes, in the order a real desk would need it:

1. **Data.** The MCP read tools (`get_shipment`, `get_order`, `get_inventory`,
   `find_alternative_carriers`) become adapters over the TMS, OMS and WMS, and
   carrier quotes come from the carriers' APIs. The scenario registry already
   models an incident as data (a pack), so the first integration is an importer
   that writes packs from those systems. The plan calculation, the approval
   binding to plan and version, the idempotent execution and the audit trail
   do not change.
2. **Actions.** `execute_approved_plan` and `book_carrier` call the real
   booking and notification systems behind the same idempotency keys. Delivery
   confirmation comes back as events; today every screen says "projected, not
   physically confirmed".
3. **Identity.** Cognito stays, or is replaced by the company's identity
   provider. The scopes (`incidents.operate`, `bookings.write`) already
   separate reading, approving and paying. The operator token is for the demo
   only.
4. **Alexa+.** The device page simulates the Alexa+ experience. The server
   already speaks the protocols Alexa+ add-ons are built on: MCP tools,
   prompts, resources, MCP Apps, an Agent Skill, URL elicitation and OAuth 2.1.
   What I expect is left once the partner-only developer tools open is in
   [`alexa-plus-readiness.md`](hackathon/alexa-plus-readiness.md).
5. **Scale and operations.**
   - SQLite becomes Postgres behind the same service layer.
   - The one EC2 instance becomes a container service behind the same CloudFront
     distribution.
   - `LOGIOPS_OTEL=1` ships the agent's spans to the company's collector.
   - The daily budgets become per-tenant quotas.
