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
