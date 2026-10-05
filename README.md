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
runs the same MCP calls without AWS charges. A web interface and public HTTPS
deployment are pending. See `docs/hackathon/decisions.md` for decisions and
`docs/demo-scenario.md` for the synthetic data.

The AWS demo infrastructure and deployment procedure live in
[`infra/amazon/README.md`](infra/amazon/README.md). It has not been provisioned
yet; local tests do not claim a remote or live Bedrock run.

## Setup

Install Python 3.12 or newer, [uv](https://docs.astral.sh/uv/), and the AWS CLI.
For the live agent, sign in with `aws login` and ensure the Bedrock model in
`.env.example` is accessible in `us-east-1`. Then run:

```sh
uv sync --extra dev
uv run uvicorn logiops.api:app --host 127.0.0.1 --port 8000
```

Open <http://127.0.0.1:8000/docs>. The MCP endpoint is
<http://127.0.0.1:8000/mcp> and negotiates protocol version 2025-11-25.
The SQLite database is created at
`data/logiops.sqlite3` and survives server restarts. Set `LOGIOPS_DB_PATH` to
change the location. The default configuration is **local only**. Do not bind
it to a public interface without `LOGIOPS_PUBLIC=1`, a random
`LOGIOPS_ACCESS_TOKEN` of at least 32 characters, and HTTPS. In public mode the
token guards both REST and MCP; MCP requests are limited to 60 per minute per
client IP in a single process. A production deployment needs shared rate
limiting and appropriate proxy configuration.

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
`bedrock`. It uses AWS CLI credentials and calls Converse on each agent turn.

In Swagger, run `POST /demo/reset`, `POST /incidents/SHIP-421/agent/investigate`
(or the deterministic `/investigate` endpoint),
`POST /incidents/SHIP-421/approvals`, `POST /incidents/SHIP-421/execute`, and
`GET /incidents/SHIP-421`, in that order. Copy `plan_id` and `source_version`
from the `split-express` plan into approval and execution requests. Use
`approved_by: "demo-operator"`. `POST /demo/inventory` can change local stock
to demonstrate that an old approval cannot execute a stale plan.

The result verifies operational state changes, **not physical delivery**. The
zero-hour customer delay is a projection from the synthetic carrier times.
Run tests with `uv run pytest`. The MCP interoperability tests use the
official Python MCP client against the in-process ASGI app.

## License

MIT — see [LICENSE](LICENSE).
