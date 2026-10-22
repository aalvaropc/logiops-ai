# Friction log — Amazon / AWS

Real friction only, logged as it happened. Each entry gives the
technology, the task attempted, the steps taken, what I expected, what
actually happened, the severity, the workaround and a suggestion.

**Severity scale:** Blocker (stopped work, no workaround) · High (blocked a
feature until a workaround) · Medium (cost time, workaround easy) · Low
(annoyance).

## 2026-10-02 — Bedrock model access UX

- **Technology:** Amazon Bedrock console.
- **Task attempted:** enable access to a Claude model to test it in the
  Playground.
- **Steps taken:**
  1. Opened the Bedrock Model catalog.
  2. Searched for Anthropic.
  3. Opened Claude Sonnet 5.5 and requested access.
- **Expected:** either immediate access or a clear use-case form.
- **Actual:** `AccessDeniedException: anthropic.claude-sonnet-5-5 is not
  available for this account`, pointing to AWS Sales with no self-service
  option. Claude Sonnet 4.6 showed the expected use-case form and granted
  access right after I submitted it. Nothing said *why* one model self-serves
  and the newer one does not.
- **Severity:** Low — another model worked at once, but the difference was
  confusing.
- **Workaround:** used Claude Sonnet 4.6.
- **Suggestion:** say in the error why a model needs AWS Sales, and list which
  models self-serve.

## 2026-10-02 — Billing console region selector

- **Technology:** AWS Billing and Budgets console.
- **Task attempted:** switch to `us-east-1` before setting up Bedrock.
- **Steps taken:**
  1. Opened the region selector from the Billing console.
  2. Tried to pick `us-east-1`.
- **Expected:** to switch region normally.
- **Actual:** every region showed a lock icon and the note "There are 17
  Regions that are not enabled for this account". Billing is a global service
  and does not support region switching at all, which is not obvious to
  someone new to AWS.
- **Severity:** Low — a few minutes of confusion.
- **Workaround:** opened a regional service (Bedrock) first and used its own
  region selector.
- **Suggestion:** on global services, explain why the selector is locked
  instead of showing lock icons.

## 2026-10-02 — AWS Budgets email verification

- **Technology:** AWS Budgets.
- **Task attempted:** get e-mail alerts before any spend: two cost budgets of
  US$50 and US$100, plus a zero-spend alert.
- **Steps taken:**
  1. Opened AWS Budgets in the console.
  2. Created the budgets, each with an e-mail notification to the account's
     address.
  3. Saved them.
- **Expected:** the alerts to be active once the budgets were saved, or the
  creation flow to ask for verification before finishing.
- **Actual:** notifications are only sent after the recipient address is
  verified through a link, and that requirement appears as a banner that is
  easy to miss.
- **Severity:** Low.
- **Workaround:** found the verification e-mail (inbox and spam) and clicked
  the link; the zero-spend alert then fired within hours of the first Bedrock
  calls.
- **Suggestion:** block alert creation until the address is verified, instead
  of a dismissible banner.

## 2026-10-03 — Alexa+ developer tools are partner-only

- **Technology:** Alexa+ Add-on developer tools (Category SDK, MCP Toolkit, CLI,
  Web Simulator).
- **Task attempted:** register my self-hosted MCP server with Alexa+ and test
  the real conversation in the Web Simulator.
- **Steps taken:**
  1. Read the Alexa+ add-on documentation and its setup pages to plan the
     integration.
  2. Found on the add-on docs home page that the tools are in preview for
     select partners only; the individual setup pages did not say so.
  3. Checked the hackathon FAQ, which confirmed there is no way for
     participants to apply for or gain access.
- **Expected:** a way to request access, or at least the same "partner-only"
  notice on every setup page.
- **Actual:** no access for hackathon participants. The FAQ says: "there is
  currently no way for hackathon participants to apply for or gain access".
- **Severity:** High — the real Alexa+ integration was not possible; I built
  around it.
- **Workaround:** a real self-hosted MCP server (Streamable HTTP, OAuth 2.1, MCP
  Apps, Agent Skill) driven by my own simulated Alexa+ device, as the FAQ
  recommends (decision D2). `alexa-plus-readiness.md` lists what is left once
  the tools open.
- **Suggestion:** state "partner-only" on every setup page, and publish a
  public simulator, even a limited one, so builders can test the real Alexa+
  conversation.

## 2026-10-05 — CloudFront drops Authorization on GET with CachingDisabled

- **Technology:** Amazon CloudFront cache and origin request policies.
- **Task attempted:** put a bearer-token API behind CloudFront without
  caching it.
- **Steps taken:**
  1. Wrote the first distribution in `infra/amazon/main.tf` with the managed
     `CachingDisabled` cache policy and the `AllViewer` origin request policy.
  2. Before the first `terraform apply`, reviewed which viewer headers would
     reach the origin.
  3. Checked whether `Authorization` could be added to an origin request
     policy, and whether `CachingDisabled` could include it in the cache key.
- **Expected:** the managed `CachingDisabled` + `AllViewer` policies to forward
  every viewer header, including `Authorization`.
- **Actual:** `Authorization` cannot be added to an origin request policy, and
  `CachingDisabled` cannot include headers in the cache key, so GET requests
  would have reached the origin without the token and answered 401. POST
  requests are unaffected, which makes the failure easy to miss in a quick
  test. I caught it in this review, so the deployed demo never dropped a
  token.
- **Severity:** High — every authenticated read would have failed.
- **Workaround:** a custom cache policy that adds `Authorization` to the cache
  key with `max_ttl = 1`, plus `Cache-Control: no-store` from the app. The
  first deployment, on 2026-10-06, already used it.
- **Suggestion:** document this combination on the `CachingDisabled` policy
  page, or offer a managed "forward Authorization, never cache" policy.

## 2026-10-05 — CloudFront origin timeout above the default quota

- **Technology:** Amazon CloudFront, Service Quotas.
- **Task attempted:** let slow model answers through CloudFront.
- **Steps taken:**
  1. Set `origin_read_timeout = 120` on the CloudFront origin in
     `infra/amazon/main.tf`.
  2. Ran `terraform plan`, which accepted the value.
  3. Found that applying it would need a CloudFront quota increase first.
- **Expected:** `plan` to reject a value above the account's quota, or the
  quota to be shown next to the setting.
- **Actual:** an origin read timeout above 60 s is accepted by `terraform
  plan` but needs a quota increase before `apply` succeeds.
- **Severity:** Medium — it only shows up at apply time.
- **Workaround:** kept the default 60 s and stop every agent run after 50 s,
  so an answer always arrives before CloudFront gives up.
- **Suggestion:** surface the quota limit in plan-time validation.

## 2026-10-05 — `aws login` session expired between work sessions

- **Technology:** AWS CLI `aws login`.
- **Task attempted:** resume deployment work after the sign-in of an earlier
  session.
- **Steps taken:**
  1. Signed in with `aws login --region us-east-1` and worked through the day.
  2. Resumed the next day and ran AWS commands again.
  3. The same happened later: on 2026-10-13 Cost Explorer could not be
     queried; on 2026-10-19 `scripts/deploy_ec2.py` failed while uploading the
     release to S3 (nothing was deployed); on 2026-10-20
     `aws sts get-caller-identity` reported the expired session before a
     redeploy.
- **Expected:** a session that lasts through a working day, or credentials
  that refresh on their own as the instance role's do.
- **Actual:** every call failed with "Your session has expired. Please
  reauthenticate using 'aws login'." Signing in again needs a browser, so it
  cannot be done from a headless agent session.
- **Severity:** Medium — it stopped deployment work four times, once halfway
  through a deploy, until a person signed in again.
- **Workaround:** run `aws login` interactively before any deployment work.
  The deploy that failed at the upload had deployed nothing, so it was simply
  run again.
- **Suggestion:** print when the session expires at sign-in, warn before it
  does, and offer a sign-in that can be completed from another device for
  headless terminals.

## 2026-10-06 — boto3 cannot use an `aws login` session without the CRT extra

- **Technology:** boto3 / botocore with the AWS CLI `aws login` credentials.
- **Task attempted:** call Bedrock Converse from Python with the same session
  the CLI uses.
- **Steps taken:**
  1. Signed in with `aws login --region us-east-1`; the CLI worked in the same
     shell.
  2. Started the API locally in Bedrock mode and posted an investigation.
  3. Every live run failed with my generic "Bedrock Converse failed".
  4. Added the SDK error's class name to that message, which showed the real
     cause.
- **Expected:** boto3 finds the CLI login session like any other credentials.
- **Actual:** `MissingDependencyException: Using the login credential provider
  requires an additional dependency ... pip install "botocore[crt]"`. Because
  the CLI worked in the same shell, it looked like a credentials problem.
- **Severity:** Medium — local live runs failed until the extra was
  installed.
- **Workaround:** depend on `boto3[crt]`. After that, a full investigation
  through the MCP loop returned in 15.8 s.
- **Suggestion:** ship the login credential provider without an optional
  extra, or mention it in the `aws login` documentation.

## 2026-10-07 — Promotional credits and Marketplace-billed models

- **Technology:** AWS promotional credits, AWS Billing (Credits page, Cost
  Explorer), AWS Marketplace billing for Claude on Bedrock.
- **Task attempted:** confirm that the hackathon credits cover the Bedrock
  model, the main runtime cost.
- **Steps taken:**
  1. Submitted the credits form on 2026-10-02; the Marketplace subscription
     e-mail for Claude on Bedrock arrived the same day.
  2. Received US$150 of credits on 2026-10-06; the form gave no processing
     time.
  3. On 2026-10-07 opened the Credits page, then Cost Explorer.
- **Expected:** the credits to apply to the Bedrock model usage, or the form to
  say which services they cover.
- **Actual:** the Credits page still showed US$0.00 used. Cost Explorer later
  that day showed the credits applied to EC2, VPC, S3 and Cost Explorer usage
  (US$0.28), and none to the Claude Sonnet 4.6 usage billed through AWS
  Marketplace (US$0.63).
- **Severity:** Medium — the model's cost falls outside the credits, and
  nothing said so in advance.
- **Workaround:** a daily cap on live model calls (40 a day on the deployed
  demo) with a scripted replay after it, plus the budget alerts.
- **Suggestion:** state on the credits form whether Marketplace-billed models
  are covered and how long processing takes, and update the Credits page
  within hours.

## 2026-10-11 — Cognito discovery does not advertise PKCE

- **Technology:** Amazon Cognito user pools (OAuth 2.0 endpoints).
- **Task attempted:** let MCP clients (and the Alexa+-style demo) find how to
  sign in, as the MCP authorization spec and Alexa+ account linking expect.
- **Steps taken:** read
  `https://cognito-idp.us-east-1.amazonaws.com/<pool>/.well-known/openid-configuration`.
- **Expected:** `code_challenge_methods_supported: ["S256"]`, since Cognito
  supports PKCE for public clients, and an RFC 8414 document.
- **Actual:** the OIDC discovery document omits the PKCE methods, and there is
  no `/.well-known/oauth-authorization-server`. Spec-following MCP clients
  refuse to start an authorization-code flow without S256 in the metadata.
- **Severity:** High — standard MCP clients could not sign in until I served
  my own metadata.
- **Workaround:** LogiOps serves its own RFC 8414 document with S256, Cognito's
  authorize endpoint, and a token endpoint that forwards only PKCE and refresh
  grants of allowed public clients.
- **Suggestion:** publish `code_challenge_methods_supported` and an RFC 8414
  document for user pools.

## 2026-10-11 — Cognito access tokens have no audience

- **Technology:** Amazon Cognito access tokens with a resource server.
- **Task attempted:** bind tokens to the MCP resource (`https://<host>/mcp`),
  per RFC 8707 and the MCP authorization spec.
- **Steps taken:**
  1. Defined the resource server `https://<cloudfront>/mcp` with the scopes
     `incidents.operate` and `bookings.write` in `infra/amazon/identity.tf`.
  2. Wrote the access-token checks in `logiops/oauth.py` and looked for a
     claim, or a `resource` parameter, that binds a token to that resource
     server.
- **Expected:** an `aud` claim naming the resource server, or support for the
  `resource` parameter.
- **Actual:** access tokens carry `client_id` and scopes prefixed with the
  resource server identifier, but no `aud`.
- **Severity:** Low — the scopes still bind the token.
- **Workaround:** check the issuer, `token_use`, an allowlist of client ids,
  and the resource-prefixed scopes.
- **Suggestion:** support RFC 8707 resource indicators (an `aud` per resource
  server).

## 2026-10-11 — AgentCore Memory: `namespaces` deprecated, found only in the schema

- **Technology:** Terraform AWS provider 6.67, `aws_bedrockagentcore_memory_strategy`.
- **Task attempted:** define USER_PREFERENCE and SEMANTIC strategies with
  per-actor namespaces.
- **Steps taken:**
  1. Started from the resource's documentation example, which uses
     `namespaces`.
  2. Looked for attribute descriptions on the resource page; there are none.
  3. Ran `terraform providers schema -json` and found `namespaces` marked as
     deprecated.
  4. Switched to `namespace_templates`; `terraform validate` passed.
- **Expected:** the documentation example to use the current attribute.
- **Actual:** `namespaces` is deprecated in favor of `namespace_templates`.
  That showed up only in `terraform providers schema -json`; the resource has
  no attribute descriptions to explain it.
- **Severity:** Low.
- **Workaround:** used `namespace_templates = ["/users/{actorId}/…"]`.
- **Suggestion:** add attribute descriptions and a deprecation note to the
  resource docs.

## 2026-10-11 — AgentCore Memory: listing events needs a session id

- **Technology:** Amazon Bedrock AgentCore Memory data plane (`ListEvents`).
- **Task attempted:** recall what a person said in their *previous* session to
  greet them with "Welcome back".
- **Steps taken:**
  1. Wrote the recall in `logiops/memory.py` to read an actor's latest events
     with `ListEvents`.
  2. Found that `ListEvents` requires `sessionId`.
  3. Rewrote it as `ListSessions`, then `ListEvents` on the chosen session.
  4. Tested it with botocore's Stubber, which rejected my short
     `memoryRecordId` values.
- **Expected:** to list an actor's latest events across sessions.
- **Actual:** `ListEvents` requires `sessionId`. Finding the previous session
  takes `ListSessions`, sorting by `createdAt`, and then a second call. When
  testing with botocore's Stubber, `memoryRecordId` also needs at least 40
  characters, which the docs examples do not show.
- **Severity:** Low.
- **Workaround:** `ListSessions` → newest session other than the current one →
  `ListEvents`.
- **Suggestion:** allow `ListEvents` by actor with a time filter, or a "latest
  sessions with their last events" call.

## 2026-10-12 — Strands Agents: `MCPClient` deadlocks with an in-process MCP server

- **Technology:** `strands-agents` 1.59/1.60, `strands.tools.mcp.MCPClient`.
- **Task attempted:** run the agent loop on Strands over the project's MCP
  server, which the API talks to in-process through an ASGI transport (no
  network hop).
- **Steps taken:**
  1. Built an `MCPClient` on a `streamable_http_client` bound to the ASGI app.
  2. Listed its tools from the request's event loop.
- **Expected:** the client to use the running loop, as the official MCP
  `ClientSession` does.
- **Actual:** `MCPClient` starts its own thread and event loop and blocks the
  calling thread while the server coroutine needs that same loop; the request
  never returns.
- **Severity:** High — the SDK's own MCP integration could not be used with an
  in-process server.
- **Workaround:** one `AgentTool` subclass per allowed tool that calls
  `session.call_tool` on the session already open in the request's loop
  (`logiops/strands_runtime.py`).
- **Suggestion:** an `MCPClient` mode that accepts an existing `ClientSession`
  or runs on the caller's loop.

## 2026-10-12 — botocore: `NoRegionError` while refreshing `aws login` credentials

- **Technology:** boto3 / botocore with an `aws login` session.
- **Task attempted:** call Bedrock locally from the API with
  `boto3.client("bedrock-runtime", region_name="us-east-1")`.
- **Steps taken:**
  1. Signed in with `aws login --region us-east-1`.
  2. Exported `AWS_REGION=us-east-1` (but not `AWS_DEFAULT_REGION`) and
     started the API in Bedrock mode.
  3. Posted an investigation once the login credentials needed a refresh.
- **Expected:** the explicit `region_name` to be enough.
- **Actual:** the login credential provider refreshes its credentials through a
  client of its own that reads the default region, and raises `NoRegionError:
  You must specify a region` even though the Bedrock client has one.
- **Severity:** Low — once understood; the error names the wrong client.
- **Workaround:** export `AWS_DEFAULT_REGION=us-east-1` as well (or configure
  the profile's region).
- **Suggestion:** resolve the refresh client's region from the calling
  client's `region_name`, or name the credential provider in the error.
