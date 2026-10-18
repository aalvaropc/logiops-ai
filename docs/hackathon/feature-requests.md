# Feature requests — Amazon / AWS, with priority

Required by the submission (rules 3.16). Priority is what would have saved the most
time or risk in this project: **P1** blocked or cost days, **P2** cost hours or a
workaround we had to test, **P3** polish. Each request names the evidence in
`amazon-friction-log.md` or `amazon-feedback.md`.

| Priority | Product | Request | Why (evidence) |
|---|---|---|---|
| P1 | Alexa+ developer tools | A public Alexa+ simulator (even a limited one) and public access to the MCP toolkit for hackathon participants. | The tools are partner-only; we built our own device simulation to show the conversation and the cards (`alexa-plus-readiness.md`, feedback "Alexa+ developer tools"). |
| P1 | MCP Apps | A reference sandbox proxy page in the SDK and a documented local-development pattern (two loopback origins). | Every web host must build the second-origin proxy; ours is `mcp_app_sandbox.html` plus a second CloudFront distribution (feedback "MCP Apps"). |
| P1 | Strands Agents | An MCP client mode that runs on the caller's event loop (or accepts an existing `ClientSession`) instead of a background thread. | `MCPClient` deadlocks with an in-process stateless Streamable HTTP server; we wrapped each tool in our own `AgentTool` (friction 2026-10-12). |
| P2 | Amazon Cognito | Advertise `code_challenge_methods_supported` in the OIDC discovery document and support RFC 8707 resource indicators (an `aud` per resource server). | MCP clients expect both; we publish our own RFC 8414 document and check scopes instead of `aud` (friction 2026-10-11). |
| P2 | Amazon Bedrock AgentCore Memory | `ListEvents` by actor with a time filter, or a "latest sessions with their last events" call. | "Welcome back" needs `ListSessions` plus a second call today (friction 2026-10-11). |
| P2 | Amazon CloudFront | A managed cache policy "forward Authorization, never cache". | `CachingDisabled` drops `Authorization` on GET (friction 2026-10-05). |
| P2 | Amazon Bedrock | Say in the `AccessDeniedException` why a model needs AWS Sales and which models self-serve. | Claude Sonnet 5.5 vs 4.6 (friction 2026-10-02). |
| P2 | AWS credits and Marketplace billing | State on the credits form whether Marketplace-billed models (Claude on Bedrock) are covered, and show it in the Credits page within hours, not days. | The model is the main runtime cost of a Bedrock hackathon (feedback "AWS promotional credits"). |
| P2 | boto3 / `aws login` | Make the login credential provider work without the `crt` extra, or say so in the `aws login` docs; resolve the credential-refresh region from the client's `region_name`. | `MissingDependencyException` (friction 2026-10-06) and `NoRegionError` while refreshing credentials even with `region_name` set (friction 2026-10-12). |
| P3 | Strands Agents | Document that `AfterModelCallEvent` runs before the max-tokens recovery and how `limits["turns"]` counts cycles; a lighter install without OpenTelemetry and watchdog for servers that do not trace. | We relied on reading the source to place the guards (feedback "Strands Agents"). |
| P3 | Amazon Polly | A per-text cache hint or ETag so callers can dedupe without their own store. | We cache MP3 per text in SQLite to stay under the daily budget (feedback "Amazon Polly"). |
| P3 | Terraform AWS provider | Attribute descriptions and deprecation notes on `aws_bedrockagentcore_memory_strategy`. | `namespaces` vs `namespace_templates` found only in the schema (friction 2026-10-11). |
| P3 | MCP Apps | Default tool `visibility` to `["model"]`, or warn when a destructive tool is callable from views. | Easy to miss (feedback "MCP Apps"). |
