import pytest

from tests.test_oauth import BOOK, MCP_HEADERS, OPERATE, bearer, rpc, run_app, token


@pytest.mark.parametrize("credentials, allowed", [(None, False), ("openid", False), (BOOK, False), (OPERATE, True)])
def test_booking_details_follow_the_same_permissions(tmp_path, credentials, allowed):
    async def work(http, _app):
        full = bearer(token())
        plan = (await http.post("/incidents/SHIP-421/investigate")).json()["plans"][2]
        await http.post("/incidents/SHIP-421/approvals", headers=full, json={
            "plan_id": plan["id"], "source_version": plan["source_version"], "approved_by": "judge"})
        quote = (await http.post("/incidents/SHIP-421/bookings/quote", headers=full)).json()
        booking = (await http.post(f"/quotes/{quote['quote_id']}/confirm", headers=full, json={
            "confirmed_total_usd": quote["total_usd"], "idempotency_key": "booking-access-test"})).json()
        headers = bearer(token(scope=credentials)) if credentials else {}
        incident = (await http.get("/incidents/SHIP-421", headers=headers)).json()
        assert bool(incident["bookings"]) is allowed
        for scheme in ("receipt", "RECEIPT", "ReCeIpT"):
            response = await http.post("/mcp", headers={**MCP_HEADERS, **headers}, json={
                "jsonrpc": "2.0", "id": 1, "method": "resources/read",
                "params": {"uri": f"{scheme}://logiops/{booking['number']}"}})
            assert response.status_code == (200 if allowed else 403 if credentials else 401)
            assert ("LogiOps receipt" in response.text) is allowed

    run_app(tmp_path, work)


async def book(http):
    full = bearer(token())
    plan = (await http.post("/incidents/SHIP-421/investigate")).json()["plans"][2]
    await http.post("/incidents/SHIP-421/approvals", headers=full, json={
        "plan_id": plan["id"], "source_version": plan["source_version"], "approved_by": "judge"})
    quote = (await http.post("/incidents/SHIP-421/bookings/quote", headers=full)).json()
    return (await http.post(f"/quotes/{quote['quote_id']}/confirm", headers=full, json={
        "confirmed_total_usd": quote["total_usd"], "idempotency_key": "booking-access-test"})).json()


def test_public_metrics_hide_the_booking_number_and_amount(tmp_path):
    async def work(http, _app):
        booking = await book(http)
        response = await http.get("/metrics")
        assert response.status_code == 200
        assert booking["number"] not in response.text
        assert all("booking_number" not in item and "booking_total_usd" not in item for item in response.json()["incidents"])
        assert response.json()["session"]["booked_usd"] == booking["total_usd"]

    run_app(tmp_path, work)


@pytest.mark.parametrize("scope, status", [(OPERATE, 200), (BOOK, 403), ("openid", 403)])
def test_the_get_booking_tool_needs_incidents_operate(tmp_path, scope, status):
    async def work(http, _app):
        booking = await book(http)
        response = await http.post("/mcp", headers={**MCP_HEADERS, **bearer(token(scope=scope))}, json=rpc(
            "get_booking", {"number": booking["number"]}))
        assert response.status_code == status
        assert (booking["number"] in response.text) is (status == 200)

    run_app(tmp_path, work)


def test_a_batch_cannot_read_a_booking_with_only_the_book_scope(tmp_path):
    async def work(http, _app):
        booking = await book(http)
        batch = [rpc("get_booking", {"number": booking["number"]}), rpc(
            "book_carrier", {"quote_id": "Q-1", "confirmed_total_usd": 1, "idempotency_key": "abcdefgh"}, 2)]
        response = await http.post("/mcp", headers={**MCP_HEADERS, **bearer(token(scope=BOOK))}, json=batch)
        assert booking["number"] not in response.text

    run_app(tmp_path, work)


@pytest.mark.parametrize("params", ["bad", [1], {"uri": 5}, {"uri": {"a": 1}}])
def test_a_malformed_resource_read_is_not_a_server_error(tmp_path, params):
    async def work(http, _app):
        response = await http.post("/mcp", headers=MCP_HEADERS, json={
            "jsonrpc": "2.0", "id": 1, "method": "resources/read", "params": params})
        assert response.status_code < 500

    run_app(tmp_path, work)
