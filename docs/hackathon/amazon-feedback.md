# Product Feedback — Amazon / AWS

Required by the Amazon submission (rules 3.16). Entries added as the project
is built; see also `amazon-friction-log.md` for discrete problems.

## 2026-10-02 — AWS account setup + Bedrock access

- **What I used it for:** standing up an AWS account, IAM user with admin
  access (existing account, reused an old `admin` IAM group), AWS Budgets
  alerts, and Bedrock model access for Claude Sonnet 4.6 in `us-east-1`.
- **What worked well:** IAM console login flow with pre-existing groups made
  setting up a scoped-enough user fast. `aws login` (browser-based) meant no
  long-lived access keys were needed for local testing.
- **Problems:** the "Model access" page referenced in older docs/guides no
  longer exists in the console; access is now granted per-model via a use-case
  form shown the first time you open a model in the Playground. Claude Sonnet
  5.5 is not available on this account at all (`AccessDeniedException`,
  pointing to AWS Sales) with no self-service path — unclear why, since
  Sonnet 4.6 worked immediately after the same use-case form.
- **Would I use it again:** yes, Bedrock's Converse API with tool calling
  worked correctly on the first real call.

## 2026-10-05 — MCP SDK and Bedrock integration

- **What I used it for:** implemented Streamable HTTP tools for the shipment
  incident and a Converse tool-use loop that sends the tool schemas to Bedrock.
- **What worked well:** the official Python MCP client and server negotiated
  protocol version 2025-11-25 in local integration tests; tool results carry
  structured JSON suitable for Converse `toolResult` blocks.
- **Problems:** a fresh live Bedrock smoke call could not complete in the
  restricted development environment because `aws login` could not reach the
  AWS sign-in token endpoint. The earlier 2026-10-02 account test succeeded.
- **Would I use it again:** yes; the SDK and Converse interfaces fit the
  read-only investigation flow. Live integration still needs a connected run.
