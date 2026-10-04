# Architecture

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
