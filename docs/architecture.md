# Architecture

## Current local implementation

`logiops/scenario.py` owns the fixed synthetic data and derives the three
cost/ETA options. `logiops/tools.py` exposes read-only shipment, order,
inventory, and carrier lookups. `logiops/service.py` runs investigation,
approval, execution, and operational verification in SQLite transactions;
it records source versions and audit events. `logiops/api.py` exposes this
workflow through FastAPI and Swagger. `logiops/mcp_server.py` exposes real MCP
tools over Streamable HTTP at `/mcp`. `logiops/agent.py` runs the Bedrock
Converse tool loop through that MCP endpoint; `logiops/bedrock.py` invokes the
AWS CLI with the user's `aws login` credentials. `logiops/replay.py` provides
an explicit deterministic local replay. `logiops/security.py` enforces a
bearer token when configured and a per-process MCP request limit. A React UI
and public HTTPS deployment are not yet connected.

`infra/amazon/` prepares a single-instance AWS demo. CloudFront gives the
public HTTPS URL; EC2 serves the API and MCP endpoint with an IAM instance
role for Bedrock. A separate EBS volume stores SQLite so the incident and
audit trail survive instance restarts. Deployment uses a private S3 archive
and Systems Manager, without SSH or static AWS keys on the instance. This
infrastructure remains unprovisioned until AWS access is restored and its
Terraform plan is reviewed.

The scenario, service, tools, and tests are provider-independent; the MCP
and Bedrock modules are the Amazon-specific layer. The model sees only read and investigation tools; human approval uses
REST, and the backend checks the exact plan ID and source version before
execution through REST or MCP.

## Target architecture

```text
                    React UI
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

## Modules

```text
domain/      shipment, order, inventory, routing, incident, resolution_plan
agent/       planner, executor, evaluator, policy, memory
tools/       get_shipment, get_inventory, get_route_status, find_alternative,
             execute_plan, notify
transport/   http/, mcp/
frontend/    react/
```

## AWS services (justify each one here as they're added)

_TODO — fill in during phase F6, only services with a real reason to be there._
