# Architecture

## Current local implementation

`logiops/scenario.py` owns four synthetic incidents of different kinds (see
`docs/demo-scenario.md`) and derives each one's cost/ETA options from its data:
every incident lists its options as data, and one fill turns them into
allocations, per-order delays, late units and cost. Only the options the
current stock and capacity can cover are offered. Plans, approvals, executions
and events carry the incident id, so incidents never see or apply each other's
plans. The SQLite layout has a `meta.schema_version` (now 2); a database from
the earlier single-incident layout is rebuilt once at startup, in one
transaction, and the rebuild is logged and recorded as `schema_migrated` events
(the data is synthetic, so it is reseeded rather than converted). `logiops/tools.py` exposes read-only shipment, order,
inventory, and carrier lookups. `logiops/service.py` runs investigation,
approval, execution, and operational verification in SQLite transactions;
it records source versions and audit events. `logiops/api.py` resolves the
settings, builds the stores and clients and mounts one FastAPI router per area
(`logiops/routes/`: pages, incidents, account, agent, scenario, bookings) with
Swagger. `logiops/mcp_server.py` exposes real MCP
tools over Streamable HTTP at `/mcp`. `logiops/agent.py` runs the Bedrock
Converse tool loop through that MCP endpoint on Strands Agents
(`logiops/strands_runtime.py`: a model provider over the Converse client, one
agent tool per allowed MCP tool, guard hooks); `logiops/bedrock.py` calls
Converse with boto3 and the default credential chain (an `aws login` session
locally, the instance role on EC2). `logiops/replay.py` provides an explicit
deterministic local replay. `logiops/security.py` enforces a bearer token when
configured, per-viewer limits for MCP and for agent runs, and `no-store`
responses. Two pages call the same API: `/demo` is the simulated Alexa+ device
(one card at a time: the inbox carousel, the incident with its map and promise
bars, the plans with the MCP App inside, a confirmation with Yes / No, the
receipt, a proactive alert and the result; voice, chips and a "More" sheet with
the whole transcript and the tool trace), and `/console` is the operator
console (plans with Approve, Execute, bookings, preferences, the audit trail,
the session metrics and a Developer drawer). Both are ES modules without a
build step (`logiops/static/app/*` shared, `device/*` for the device,
`console.js` for the console) over `app/mcp-host.js`, a dependency-free MCP
Apps host bridge. `logiops/metrics.py` derives outcome metrics per incident
and per session from the recorded events and bookings (`GET /metrics`), and
`logiops/scenario.py` keeps the incident registry: the built-ins plus any
scenario packs, validated and registered over HTTP (`POST /scenario/packs`) or
at start (`LOGIOPS_SCENARIO_PACK`). `logiops/telemetry.py` turns on OpenTelemetry for
the agent's runs only with `LOGIOPS_OTEL=1`.

`logiops/preferences.py` keeps the operator's saved preferences (a rule, an
optional spend cap and a short note) in an `operator_preferences` table of the
same SQLite file. The incident migration rebuilds only the incident tables, so
preferences survive it. Fixed rules turn them into a preferred plan among the
calculated ones, with the trade-off and any critical-order warning;
`investigate_incident` returns that as `operator_preferences`, and
`GET /incidents/{id}` returns it as `preference`. The agent has three jobs on
the same loop, run on Strands Agents (`logiops/strands_runtime.py`): investigate one incident (read tools plus
`investigate_incident`), answer a follow-up (read tools only), and brief the
queue (`list_incidents` plus read tools, no plans). Each prompt asks for a
`Spoken:` line (followed by `Recommended plan:` in an investigation), which
the server splits off into a `spoken` field for voice.

`infra/amazon/` prepares a single-instance AWS demo. CloudFront gives the
public HTTPS URL (and a second distribution the MCP Apps sandbox origin); EC2
serves the API and MCP endpoint with an IAM instance role for Bedrock, Polly
and AgentCore Memory. A separate EBS volume stores SQLite so the incidents,
preferences and audit trail survive instance restarts. Deployment uses a private S3 archive
and Systems Manager, without SSH or static AWS keys on the instance; settings
and the operator token come from SSM parameters. A Cognito user pool with a
managed-login domain provides OAuth 2.1 sign-in (PKCE) for the device, the
console and MCP clients, and an AgentCore Memory keeps conversations across
sessions. It was provisioned on 2026-10-06 and 2026-10-11; `scripts/deploy_ec2.py`
ships only `origin/main`.

The scenario, service, tools, and tests are provider-independent; the MCP,
Bedrock and preference modules are the Amazon-specific layer. The model sees only read and investigation tools; human approval uses
REST, and the backend checks the exact plan ID and source version before
execution through REST or MCP.

## Runtime architecture

```text
   /demo (Alexa+ device)        /console (operator)        MCP clients, Alexa+
          |                            |                          |
          +------------+---------------+--------------------------+
                       |  REST + MCP over Streamable HTTP (OAuth 2.1 / token)
                  FastAPI app (routes/, security, MCP server, MCP App view)
                       |
            Agent on Strands Agents (ConverseModel, McpTool, RunGuards)
                       |                          \
          +------------+------------+              AgentCore Memory, Polly
          |                         |
   Amazon Bedrock              MCP tools (in-process)
   (Claude Sonnet 4.6,              |
    prompt cache)        +----------+----------+-----------+
                         |          |          |           |
                       Orders  Inventory  Carriers    Plans / execution
                                                      (versioned, audited)
```

## AWS services and their purpose

- **Bedrock Converse:** the agent chooses MCP read tools and explains the
  calculated resolution plans, with the Agent Skill and the prompt read from the
  prompt cache after the first turn. A deterministic replay supports offline review.
- **Strands Agents:** runs the agent loop (model adapter over the same Converse
  client, one tool per allowed MCP tool, guard hooks, turn limits, optional
  OpenTelemetry).
- **AgentCore Memory:** remembers each signed-in person's turns and long-term
  facts across sessions ("Welcome back"); SQLite stands in locally.
- **Amazon Polly:** reads the spoken line aloud (Ruth, generative), cached per
  text and capped per day; the browser's voice is the fallback.
- **Amazon Cognito:** OAuth 2.1 sign-in with PKCE for the pages and MCP clients;
  the API publishes RFC 9728 and RFC 8414 metadata and proxies the token endpoint.
- **EC2:** runs FastAPI, MCP, and the browser demo in one process. The instance
  role supplies temporary Bedrock, S3, and Systems Manager permissions.
- **EBS:** stores SQLite separately from the EC2 root filesystem so the audit
  history survives instance restarts.
- **S3 and Systems Manager:** transfer a checksum-verified release and run its
  installation without SSH or long-lived credentials on the instance.
- **CloudFront:** gives judges a stable HTTPS address. The EC2 security group
  accepts origin traffic only from CloudFront's origin-facing prefix list;
  CloudFront to EC2 currently uses HTTP, with bearer authentication on every
  route except the page, its assets, the sandbox proxy, the API docs and the
  health check.

These resources are defined in `infra/amazon/` and were provisioned on 2026-10-06
and 2026-10-11.

## Production path

What stays, what changes, in the order a real desk would need it:

1. **Data.** The MCP read tools (`get_shipment`, `get_order`, `get_inventory`,
   `find_alternative_carriers`) become adapters over the TMS, OMS and WMS, and
   carrier quotes come from the carriers' APIs. The scenario registry already
   models an incident as data (a pack), so the first integration is an importer
   that writes packs from those systems; the plan calculation, the approval
   binding to plan and version, the idempotent execution and the audit trail do
   not change.
2. **Actions.** `execute_approved_plan` and `book_carrier` call the real
   booking and notification systems behind the same idempotency keys; delivery
   confirmation comes back as events (today "projected, not physically
   confirmed" is said on every screen).
3. **Identity.** Cognito stays or is replaced by the company's identity provider;
   the scopes (`incidents.operate`, `bookings.pay`) already separate reading,
   approving and paying. The operator token is for the demo only.
4. **Alexa+.** The device page simulates the Alexa+ experience; the server
   speaks MCP (tools, prompts, resources, MCP Apps, Agent Skill, URL elicitation,
   OAuth 2.1), so connecting Alexa+ is a registration step when the developer
   tools open, not a rewrite (see `docs/hackathon/alexa-plus-readiness.md`).
5. **Scale and operations.** SQLite becomes Postgres behind the same service
   layer; the one EC2 instance becomes a container service behind the same
   CloudFront distribution; `LOGIOPS_OTEL=1` ships the agent's spans to the
   company's collector; the daily budgets become per-tenant quotas.
