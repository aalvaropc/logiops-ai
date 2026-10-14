"""Carrier bookings: quote, simulated payment and receipt, charged once and only for an approved plan."""

import asyncio
import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import httpx
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.exceptions import McpError
from pydantic import AnyUrl

from logiops import booking as booking_module
from logiops.api import create_app
from logiops.booking import BookingStore, breakdown, cents_of
from logiops.identity import OPERATOR
from logiops.service import LogiOpsService, WorkflowError

BASE_URL = "http://127.0.0.1:8000"
PLAN_ID = re.compile(r"SHIP-\d+:[0-9a-f][0-9a-f-]{7,}:[a-z][a-z-]*:v\d+")


class Clock:
    def __init__(self):
        self.now = datetime(2026, 10, 12, 15, 0, tzinfo=timezone.utc)

    def __call__(self):
        return self.now


def approved(service, incident_id="SHIP-421", kind="split-express"):
    plan = next(item for item in service.investigate(incident_id) if item["kind"] == kind)
    service.approve(incident_id, plan["id"], plan["source_version"], "operator")
    return plan


def store(tmp_path, clock=None):
    service = LogiOpsService(tmp_path / "booking.sqlite3")
    return service, BookingStore(tmp_path / "booking.sqlite3", service, clock=clock)


def test_the_breakdown_adds_up_and_matches_the_spoken_summary(tmp_path):
    service, bookings = store(tmp_path)
    plan = approved(service)
    quote = bookings.quote("SHIP-421", None, OPERATOR)
    assert (quote["base_usd"], quote["service_fee_usd"], quote["tax_usd"], quote["total_usd"]) == (120.0, 5.0, 22.5, 147.5)
    assert round(quote["base_usd"] + quote["service_fee_usd"] + quote["tax_usd"], 2) == quote["total_usd"]
    assert quote["plan_id"] == plan["id"] and quote["approved"] is True and quote["tax_rate"] == 0.18 and quote["tax_label"] == "Tax 18%"
    assert quote["lines"] == [{"service": "Express", "units": 8, "arrival_eta": quote["lines"][0]["arrival_eta"], "cost_usd": 120.0}]
    for figure in ("$120.00", "$5.00", "Tax 18% $22.50", "total $147.50", "corporate card ending 4242", "local time"):
        assert figure in quote["summary"], figure
    assert not PLAN_ID.search(quote["summary"])
    assert bookings.quote("SHIP-421", None, OPERATOR)["quote_id"] == quote["quote_id"], "an open quote is reused"


@pytest.mark.parametrize("dollars, tax", [(80, 15.30), (150, 27.90), (240, 44.10), (390, 71.10), (350, 63.90), (300, 54.90)])
def test_tax_is_18_percent_of_cost_plus_fee_rounded_to_cents(dollars, tax):
    price = breakdown({"incremental_cost_usd": dollars})
    assert price["tax"] == round(tax * 100) and price["total"] == dollars * 100 + 500 + price["tax"]


def test_the_tax_rate_and_name_come_from_the_environment(monkeypatch):
    monkeypatch.setenv("LOGIOPS_TAX_RATE", "0.0825")
    assert booking_module._tax_rate() == Decimal("0.0825")
    monkeypatch.delenv("LOGIOPS_TAX_RATE")
    assert booking_module._tax_rate() == Decimal("0.18")
    for bad in ("abc", "1", "-0.1", "NaN", ""):
        monkeypatch.setenv("LOGIOPS_TAX_RATE", bad)
        with pytest.raises(RuntimeError, match="LOGIOPS_TAX_RATE"):
            booking_module._tax_rate()
    assert [booking_module._tax_label(name, Decimal(rate)) for name, rate in (("Tax", "0.18"), ("VAT", "0.0825"), ("GST", "0.10"), ("Tax", "0"))] == [
        "Tax 18%", "VAT 8.25%", "GST 10%", "Tax 0%"]


def test_a_configured_rate_changes_the_price_and_the_label(monkeypatch):
    monkeypatch.setattr(booking_module, "TAX_RATE", Decimal("0.10"))
    price = breakdown({"incremental_cost_usd": 100})
    assert price["tax"] == 1050 and price["total"] == 11550


def test_paying_charges_the_quoted_total_once(tmp_path):
    service, bookings = store(tmp_path)
    approved(service)
    quote = bookings.quote("SHIP-421", None, OPERATOR)
    booking = bookings.confirm(quote["quote_id"], "147.50", "key-00000001", OPERATOR)
    assert re.fullmatch(r"LGO-[A-Z2-9]{6}", booking["number"])
    assert booking["payment"]["amount_usd"] == booking["total_usd"] == 147.5 and booking["payment"]["status"] == "captured"
    assert booking["number"] in booking["confirmation"] and "$147.50" in booking["confirmation"]
    assert "projected" in booking["confirmation"] and not PLAN_ID.search(booking["confirmation"])
    replay = bookings.confirm(quote["quote_id"], 147.5, "key-00000001", OPERATOR)
    assert replay["replayed"] is True and replay["number"] == booking["number"]
    with pytest.raises(WorkflowError, match=f"already booked as {booking['number']}. Nothing was charged again"):
        bookings.confirm(quote["quote_id"], 147.5, "key-00000002", OPERATOR)
    with pytest.raises(WorkflowError, match="already booked"):
        bookings.quote("SHIP-421", None, OPERATOR)
    assert bookings.for_incident("SHIP-421") == [booking] and bookings.get(booking["number"].lower()) == booking


@pytest.mark.parametrize("amount", ["147.49", 147.51, 0, "120"])
def test_a_different_amount_is_refused_and_nothing_is_charged(tmp_path, amount):
    service, bookings = store(tmp_path)
    approved(service)
    quote = bookings.quote("SHIP-421", None, OPERATOR)
    with pytest.raises(WorkflowError, match="does not match the quoted total \\$147.50. Nothing was charged") as refused:
        bookings.confirm(quote["quote_id"], amount, "key-00000003", OPERATOR)
    assert refused.value.status_code == 409 and bookings.for_incident("SHIP-421") == []


@pytest.mark.parametrize("amount", ["147.505", "abc", True, -1, "NaN"])
def test_an_amount_that_is_not_money_is_rejected(amount):
    with pytest.raises(WorkflowError) as refused:
        cents_of(amount)
    assert refused.value.status_code == 422


def test_an_expired_quote_cannot_be_paid(tmp_path):
    clock = Clock()
    service, bookings = store(tmp_path, clock)
    approved(service)
    quote = bookings.quote("SHIP-421", None, OPERATOR)
    clock.now += timedelta(minutes=10)
    with pytest.raises(WorkflowError, match="That price expired. Ask for a new quote; nothing was charged"):
        bookings.confirm(quote["quote_id"], 147.5, "key-00000004", OPERATOR)
    fresh = bookings.quote("SHIP-421", None, OPERATOR)
    assert fresh["quote_id"] != quote["quote_id"]
    assert bookings.confirm(fresh["quote_id"], 147.5, "key-00000004", OPERATOR)["status"] == "confirmed"


def test_a_plan_made_stale_by_a_stock_change_cannot_be_paid(tmp_path):
    service, bookings = store(tmp_path)
    approved(service)
    quote = bookings.quote("SHIP-421", None, OPERATOR)
    service.set_local_inventory("SHIP-421", 3)
    with pytest.raises(WorkflowError, match="older data") as refused:
        bookings.confirm(quote["quote_id"], 147.5, "key-00000005", OPERATOR)
    assert refused.value.status_code == 409 and not PLAN_ID.search(str(refused.value))
    assert bookings.for_incident("SHIP-421") == []


def test_an_unapproved_plan_is_priced_but_not_booked(tmp_path):
    service, bookings = store(tmp_path)
    plan = next(item for item in service.investigate("SHIP-433") if item["kind"] == "priority-air-ground")
    quote = bookings.quote("SHIP-433", plan["id"], OPERATOR)
    assert quote["approved"] is False and quote["total_usd"] == 466.1
    assert [line["cost_usd"] for line in quote["lines"]] == [240.0, 150.0]
    with pytest.raises(WorkflowError, match="must approve “Fly the hospital order; rebook the store order on ground”"):
        bookings.confirm(quote["quote_id"], 466.1, "key-00000006", OPERATOR)
    with pytest.raises(WorkflowError, match="No plan is approved yet"):
        bookings.quote("SHIP-433", None, OPERATOR)
    service.approve("SHIP-433", plan["id"], plan["source_version"], "operator")
    reused = bookings.quote("SHIP-433", None, OPERATOR)
    assert reused["quote_id"] == quote["quote_id"] and reused["approved"] is True


def test_an_executed_plan_can_still_be_booked(tmp_path):
    service, bookings = store(tmp_path)
    plan = approved(service)
    service.execute("SHIP-421", plan["id"], plan["source_version"])
    quote = bookings.quote("SHIP-421", None, OPERATOR)
    assert quote["plan_id"] == plan["id"]
    assert bookings.confirm(quote["quote_id"], 147.5, "key-00000007", OPERATOR)["plan_label"] == plan["label"]


def test_a_plan_without_paid_carriers_has_nothing_to_book(tmp_path):
    service, bookings = store(tmp_path)
    approved(service, kind="wait")
    with pytest.raises(WorkflowError, match="uses no paid carrier or service, so there is nothing to book"):
        bookings.quote("SHIP-421", None, OPERATOR)


def test_an_idempotency_key_cannot_pay_for_another_quote(tmp_path):
    service, bookings = store(tmp_path)
    approved(service)
    approved(service, "SHIP-433", "reroute")
    first = bookings.quote("SHIP-421", None, OPERATOR)
    second = bookings.quote("SHIP-433", None, OPERATOR)
    bookings.confirm(first["quote_id"], 147.5, "key-00000008", OPERATOR)
    with pytest.raises(WorkflowError, match="different quote"):
        bookings.confirm(second["quote_id"], second["total_usd"], "key-00000008", OPERATOR)


def client(tmp_path):
    app = create_app(tmp_path / "rest.sqlite3")
    return app, httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE_URL)


def test_the_rest_flow_returns_a_receipt_and_reset_forgets_bookings(tmp_path):
    async def run():
        app, http = client(tmp_path)
        async with http:
            plans = (await http.post("/incidents/SHIP-421/investigate")).json()["plans"]
            plan = plans[2]
            await http.post("/incidents/SHIP-421/approvals", json={
                "plan_id": plan["id"], "source_version": plan["source_version"], "approved_by": "operator"})
            quote = (await http.post("/incidents/SHIP-421/bookings/quote")).json()
            wrong = await http.post(f"/quotes/{quote['quote_id']}/confirm", json={"confirmed_total_usd": 147.4, "idempotency_key": "rest-key-1"})
            bad = await http.post(f"/quotes/{quote['quote_id']}/confirm", json={"confirmed_total_usd": 147.505, "idempotency_key": "rest-key-1"})
            paid = await http.post(f"/quotes/{quote['quote_id']}/confirm", json={"confirmed_total_usd": "147.50", "idempotency_key": "rest-key-1"})
            number = paid.json()["number"]
            receipt = await http.get(f"/bookings/{number}/receipt")
            incident = (await http.get("/incidents/SHIP-421")).json()
            await http.post("/demo/reset", json={"incident_id": "SHIP-421"})
            gone = await http.get(f"/bookings/{number}")
            return wrong, bad, paid, receipt, incident, gone

    wrong, bad, paid, receipt, incident, gone = asyncio.run(run())
    assert wrong.status_code == 409 and "Nothing was charged" in wrong.json()["detail"]
    assert bad.status_code == 422
    assert paid.status_code == 200 and paid.json()["total_usd"] == 147.5
    assert receipt.status_code == 200 and receipt.headers["content-type"].startswith("text/html")
    assert "default-src 'none'" in receipt.headers["content-security-policy"]
    for text in (paid.json()["number"], "$147.50", "Tax 18%", "$22.50", "Corporate card ending 4242 (simulated)"):
        assert text in receipt.text, text
    assert not PLAN_ID.search(receipt.text)
    assert [item["number"] for item in incident["bookings"]] == [paid.json()["number"]]
    assert gone.status_code == 404


def test_the_receipt_escapes_what_it_shows(tmp_path):
    from logiops.booking import receipt_html

    service, bookings = store(tmp_path)
    approved(service)
    booking = bookings.confirm(bookings.quote("SHIP-421", None, OPERATOR)["quote_id"], 147.5, "key-00000009", OPERATOR)
    page = receipt_html({**booking, "plan_label": "<script>alert(1)</script>", "booked_by": "a&b"})
    assert "<script>" not in page and "&lt;script&gt;" in page and "a&amp;b" in page


def mcp_session(tmp_path, work):
    async def run():
        app = create_app(tmp_path / "mcp.sqlite3")
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE_URL) as http:
                async with streamable_http_client(f"{BASE_URL}/mcp", http_client=http) as (read, write, _):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        return await work(session, http)
    return asyncio.run(run())


def test_mcp_books_only_an_approved_plan_and_serves_the_receipt(tmp_path):
    async def work(session, http):
        plan = (await session.call_tool("investigate_incident", {"shipment_id": "SHIP-421"})).structuredContent["plans"][2]
        quote = (await session.call_tool("quote_carrier_booking", {"shipment_id": "421", "plan_id": plan["id"]})).structuredContent
        with pytest.raises(McpError) as elicited:
            await session.call_tool("book_carrier", {"quote_id": quote["quote_id"], "confirmed_total_usd": 147.5,
                                                     "idempotency_key": "mcp-key-01"})
        await http.post("/incidents/SHIP-421/approvals", json={
            "plan_id": plan["id"], "source_version": plan["source_version"], "approved_by": "operator"})
        wrong = await session.call_tool("book_carrier", {"quote_id": quote["quote_id"], "confirmed_total_usd": 140,
                                                         "idempotency_key": "mcp-key-01"})
        booked = await session.call_tool("book_carrier", {"quote_id": quote["quote_id"], "confirmed_total_usd": 147.5,
                                                          "idempotency_key": "mcp-key-01"})
        again = await session.call_tool("book_carrier", {"quote_id": quote["quote_id"], "confirmed_total_usd": 147.5,
                                                         "idempotency_key": "mcp-key-01"})
        number = booked.structuredContent["number"]
        receipt = await session.read_resource(AnyUrl(f"receipt://logiops/{number}"))
        unknown = await session.call_tool("get_booking", {"number": "LGO-AAAAAA"})
        return quote, elicited.value.error, wrong, booked, again, receipt.contents[0], unknown

    quote, elicitation, wrong, booked, again, receipt, unknown = mcp_session(tmp_path, work)
    assert quote["approved"] is False and quote["total_usd"] == 147.5
    assert elicitation.code == -32042 and "before it can be booked" in elicitation.message
    assert "Nothing was charged" in elicitation.message and elicitation.data["elicitations"][0]["url"].endswith("/demo#SHIP-421")
    assert wrong.isError and "Nothing was charged" in wrong.content[0].text and "Next step:" in wrong.content[0].text
    assert booked.isError is False and again.structuredContent["number"] == booked.structuredContent["number"]
    assert again.structuredContent["replayed"] is True
    assert receipt.mimeType == "text/markdown" and booked.structuredContent["number"] in receipt.text
    assert "**$147.50**" in receipt.text
    assert unknown.isError and "Next step:" in unknown.content[0].text


def test_concurrent_payments_book_the_plan_once(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    service, bookings = store(tmp_path)
    approved(service)
    quote = bookings.quote("SHIP-421", None, OPERATOR)

    def pay(index):
        try:
            return bookings.confirm(quote["quote_id"], 147.5, f"race-key-{index:04d}", OPERATOR)["number"]
        except WorkflowError as exc:
            return str(exc)

    with ThreadPoolExecutor(max_workers=8) as pool:
        outcomes = list(pool.map(pay, range(8)))
    numbers = [item for item in outcomes if item.startswith("LGO-")]
    assert len(numbers) == 1 and len(bookings.for_incident("SHIP-421")) == 1
    assert all("already booked" in item for item in outcomes if not item.startswith("LGO-"))
    assert bookings.figures("SHIP-421")["dollars"] == [5.0, 22.5, 120.0, 147.5]
