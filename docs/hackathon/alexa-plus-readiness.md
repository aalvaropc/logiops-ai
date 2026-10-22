# Alexa+ readiness

What Alexa+ expects from a self-hosted MCP server, what LogiOps AI already does, how
it was verified, and what is left when the Alexa+ developer tools open to the public.
The device page (`/demo`) simulates the Alexa+ experience over the same server, as the
hackathon rules allow for participants without access to those tools. The server itself
speaks the protocols Alexa+ add-ons are built on: MCP over Streamable HTTP, OAuth 2.1,
MCP Apps and an Agent Skill. I expect connecting Alexa+ to be mainly registration and
configuration rather than a rewrite, but I could not verify it: the Alexa+ developer
tools are partner-only. What I expect is left is listed below.

| Alexa+ expectation | LogiOps AI today | Verified by |
|---|---|---|
| A self-hosted MCP server over Streamable HTTP | `/mcp`, stateless, MCP 2025-11-25, official Python SDK 1.30.0; `initialize` returns server instructions with the workflow and the human-approval rule | `tests/test_mcp_contract.py`, `scripts/check_mcp.py` against the CloudFront URL |
| Tools with titles, descriptions, annotations and typed outputs | 12 tools: 8 read-only (`readOnlyHint`), 2 destructive and idempotent (`execute_approved_plan`, `book_carrier`), inputs that accept "433" or "ship 433", `outputSchema` on each | `tests/test_mcp.py`, `tests/test_mcp_contract.py` |
| Agentic orchestration: the agent chooses tools and acts within limits | The agent runs on Strands Agents with a model adapter over Bedrock Converse, one tool per allowed MCP tool, guard hooks and a turn budget; investigate, follow-up and briefing are three jobs on the same loop; every answer passes a deterministic data check and gets one revision | `tests/test_strands_runtime.py`, `tests/test_agent*.py`, live runs on 2026-10-12 |
| A human approves; the agent never does | No approval tool exists; `execute_approved_plan` is `visibility: ["model"]` and refuses a plan no person approved with MCP error `-32042` (URL elicitation) that carries the console URL; approval binds plan id and data version | `tests/test_mcp_prompts.py`, `tests/test_security.py` |
| State across sessions | AgentCore Memory keeps each signed-in person's turns and long-term facts ("Welcome back… we were on SHIP-433"); operator preferences persist and steer the pick without approving; each incident keeps its own conversation on the device | `tests/test_memory.py`, `scripts/verify_remote.py` |
| Purchasing with a read-back and no double charge | `quote_carrier_booking` reads carriers, service fee, tax and the total back; `book_carrier` charges once under an idempotency key, refuses a different amount, an expired quote or stale data (409 "Nothing was charged"), and returns a receipt (`receipt://logiops/{number}`) | `tests/test_booking.py`, `scripts/verify_remote.py` |
| Cards | The device shows one surface at a time (home with the open incidents as lanes and the queue as a list, incident with its map and time scale, the agent stage, plans, confirmation, receipt, alert, result); the plans card is an MCP App. The queue is a list rather than a carousel, so it reads on a phone without swiping | `tests/browser/test_device.py` (axe 0 at 1440 and 390 px) |
| MCP Apps | `ui://logiops/resolution-options.<sha>.html` declared on `investigate_incident`, served through a sandbox proxy on a second origin, `ui/initialize`, host context (theme, size, locale, time zone, device class), `ui/message` to select a plan, `ui/resource-teardown`; the dependency-free host bridge is `logiops/static/app/mcp-host.js` | `tests/test_mcp_app.py`, `tests/static/mcp-host.test.mjs`, browser tests |
| Agent Skills | `skills/logiops-exception-desk/SKILL.md` served as `skill://logiops-exception-desk/SKILL.md`, sent as the first system block with a cache point; runs report its name, URI and SHA-256 | `tests/test_skill.py` |
| Prompts, completions, resource templates | 2 prompts, `shipment_id` completions, `incident://{shipment_id}` and `receipt://logiops/{number}` templates | `tests/test_mcp_prompts.py` |
| OAuth 2.1 for MCP clients | 401 challenge naming the resource metadata and the scope, RFC 9728 protected-resource metadata, RFC 8414 authorization-server metadata with PKCE S256, Cognito managed login, a token endpoint proxy, scopes `incidents.operate` and `bookings.write`; guests read and ask on the replay model | `tests/test_oauth.py`, `scripts/check_oauth.py` (4/4 on the deployment) |
| Proactive notifications | A watcher raises an alert when data under an investigated plan changes; `list_alerts` over MCP, `/alerts` over REST; the device shows it as a card and speaks "Heads up on SHIP-421…" | `tests/test_alerts.py`, browser test "an alert elsewhere opens as a card" |
| Short spoken replies | Every answer ends in a `Spoken:` line the server splits off; Amazon Polly (Ruth, generative) reads it on the deployment, cached per text | `tests/test_voice.py`, `tests/test_presentation.py` |
| Bring your own data | Incidents are a scenario pack; `POST /scenario/packs` and `LOGIOPS_SCENARIO_PACK` register more, and they run through the same tools, agent and pages | `tests/test_scenario_packs.py`, `tests/test_scenario_registry.py` |

## What the device simulates

Alexa+ would provide the wake word, speech recognition, the voice, the screen and the
account. The device page stands in for those with the browser's speech recognition,
Amazon Polly, an Echo Show-style frame and Cognito sign-in. Everything under it — the
conversation, the cards, the approvals, the purchases, the memory — goes through the
same REST and MCP endpoints an Alexa+ integration would use.

## What is left when the developer tools open

1. Register the server with the Alexa+ MCP toolkit and point its OAuth client at the
   same Cognito user pool (the discovery documents already name the resource and the
   scopes).
2. Map the two prompts and the spoken lines to Alexa+'s response format; the
   `Spoken:` line is already the short form.
3. Replace the browser's speech recognition and Polly with Alexa+'s own, and the
   device frame with the real screen; the MCP App card already follows the host
   context (theme, size, device class, safe areas).
4. Keep the operator console as the desk-side view.
