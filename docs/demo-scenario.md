# Demo scenario: SHIP-421

```text
Shipment: SHIP-421
Route: Lima -> Arequipa
Original ETA: 14:00
New ETA: 02:00 next day
Delay: 12 hours
Order: 20 laptops
```

All times use `America/Lima` (UTC-05:00). The fixture fixes the original ETA
at **2026-10-12 14:00** and the disrupted ETA at **2026-10-13 02:00**. Local
stock has 12 units ready by 10:00 on October 12. The economy reroute has
capacity 20, arrives at 17:00, and costs $80 extra. Express has capacity 8,
arrives at 13:00, and costs $120 extra. The three options therefore project
delays of 12, 3, and 0 hours respectively.

## Expected plan (option C, "split + express")

```text
- 12 units fulfilled from Arequipa warehouse stock
- 8 units shipped from Lima via an alternative express carrier,
  arriving before the original ETA
- additional cost: $120
- customer-facing delay: 0 h
```

The 8 units are **not** left on the delayed shipment — they're re-routed
through an express carrier so the whole order still lands on time. (This
replaces an earlier draft of the scenario that left those 8 units on the
delayed shipment while also claiming 0 h delay, which didn't add up.)

## Agent flow

```text
1. get_shipment(SHIP-421)         -> detect delay
2. get_order(...)                 -> 20 laptops
3. get_inventory / find_nearby_inventory(Arequipa) -> 12 units available
4. find_alternative_carriers(...) -> express option for remaining 8 units
5. calculate_reroute_cost(...)    -> compare options (wait / reroute / split+express)
6. request_human_approval(...)    -> present the 3 options, user approves split+express
7. create_split_fulfillment(...) + update_shipment(...) -> execute
8. notify_customer / notify_operations
9. get_execution_status(...)      -> verify
```

For the first local implementation, verification means the selected plan's
inventory, route, notifications, and audit events were applied exactly once.
It does not claim that the laptops were physically delivered. Plans are tied
to the source data version; a stock change invalidates prior approval.
