# LogiOps AI

An agent that investigates and resolves logistics exceptions
(e.g. a delayed shipment): it queries orders, inventory and routes, compares
alternatives by cost and ETA, requests human approval, executes the chosen
plan, and verifies the result.

Built for the **Amazon Developer Hackathon**, Alexa+ track (self-hosted MCP
server, Streamable HTTP) + AWS Builder Mini Challenge. Runtime: Amazon
Bedrock.

## Submission

| Tag | Devpost | Live demo |
|---|---|---|
| _pending_ | _pending_ | _pending (hosting optional, see docs/hackathon/decisions.md D-AMZ-1)_ |

## Status

The SHIP-421 workflow, MCP Streamable HTTP endpoint, Bedrock Converse tool
loop, approval gate, and operational verification run locally. A replay mode
runs the same MCP calls without AWS charges. A browser interface is available
at `/demo`; public HTTPS deployment is pending. See
`docs/hackathon/decisions.md` for decisions and
`docs/demo-scenario.md` for the synthetic data.

The AWS demo infrastructure and deployment procedure live in
[`infra/amazon/README.md`](infra/amazon/README.md). It has not been provisioned
yet; local tests do not claim a remote or live Bedrock run.

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

Open the browser demo at <http://127.0.0.1:8000/demo>. It simulates the
Alexa+ experience as a conversation: ask "What's happening with SHIP-421?" by
text, or by voice in browsers with speech recognition (Chrome, Edge), and
optionally have replies read aloud. Say "approve the recommended plan" and
then "execute it"; those requests use the same REST approval and execution
endpoints as the buttons, so the version checks are identical. The plan
cards, timeline, and a stock-change control show how a data change
invalidates an earlier approval. On the public deployment, paste the operator
token into the page to connect. It stays in browser memory until the page is
reloaded.

The API reference is at <http://127.0.0.1:8000/docs>. The MCP endpoint is
<http://127.0.0.1:8000/mcp> and negotiates protocol version 2025-11-25.
The SQLite database is created at
`data/logiops.sqlite3` and survives server restarts. Set `LOGIOPS_DB_PATH` to
change the location. The default configuration is **local only**. Do not bind
it to a public interface without `LOGIOPS_PUBLIC=1`, a random
`LOGIOPS_ACCESS_TOKEN` of at least 32 characters, and HTTPS. In public mode the
token guards both REST and MCP. In a single process, MCP requests are limited
to 60 per minute and agent runs (each one calls a paid model) to 5 per minute
per viewer. Behind CloudFront, set `LOGIOPS_TRUST_CLOUDFRONT=1` so viewers are
identified by the `CloudFront-Viewer-Address` header instead of the shared
edge IP; only do this when the origin accepts traffic exclusively from
CloudFront. The agent's own in-process MCP calls are exempt from the MCP
limit. Responses carry `Cache-Control: no-store`. A production deployment
needs shared rate limiting.

### Agent investigation

```sh
curl -sS -X POST http://127.0.0.1:8000/demo/reset
curl -sS -X POST http://127.0.0.1:8000/incidents/SHIP-421/agent/investigate \
  -H 'Content-Type: application/json' -d '{}'
curl -sS http://127.0.0.1:8000/incidents/SHIP-421
```

The agent receives only read and investigation tools. Its MCP tool results,
response, and token usage are recorded in the incident's events. The API
returns the calculated plans separately from the model's explanation. For a
deterministic rehearsal, launch the server with `LOGIOPS_AGENT_MODE=replay`;
the response says `mode: replay` and reports zero tokens. Normal mode is
`bedrock`. It calls Converse through boto3 with SDK retries, and a run stops
with a clear error after 50 seconds so it always answers before CloudFront's
60-second origin timeout.

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
botocore's service model without a paid call.

## License

MIT — see [LICENSE](LICENSE).
