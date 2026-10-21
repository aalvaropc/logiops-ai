import pytest

from tests.test_oauth import BOOK, MCP_HEADERS, OPERATE, bearer, run_app, token


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
