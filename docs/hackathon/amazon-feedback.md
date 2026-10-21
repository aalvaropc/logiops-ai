# Product Feedback — Amazon, AWS and the Alexa+ track tools

The submission asks, for every tool, API or SDK used: what we used it for, what
worked well, what needs work, how onboarding went (zero to hello world), and
whether we would build with it again. Each section below answers those five.
Measured figures carry their date and come from the deployed demo unless they
say "local". Discrete problems are in `amazon-friction-log.md`; the requests
that follow from them, with priorities, are in `feature-requests.md`.

## AWS services used (AWS Builder Mini Challenge)

- **Amazon Bedrock** is the runtime: Claude Sonnet 4.6 through the global
  inference profile `global.anthropic.claude-sonnet-4-6` in `us-east-1`, called
  with the Converse API. Every investigation is a multi-turn tool-use loop over
  our MCP tools, with the Agent Skill and the prompt cached; follow-ups and the
  queue briefing are shorter loops with read-only tools.
- **Strands Agents** runs that loop, with a `Model` adapter over our Converse
  client and one tool per allowed MCP tool.
- **Amazon Bedrock AgentCore Memory** keeps each signed-in person's turns and
  long-term facts across sessions ("Welcome back", "forget me").
- **Amazon Polly** speaks the short line of each answer (Ruth, generative).
- **Amazon Cognito** is the OAuth 2.1 authorization server for the device, the
  console and MCP clients (PKCE, two resource scopes).
- **Amazon EC2 and EBS** run the API and MCP server, with SQLite on an
  encrypted data volume; **Amazon CloudFront** gives HTTPS and, with a second
  distribution, the MCP Apps sandbox origin; **Amazon S3** holds private
  releases; **AWS Systems Manager** installs them with no SSH and stores the
  token and settings; **AWS IAM** scopes the instance role to exactly these.
- **AWS Budgets** and the Billing console watch the spend, and a budget action
  cuts Bedrock and Polly at the account level if a month's actual cost passes
  US$60.
- **Amazon Route 53** checks the demo through CloudFront every 30 seconds, and
  an **Amazon CloudWatch** alarm e-mails through **Amazon SNS** when it is down
  and again when it is back.
- Everything is defined in Terraform (`infra/amazon/`).

## Amazon Bedrock — Converse API with tool use

- **Used for:** the agent's tool loop described above. Each run's token usage
  is recorded in the audit trail and reported by `GET /metrics`.
- **Worked well:**
  - `toolUse` and `toolResult` blocks map one to one onto MCP tool calls and
    structured results; tool calling worked on the first real request.
  - Prompt caching: with the Agent Skill and the prompt before a cache point,
    one run read 11,596 tokens from the cache (2026-10-12).
  - Testing: botocore's Stubber validated our request shapes without a paid
    call, which was the cheapest useful test.
  - Performance: 15.8 s for an investigation of five tool calls and three
    plans with 5,529 input and 1,192 output tokens (2026-10-06, our first
    hand-written loop); 12.2 s with 5 MCP calls and 5,941 tokens, about
    US$0.04 for that run (2026-10-19); answered in 11.2 s (2026-10-21).
  - Reliability: we saw no failed Converse call in our runs. We still enforce
    a 50 s deadline (CloudFront cuts at 60 s), and since 2026-10-21 an outage
    answers from our scripted replay instead of failing.
- **Needs work:**
  - Model access: the "Model access" page older guides describe no longer
    exists; access is a use-case form shown the first time a model is opened
    in the Playground. The guides should say so.
  - Claude Sonnet 5.5 returned `AccessDeniedException` pointing to AWS Sales,
    with no reason and no self-service path, while Sonnet 4.6 worked after the
    same form.
- **Onboarding:** on 2026-10-02 we filled the use-case form for Claude Sonnet
  4.6 and the first Converse call returned `stopReason: tool_use` (637 tokens)
  the same day. Our first client shelled out to the AWS CLI with the whole
  conversation in `argv`, which fails past 128 KiB and hid the real error; on
  2026-10-05 we moved to boto3.
- **Would build with it again:** yes. The Converse API was the most predictable
  part of the stack, and one interface served the live model, our daily-budget
  wrapper, the replay and every test fake.

## AWS promotional credits and Marketplace billing for Claude

- **Used for:** paying for the demo: US$150 of credits, requested on 2026-10-02
  and received on 2026-10-06.
- **Worked well:** the credits applied to October's EC2, VPC, S3 and Cost
  Explorer usage (US$0.28 by 2026-10-07).
- **Needs work:**
  - Claude on Bedrock is billed as an AWS Marketplace subscription sold by a
    third party. By 2026-10-07 the Claude usage (US$0.63) had no credits
    applied. Nothing we found says whether Marketplace-billed models are
    covered; for a Bedrock hackathon the model is the main runtime cost.
  - The form gives no processing time, and the Credits page and Cost Explorer
    lag a day or more, so a builder cannot see during the hackathon whether a
    charge will be covered.
- **Onboarding:** one form; the credits arrived four days later.
- **Would use them again:** yes, knowing the Marketplace caveat up front.

## Strands Agents

- **Used for:** the agent's tool loop since 2026-10-12 (version 1.60),
  replacing a hand-written Converse loop with the same contract
  (`logiops/strands_runtime.py`).
- **Worked well:**
  - The `Model` interface is small enough to adapt our non-streaming Converse
    client (Bedrock, the daily-budget wrapper, the replay and every test fake)
    in one class.
  - `AgentTool` lets a tool run on an MCP session we own.
  - Hooks (`AfterModelCallEvent`, `AfterToolCallEvent`) hold our guards, which
    run before any tool executes; `limits={"turns": n}` and
    `NullConversationManager` keep the loop predictable.
  - System prompt content blocks carry the Agent Skill and a cache point.
  - Performance: 13.6 s with 5,872 tokens on the deployment and 18.5 s locally
    with 11,636 cache-read tokens (2026-10-12), against 15.8 s and 14.1 s for
    the earlier hand-written loop. The runtime added no measurable latency.
- **Needs work:**
  - `MCPClient` runs its own thread and event loop and deadlocks with an
    in-process stateless Streamable HTTP server (friction 2026-10-12); we wrote
    one `AgentTool` per MCP tool instead.
  - The order of `AfterModelCallEvent` and the max-tokens recovery, and how
    turn limits count cycles, we learned from the source.
  - A production install pulls OpenTelemetry and watchdog even when tracing
    is off.
- **Onboarding:** it landed in one day: first unwired with its own tests, then
  swapped in as a one-file change with every existing test green.
- **Would build with it again:** yes, with the adapter pattern.

## Amazon Bedrock AgentCore Memory

- **Used for:** memory across sessions for signed-in people: every turn is an
  event under the person's actor (a SHA-256 of their token subject), with
  USER_PREFERENCE and SEMANTIC strategies extracting preferences and facts. It
  drives the "Welcome back" line, "pick up where we left off" and "forget me".
- **Worked well:** `scripts/verify_remote.py` recalls the previous session's
  turn and forgets one item in under two seconds each on the deployment. The
  extracted facts need no store of our own.
- **Needs work:**
  - Listing a person's latest events needs a session id: "Welcome back" takes
    `ListSessions`, sorting, and then `ListEvents` (friction 2026-10-11).
  - With botocore's Stubber, `memoryRecordId` needs at least 40 characters,
    which the docs examples do not show.
  - The Terraform resource has no attribute descriptions; `namespaces` versus
    `namespace_templates` showed up only in the provider schema.
- **Onboarding:** the memory and its two strategies came in one Terraform apply
  on 2026-10-11; the first live recall ran on 2026-10-12.
- **Would build with it again:** yes. It gave us cross-session memory without
  running a database for it.

## Amazon Polly

- **Used for:** reading the spoken line of every reply on the deployment (Ruth,
  generative engine), cached per text in SQLite and capped per day
  (`LOGIOPS_DAILY_SPEECH_CHARS`, 10,000 characters on AWS since 2026-10-21).
- **Worked well:**
  - One spoken line of about 25 words is an 11 KB MP3 in under a second, and
    repeated lines cost nothing.
  - The generative voice reads numbers, times and spelled-out ids ("L G O …")
    naturally.
  - The browser's voice is a transparent fallback when the budget is spent or
    Polly fails.
- **Needs work:** nothing blocked us. A per-text cache hint or ETag would
  remove the store we keep to stay under the daily cap.
- **Onboarding:** one IAM permission (`polly:SynthesizeSpeech`) and one boto3
  call; the first audio on the deployment came on 2026-10-12.
- **Would build with it again:** yes.

## Amazon Cognito

- **Used for:** sign-in on the device, the console and MCP clients: a user pool
  with the managed login (v2) domain, a resource server for `https://<host>/mcp`
  with the scopes `incidents.operate` and `bookings.write`, and a public PKCE
  client. The API publishes RFC 9728 and RFC 8414 metadata and proxies the token
  endpoint.
- **Worked well:** the pool, domain, resource server and client took one
  Terraform apply; a real sign-in was tested on 2026-10-12, and
  `scripts/check_oauth.py` passes 4/4 against the deployment after every deploy.
- **Needs work:**
  - The OIDC discovery document does not advertise
    `code_challenge_methods_supported`, and there is no
    `/.well-known/oauth-authorization-server`, so spec-following MCP clients
    refuse to start (friction 2026-10-11). We serve our own RFC 8414 document.
  - Access tokens carry no `aud` and RFC 8707 resource indicators are not
    supported; we check the issuer, `token_use`, the client and the
    resource-prefixed scopes instead.
  - There is no dynamic client registration, so each MCP client needs the
    client id entered by hand (we publish it at `GET /auth/config`).
- **Onboarding:** the Terraform resources plus a script that creates the demo
  user; the discovery facade and token proxy took one pull request.
- **Would build with it again:** yes for managed sign-in. For MCP clients we
  would keep the facade until discovery and audiences follow the specs.

## Amazon EC2 and Amazon EBS

- **Used for:** the API and MCP server on a `t3.small`, with SQLite on a
  separate encrypted EBS volume (`prevent_destroy`). The security group accepts
  the app port only from CloudFront's origin-facing prefix list, and the
  instance uses its role's temporary credentials, so no AWS key is on disk.
- **Worked well:** the state survived an EC2 reboot (2026-10-06) and an
  instance replacement (2026-10-12) with the data volume intact.
- **Needs work:** nothing blocked us. The always-on cost (about US$21 a month
  idle, including the public IPv4 address and EBS) needs planning when a demo
  must stay up through a month of judging.
- **Onboarding:** part of the first Terraform apply; the first deploy answered
  on the CloudFront URL on 2026-10-06.
- **Would build with it again:** yes for a demo of this size.

## Amazon CloudFront

- **Used for:** HTTPS for the demo, the API and `/mcp`, with a custom cache
  policy that forwards `Authorization` and never caches, and a 60 s origin
  timeout; a second distribution on the same origin is the MCP Apps sandbox
  origin, where only `/mcp-app/sandbox.html` answers.
- **Worked well:** two distributions on one origin gave us the second origin
  MCP Apps requires without a second server; `CloudFront-Viewer-Address` lets
  the app apply per-viewer limits.
- **Needs work:**
  - With the managed `CachingDisabled` policy, `Authorization` is dropped on GET
    while POST works, which is easy to miss in a quick test (friction
    2026-10-05). A managed "forward Authorization, never cache" policy would
    remove a footgun for every token-protected API.
  - Origin timeouts above 60 s pass `terraform plan` and only fail at apply
    because of a quota.
- **Onboarding:** both issues came up in configuration review and at the first
  apply on 2026-10-05; after that the distributions needed no changes.
- **Would build with it again:** yes.

## Amazon S3

- **Used for:** a private, versioned bucket for release archives. The deploy
  uploads a deterministic archive, and the instance role can read only its
  release prefix.
- **Worked well:** versioning keeps every uploaded release, and nothing in the
  bucket is public.
- **Needs work:** nothing we hit.
- **Onboarding:** part of the first Terraform apply.
- **Would build with it again:** yes.

## AWS Systems Manager — Run Command and Parameter Store

- **Used for:**
  - Deploys with Run Command: no SSH and no GitHub credentials on the instance.
    The command installs the archive, runs a health check and rolls back to the
    previous release if it fails.
  - Parameter Store: the operator token as a `SecureString` and the app
    settings under `/logiops-ai/config/`, read with `GetParametersByPath` on
    every deploy.
- **Worked well:**
  - The automatic rollback caught a bad package on 2026-10-13 (a missing
    directory) and the previous release kept serving.
  - A new setting is one parameter plus a redeploy: the Polly cap was added
    that way on 2026-10-21, with no new instance.
- **Needs work:** when a deploy fails, the command status says only "Failed";
  finding why takes `get-command-invocation` and, for the service, `journalctl`
  through a second `send-command`.
- **Onboarding:** the managed policy `AmazonSSMManagedInstanceCore` on an
  Amazon Linux 2023 instance was enough; our deploy script wraps the rest.
- **Would build with it again:** yes; nothing on the instance needs a key.

## AWS IAM

- **Used for:** the instance role, limited to its release prefix, its token and
  config parameters, `polly:SynthesizeSpeech`, the actions on its one
  AgentCore Memory, `bedrock:InvokeModel` on its one model profile, plus the
  managed policy Systems Manager needs.
- **Worked well:** temporary role credentials everywhere; no static key exists
  in the deployment.
- **Needs work:** nothing blocked us. The Bedrock statement for a global
  inference profile takes three resource ARNs (the profile, and the foundation
  model with and without a Region); a ready-made example for global profiles
  would help.
- **Onboarding:** written in Terraform with the instance profile.
- **Would build with it again:** yes.

## boto3, botocore and `aws login`

- **Used for:** every AWS call from Python (Bedrock, Polly, AgentCore Memory);
  `aws login` for local credentials; the AWS CLI in the deploy and token
  scripts.
- **Worked well:** SDK retries and timeouts out of the box, and the Stubber for
  tests without paid calls.
- **Needs work:**
  - The login credential provider needs `botocore[crt]`; without it every call
    fails with `MissingDependencyException`, although the CLI works in the same
    shell (friction 2026-10-06).
  - While refreshing `aws login` credentials, botocore raises `NoRegionError`
    even when the client has `region_name`; `AWS_DEFAULT_REGION` is needed
    (friction 2026-10-12).
  - An `aws login` session expires within hours and re-login needs a browser,
    so it blocks unattended work: on 2026-10-19 a deploy failed at the S3
    upload until a person signed in again.
- **Onboarding:** `aws login` worked the first time in a browser; boto3 needed
  the `crt` extra before it could use that session.
- **Would build with it again:** yes.

## AWS Budgets and the Billing console

- **Used for:** budgets of US$50 and US$100 with e-mail alerts, plus a
  zero-spend alert. Since 2026-10-21 a budget action also stops the demo's
  spend: at US$60 of actual monthly cost, credits excluded, it attaches a deny
  policy for Bedrock and Polly to the instance role (`infra/amazon/spend.tf`).
- **Worked well:** set up in minutes; the zero-spend alert fired within hours of
  the first Bedrock calls. The action is plain Terraform, and its execution role
  can be limited with an `iam:PolicyARN` condition to the one policy it may
  attach.
- **Needs work:** alert e-mails require verification through an easy-to-miss
  banner, and the region selector is locked on global consoles with no
  explanation (friction 2026-10-02). A budget action requires at least one
  subscriber even when its only job is the automatic action.
- **Onboarding:** minutes, once the verification e-mail was found.
- **Would use it again:** yes.

## Amazon Route 53 health checks, CloudWatch alarms and SNS

- **Used for:** knowing when the deployed demo is down without depending on
  GitHub's scheduler: an HTTPS health check on `/healthz` through CloudFront
  every 30 seconds, a CloudWatch alarm on `HealthCheckStatus` after three failed
  minutes, and an SNS e-mail on failure and on recovery (`infra/amazon/monitor.tf`,
  2026-10-21).
- **Worked well:** four Terraform resources; minutes after the apply, all 16
  health checkers reported HTTP 200 and the alarm was OK.
- **Needs work:** `terraform apply` reports the e-mail subscription as created
  while it is still `PendingConfirmation`; no alarm reaches anyone until the
  link in AWS's e-mail is followed, and nothing in the apply output says so.
- **Onboarding:** minutes.
- **Would use it again:** yes.

## Model Context Protocol — official Python SDK

- **Used for:** the self-hosted server at `/mcp` (version 1.28.1, stateless,
  JSON responses): 12 tools with titles, annotations and output schemas from
  Pydantic models, 2 prompts, resource templates, completions, the MCP Apps
  view and URL elicitation (`-32042`). The agent's in-process client and the
  test clients use the same SDK.
- **Worked well:**
  - Protocol negotiation (2025-11-25) and structured tool results worked
    between the official client and server with no glue code.
  - `TransportSecuritySettings` checks Host and Origin: a foreign `Origin` gets
    403 on the deployment (checked 2026-10-21).
- **Needs work:** guidance for self-hosted servers that are not OAuth
  providers (a bearer token behind a CDN) is thin.
- **Onboarding:** on 2026-10-05 a local official client negotiated 2025-11-25
  and called `get_shipment`.
- **Would build with it again:** yes.

## MCP Streamable HTTP transport (spec 2025-11-25)

- **Used for:** every MCP conversation: the agent's client, the device in the
  browser (`initialize`, `tools/list`, `tools/call` for its inbox and alerts,
  `resources/read` for the plans card), MCP Inspector and our checks.
- **Worked well:** one POST endpoint with JSON responses sits behind CloudFront
  unchanged; an invalid `MCP-Protocol-Version` gets 400 on the deployment
  (checked 2026-10-21).
- **Needs work:** the security section is written around local servers; a
  public server behind a CDN has to combine the Origin rule, a Host allowlist
  and its own authentication.
- **Onboarding:** the official SDK implements the transport, so we wrote no
  transport code.
- **Would build with it again:** yes.

## MCP Apps (extension 2026-01-26)

- **Used for:** an interactive plan-comparison card declared on
  `investigate_incident` (`text/html;profile=mcp-app`), rendered inside the
  device by our own host bridge through a sandbox proxy on a second origin. We
  published the bridge and the proxy as the MIT library `mcp-apps-web-host`.
- **Worked well:** the handshake is small and plain `postMessage` is enough;
  the host context (theme, size, safe-area insets) is easy to honour; a view
  that can only send `ui/message` makes a clean human-in-the-loop boundary.
- **Needs work:**
  - Web hosts must load views through a sandbox proxy on a different origin.
    For one domain that means a second hostname. A reference proxy page and a
    documented local pattern (we pair `127.0.0.1` with `localhost`) would save
    every host author the same work.
  - Tool `visibility` defaults to `["model", "app"]`, so a state-changing tool
    is callable from views unless you opt out.
- **Onboarding:** we wrote the host bridge (about 130 lines) and the sandbox
  page (about 90 lines) from the specification text, with no SDK.
- **Would build with it again:** yes.

## Agent Skills

- **Used for:** `skills/logiops-exception-desk/SKILL.md`, the playbook for these
  tools (workflow, rules, how to speak on a voice device, what to do when a tool
  fails). The server serves it as `skill://logiops-exception-desk/SKILL.md`;
  the agent reads it at the start of every run and sends it as the first system
  block before the cache point; each run reports its name, URI and SHA-256.
- **Worked well:** plain Markdown with YAML frontmatter, easy to test: our
  tests check the frontmatter, that every tool it names exists, and that the
  file, the MCP resource and the system block are byte-identical. Behind the
  cache point it costs almost nothing after the first turn.
- **Needs work:** MCP has no standard way for a server to advertise a skill, so
  we serve it as a resource and point to it from the server instructions and
  the prompts.
- **Onboarding:** one pull request, following the format at agentskills.io.
- **Would build with it again:** yes.

## MCP Inspector

- **Used for:** checking the deployed server from a standard client, and in the
  demo video.
- **Worked well:** one `npx` command with no install. On 2026-10-21, as a guest
  against the deployment, the CLI listed the tools and `get_shipment` answered.
- **Needs work:** in CLI mode, a tool that needs sign-in (our
  `execute_approved_plan` answers 401 with an OAuth challenge) surfaces as
  `auth_required` with a message about a TTY, which reads like a tooling error
  rather than "this tool needs a token".
- **Onboarding:** `npx @modelcontextprotocol/inspector --cli <url> --transport
  http --method tools/list` worked the first time.
- **Would build with it again:** yes.

## Alexa+ developer tools (Category SDK, MCP Toolkit, CLI, Web Simulator)

- **Used for:** nothing: they are partner-only, and there is no way for
  hackathon participants to request access. Following the FAQ, we built a
  self-hosted MCP server and our own simulated device over it (decision on
  2026-10-03).
- **Worked well:** the FAQ answered the access question clearly.
- **Needs work:** individual setup pages read like open onboarding and do not
  always say the tools are partner-only, which costs time. A public simulator,
  even a limited one, would let builders test the real Alexa+ conversation
  instead of building their own.
- **Onboarding:** we did not get past the access step.
- **Would build with it again:** yes, once access opens. The server already
  speaks MCP over Streamable HTTP with OAuth 2.1; what is left is listed in
  `alexa-plus-readiness.md`.

## Docker

- **Used for:** the judges' local run (`docker compose up --build`, replay mode,
  port published on loopback only) and the CI `docker` job, which builds the
  image and runs `check_mcp.py` and `rehearse_api.py` against the container.
- **Worked well:** one command and no AWS account to run the whole demo.
- **Needs work:** nothing we hit.
- **Onboarding:** standard; the image installs from the lock file with
  `uv sync --frozen`.
- **Would build with it again:** yes.

## Terraform (AWS provider)

- **Used for:** all the AWS resources in `infra/amazon/`.
- **Worked well:** 22 resources (EC2, EBS, S3, IAM, two CloudFront
  distributions) planned cleanly; 13 more (AgentCore Memory with two
  strategies, Cognito, SSM parameters, scoped IAM) applied on 2026-10-11 after a
  plan review; the committed lock file and `validate` made reviews quick.
- **Needs work:** the surprises were service-side limits (the CloudFront origin
  timeout quota) and the AgentCore Memory strategy resource's missing attribute
  descriptions.
- **Onboarding:** a standard `init`, `plan`, `apply` with `aws login`
  credentials.
- **Would build with it again:** yes.
