# Demo scenario: four synthetic incidents

All data is synthetic and every incident is marked `simulated: true`. Times
use `America/Lima` (UTC-05:00). The dates below are the seed's own: the first
orders are due on 2026-10-12, the rest one or two days later. The app moves every
timestamp by whole days so that first day is always tomorrow
(`LOGIOPS_SCENARIO_ANCHOR`: `relative` by default, `fixed`, or a `YYYY-MM-DD` day
between 2000 and 2099). Untouched incidents follow the calendar on their own, and
any incident whose first day has passed is re-seeded when the inbox is read, so a
long-running demo never shows overdue dates. Times of day, delays, costs and plans
never change. Each incident is self-contained (its own
orders, stock and carrier quotes) and isolated: working one never changes
another's plans, approvals, executions or audit trail.

| Incident | Kind | What happened | Default pick |
|---|---|---|---|
| SHIP-421 | Delayed in transit | 20 laptops Lima → Arequipa, 12 h late | split + express |
| SHIP-433 | Carrier outage | The booked carrier stopped departures Lima → Cusco; a critical hospital order and a store order share the shipment | fly the hospital order, rebook the store order on ground |
| SHIP-452 | Customs hold | 40 routers held at Callao customs; the standard review takes 72 h | ship Lima stock now, expedite clearance for the rest |
| SHIP-460 | Orders competing for stock | A delayed replenishment leaves 30 laptops in Trujillo for a critical hospital order (20) and a school order (25) | serve the hospital first, cover the school by express transfer |

The plans are **calculated** from each incident's data, never written by the
model: each incident lists its options in `logiops/scenario.py`
(`PLAYBOOKS`), and one fill turns them into allocations, ETAs, per-order
delays, late units and cost. An option that the current stock or capacity
cannot cover is not offered.

**Default pick.** Plans are ranked by the worst delay of a *critical* order,
then the worst delay of any order, then late units, then cost. Ranked only by
delay and cost, SHIP-433 would pick the $150 ground reroute, which leaves the
hospital 8 h late; ranked this way, the hospital is on time. The first key
alone decides under a $250 spend cap: without it the cap would point to the
reroute, with it to flying the hospital order ($240).

## SHIP-421 · delayed in transit

The fixture fixes the original ETA at **2026-10-12 14:00** and the disrupted
ETA at **2026-10-13 02:00**. Local stock has 12 units ready by 10:00 on
October 12. The economy reroute has capacity 20, arrives at 17:00, and costs
$80 extra. Express has capacity 8, arrives at 13:00, and costs $120 extra.

| Plan | Allocation | Delay | Cost |
|---|---|---|---|
| Wait | 20 on the delayed shipment | 12 h | $0 |
| Reroute | 20 via economy reroute | 3 h | $80 |
| Split + express | 12 from Arequipa stock + 8 express | 0 h | $120 |

With 20 or more units in stock, **fulfil the whole order from local stock**
($0, 0 h) replaces split + express. With 11, split + express would need 9
express units but express carries 8, so only wait and reroute remain.

## SHIP-433 · carrier outage (two orders, one critical)

30 tablets Lima → Cusco, due 2026-10-13 12:00. The carrier's own restart
estimate puts arrival 24 h late. ORD-433A (Cusco regional hospital,
**critical**, 12 units) and ORD-433B (Cusco electronics store, 18 units).
Quotes: ground reroute (30 units, +8 h, $150), air freight (12 units, on time,
$240). There is no local warehouse, so the stock control is disabled.

| Plan | Hospital | Store | Cost |
|---|---|---|---|
| Wait for the carrier | +24 h | +24 h | $0 |
| Rebook both on ground | +8 h | +8 h | $150 |
| Fly the hospital order; the store waits | on time | +24 h | $240 |
| Fly the hospital order; rebook the store on ground | on time | +8 h | $390 |

## SHIP-452 · customs hold

40 routers from Callao to a Lima telecom distributor, due 2026-10-12 16:00.
Customs flagged a documentation discrepancy; the standard review releases
them 72 h late. The Lima warehouse has 25 units ready at 12:00. A customs
broker can expedite clearance (+18 h, $350).

| Plan | Allocation | Worst delay | Late units | Cost |
|---|---|---|---|---|
| Wait for the review | 40 held | 72 h | 40 | $0 |
| Expedite clearance | 40 expedited | 18 h | 40 | $350 |
| Lima stock now, the rest after the review | 25 + 15 held | 72 h | 15 | $0 |
| Lima stock now, expedite the rest | 25 + 15 expedited | 18 h | 15 | $350 |

With 40 or more units in the Lima warehouse, **ship everything from Lima** ($0,
on time) replaces the two split plans.

## SHIP-460 · two orders competing for stock

A replenishment of 30 laptops to Trujillo is 48 h late. The warehouse has 30
units ready at 08:00 on October 13. ORD-460 (Trujillo regional hospital,
**critical**, 20 units, due 10-13 12:00) and ORD-461 (school district, 25
units, due 10-14 12:00, placed first). An express transfer from Lima carries
15 units (arrives 10-13 20:00, $300).

| Plan | Hospital | School | Cost |
|---|---|---|---|
| Serve the hospital first; the school waits for the replenishment | on time | +6 h | $0 |
| Serve orders as placed (school first) | +30 h | on time | $0 |
| Hospital first; cover the school by express transfer | on time | on time | $300 |

With 15–29 units in stock only the first two remain, and with 45 or more the
warehouse covers both orders on its own. Below 15 no plan covers both orders:
`POST /incidents/SHIP-460/investigate` answers 409 "No feasible plan", and the
agent's investigation fails with a clear error (502) instead of inventing one.

## Stock changes

The stock control adjusts the incident's own warehouse (none for SHIP-433)
and bumps the incident's data version: earlier plans and approvals stop
applying, and a new investigation recalculates the options.

## Operator preferences

Saved preferences pick among the same calculated plans by fixed rules. With a
spend cap of $250:

| Incident | Default pick | With the $250 cap |
|---|---|---|
| SHIP-421 | split + express, $120 | unchanged |
| SHIP-433 | fly the hospital order, ground for the store, $390 | fly the hospital order, the store waits, $240 |
| SHIP-452 | ship Lima stock, expedite the rest, $350 | ship Lima stock, the rest after the review, $0 |
| SHIP-460 | serve the hospital, express transfer for the school, $300 | serve the hospital first, the school waits, $0 |

With `cheapest_unless_critical_late`, SHIP-421 moves to waiting ($0) and
SHIP-433 still flies the hospital order ($240): its $0 and $150 options leave
the critical order late. A $200 cap on SHIP-433 points to the ground reroute
and warns that the hospital order is 8 h late.

## Agent flow

```text
1. get_shipment(SHIP-433)                -> route, delay, order ids, warehouse (none here)
2. find_alternative_carriers(SHIP-433)   -> ground and air quotes
3. get_order(ORD-433A), get_order(ORD-433B) -> quantities, priorities, due times
4. get_inventory(...)                    -> only when the incident has a warehouse
5. investigate_incident(SHIP-433)        -> server computes the feasible plans
6. operator approves one plan            -> POST /incidents/SHIP-433/approvals
7. execute_approved_plan (MCP) or POST /incidents/SHIP-433/execute
8. get_execution_status(SHIP-433)        -> verify allocations, notifications, audit
```

`list_incidents` (MCP) and `GET /incidents` return the inbox; the briefing
(`POST /agent/briefing`) reads it and ranks the open incidents without
calculating plans. No MCP tool can
approve a plan. A person approves one exact plan (`plan_id` +
`source_version`) through the REST API. The Bedrock agent only gets the read
and investigation tools. MCP clients can call `execute_approved_plan`, but
execution re-checks the exact approval, and that every order's units are
covered exactly once, before applying anything.

Verification means the selected plan's inventory, carrier capacity,
notifications (one per customer order, plus operations) and audit events were
applied exactly once, and that every order's units are accounted for. It does
not claim physical delivery.
