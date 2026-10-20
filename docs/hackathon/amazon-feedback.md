# Product Feedback — Amazon / AWS

Required by the Amazon submission (rules 3.16). Entries are added as the project is
built; see also `amazon-friction-log.md` for discrete problems. Numbers marked
*measured* come from a run on 2026-10-06; anything else is an observation.

## Amazon Bedrock — Converse API with tool use

- **Used for:** the agent's multi-turn tool loop over our MCP tools (`global.anthropic.claude-sonnet-4-6`, `us-east-1`).
- **Documentation:** the "Model access" page that older guides describe no longer exists; access is a use-case form shown the first time a model is opened in the Playground. The guides should say so.
- **Testing:** `botocore`'s service model let us validate request shapes without a paid call (Stubber), which was the cheapest useful test.
- **Performance and latency (measured):** one investigation of five MCP tool calls and three priced plans took 15.8 s end to end, with 5,529 input and 1,192 output tokens.
- **Reliability:** none of the calls we made failed. We rely on boto3's adaptive retries and enforce our own 50 s deadline so a request always answers inside CloudFront's 60 s origin timeout.
- **Limits and workarounds:** our first client shelled out to the AWS CLI and put the whole conversation in `argv`, which fails past 128 KiB and hid the real error; we moved to boto3.
- **Access:** Claude Sonnet 5.5 returned `AccessDeniedException` pointing to AWS Sales, with no reason and no self-service path, while Sonnet 4.6 worked after the same form.
- **Would build with it again:** yes. The Converse API was the most predictable part of the stack.

## AWS Marketplace billing for Claude on Bedrock

- Claude on Bedrock is billed as an AWS Marketplace subscription sold by a third party (we received the subscription e-mail on 2026-10-02). That is easy to miss and matters for builders who rely on promotional credits: whether they cover a Marketplace-billed model is not stated anywhere we could find. The Bedrock console could say so before the first call.
- **Measured:** the real test runs cost US$0.04 in total, enough to trip a zero-spend budget alert.

## boto3 with `aws login`

- The login credential provider needs `botocore[crt]`. Without it every call fails with `MissingDependencyException`, even though the CLI works in the same shell. It should work out of the box, or the `aws login` documentation should mention the extra.

## Model Context Protocol — official Python SDK, Streamable HTTP

- **Used for:** the self-hosted MCP server and the agent's MCP client.
- **Worked well:** protocol negotiation (2025-11-25) and structured tool results worked between the official client and server with no glue code; the built-in DNS-rebinding protection is a good default.
- **Needs work:** guidance for self-hosted servers that are not OAuth providers (a bearer token behind a CDN) is thin.

## MCP Apps (extension 2026-01-26)

- **Used for:** an interactive plan-comparison card declared on `investigate_incident`.
- **Worked well:** the handshake is small and plain `postMessage` is enough. A view that only sends `ui/message` makes a clean human-in-the-loop boundary.
- **Needs work:**
  - Web hosts must load views through a sandbox proxy on a different origin. We implemented it, but for one domain it means a second hostname (a second CDN distribution here). A reference proxy page in the SDK, and guidance for local development (we pair `127.0.0.1` with `localhost`), would save every host author the same work.
  - Tool `visibility` defaults to `["model", "app"]`, so a state-changing tool is callable from views unless you opt out. That default is easy to miss.

## Strands Agents (1.60)

- **Used for:** the agent's tool loop since 2026-10-12, replacing a hand-written Converse loop with the same contract (`logiops/strands_runtime.py`).
- **Worked well:** the `Model` interface is small enough to adapt our non-streaming Converse client (Bedrock, the daily-budget wrapper, the replay and every test fake) in one class; `AgentTool` lets a tool run on an MCP session we own; hooks (`AfterModelCallEvent`, `AfterToolCallEvent`) hold the same guards as before, enforced before any tool runs; `limits={"turns": n}` and `NullConversationManager` make the loop as predictable as the old one; system prompt content blocks carry the Agent Skill and a cache point.
- **Measured:** on the deployment, an investigation of five tool calls and three plans answered in 13.6 s with 5,872 tokens (the earlier hand-written loop measured 15.8 s on 2026-10-06 and 14.1 s on 2026-10-12); the SHIP-421 run read 5,818 prompt-cache tokens and wrote 2,909; locally 18.5 s with 11,636 cache-read tokens. The runtime added no measurable latency over the previous loop.
- **Needs work:** the SDK's `MCPClient` runs its own thread and event loop and deadlocks with an in-process stateless Streamable HTTP server (friction 2026-10-12); the order of `AfterModelCallEvent` and the max-tokens recovery, and how turn limits count cycles, we learned from the source; a production install pulls OpenTelemetry and watchdog even when tracing is off.
- **Would build with it again:** yes, with the adapter pattern; it took one day to land with every test green.

## Amazon Polly

- **Used for:** reading the spoken line of every reply on the deployment (Ruth, generative engine), cached per text in SQLite and capped per day (`LOGIOPS_DAILY_SPEECH_CHARS`).
- **Measured:** one spoken line of about 25 words is an 11 KB MP3 in under a second; repeated lines cost nothing.
- **Worked well:** the generative voice reads numbers, times and ids ("L G O …") naturally; the browser's voice is a transparent fallback when the budget is spent.
- **Needs work:** nothing blocked us; a per-text cache hint would remove the store we keep (feature request P3).

## Amazon Cognito (managed login, OAuth 2.1 with PKCE)

- **Used for:** sign-in on the device, the console and MCP clients; scopes `incidents.operate` and `bookings.write` on a resource server; the API proxies the token endpoint and publishes RFC 9728 and RFC 8414 metadata itself.
- **Worked well:** the managed-login domain and the public PKCE client took one Terraform apply; `check_oauth.py` passes 4/4 against the deployment and a real sign-in was tested on 2026-10-12.
- **Needs work:** the OIDC discovery document does not advertise PKCE and access tokens carry no `aud` (friction 2026-10-11), so an MCP client cannot trust Cognito's own metadata.

## Amazon Bedrock AgentCore Memory

- **Used for:** per-user memory across sessions (USER_PREFERENCE and SEMANTIC strategies), the "Welcome back" line and "forget me".
- **Measured:** on the deployment, `verify_remote.py` recalls the previous session's turn and forgets one item in under two seconds each.
- **Needs work:** listing a person's latest events needs a session id (friction 2026-10-11); the Terraform resource's attribute descriptions are missing (friction 2026-10-11).

## Terraform on AWS (phase 2)

- Thirteen more resources (AgentCore Memory with two strategies, Cognito user pool, domain, resource server and client, SSM parameters, IAM for Polly and Memory) applied cleanly on 2026-10-11 after a plan review; the instance reads settings from SSM at deploy time, so rotating the operator token is one script and one deploy.

## Alexa+ developer tools

- We wanted to build directly on the Category SDK, MCP Toolkit, CLI and Web Simulator, but they are partner-only and there is no way to request access. Individual setup pages do not always say so, which costs time. A public simulator, even a limited one, would let builders test the real Alexa+ conversation instead of building their own.

## Amazon CloudFront

- With the managed `CachingDisabled` policy, `Authorization` is dropped on GET requests while POST works, which is easy to miss in a quick test. A managed "forward Authorization, never cache" policy would remove a footgun for every token-protected API.
- Origin timeouts above 60 s pass `terraform plan` and only fail at apply because of a quota.

## AWS Budgets and Billing

- Two budgets with e-mail alerts took minutes to set up and worked: the zero-spend alert fired within hours of the first Bedrock calls.
- Alert e-mails require verification through an easy-to-miss banner, and the region selector is locked on global consoles without explanation.

## Terraform on AWS

- Twenty-two resources (EC2, EBS, S3, IAM, CloudFront ×2) plan cleanly. The provider lock file and `validate` made reviews quick. Surprises were all service-side limits (the origin timeout quota above), not syntax.

## AWS promotional credits

- We submitted the credits form on 2026-10-02, and US$150 of credits arrived on 2026-10-06, four days later, with no processing time stated anywhere. Stating the expected processing time and the covered services on the form would help builders plan.
- **Measured:** on 2026-10-07 the Credits page still showed $0.00 used. Later that day Cost Explorer showed the credits applied to October's EC2, VPC, S3 and Cost Explorer usage (US$0.28), and none to the Claude Sonnet 4.6 usage billed through AWS Marketplace (US$0.63). If Marketplace-billed models are excluded, the form should say so: for a Bedrock hackathon, the model is the main runtime cost.
- Both views update a day or more behind, so a builder cannot see during a hackathon whether a given charge will be covered.
