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
it records source versions and audit events. `logiops/api.py` exposes this
workflow through FastAPI and Swagger. `logiops/mcp_server.py` exposes real MCP
tools over Streamable HTTP at `/mcp`. `logiops/agent.py` runs the Bedrock
Converse tool loop through that MCP endpoint; `logiops/bedrock.py` calls
Converse with boto3 and the default credential chain (an `aws login` session
locally, the instance role on EC2). `logiops/replay.py` provides an explicit
deterministic local replay. `logiops/security.py` enforces a bearer token when
configured, per-viewer limits for MCP and for agent runs, and `no-store`
responses. The browser
demo at `/demo` calls the same API and shows plans, approval, execution, and
audit history.

`infra/amazon/` prepares a single-instance AWS demo. CloudFront gives the
public HTTPS URL; EC2 serves the API and MCP endpoint with an IAM instance
role for Bedrock. A separate EBS volume stores SQLite so the incident and
audit trail survive instance restarts. Deployment uses a private S3 archive
and Systems Manager, without SSH or static AWS keys on the instance. It was
provisioned on 2026-10-06; `scripts/deploy_ec2.py` ships only `origin/main`.

The scenario, service, tools, and tests are provider-independent; the MCP
and Bedrock modules are the Amazon-specific layer. The model sees only read and investigation tools; human approval uses
REST, and the backend checks the exact plan ID and source version before
execution through REST or MCP.

## Runtime architecture

```text
                Browser demo (/demo)
                       |
                  API / Backend
                       |
               Agent Orchestrator
                       |
          +------------+------------+
          |                         |
   Amazon Bedrock              Tool / MCP Layer
   (Claude, tool use)                |
                        +----------+----------+
                        |          |          |
                      Orders  Inventory  Routing
                                              |
                                           Actions
```

## AWS services and their purpose

- **Bedrock Converse:** the agent chooses MCP read tools and explains the
  calculated resolution plans. A deterministic replay supports offline review.
- **EC2:** runs FastAPI, MCP, and the browser demo in one process. The instance
  role supplies temporary Bedrock, S3, and Systems Manager permissions.
- **EBS:** stores SQLite separately from the EC2 root filesystem so the audit
  history survives instance restarts.
- **S3 and Systems Manager:** transfer a checksum-verified release and run its
  installation without SSH or long-lived credentials on the instance.
- **CloudFront:** gives judges a stable HTTPS address. The EC2 security group
  accepts origin traffic only from CloudFront's origin-facing prefix list;
  CloudFront to EC2 currently uses HTTP, with bearer authentication for the
  incident and MCP routes.

These resources are defined in `infra/amazon/` and were provisioned on 2026-10-06.
