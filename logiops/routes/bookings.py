"""Carrier bookings: quote, pay once, read back, receipt."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from ..booking import receipt_html
from ..identity import actor_of
from .context import Context
from .models import BookingConfirmation, QuoteRequest


def router(ctx: Context) -> APIRouter:
    bookings = ctx.bookings
    routes = APIRouter()

    @routes.post("/incidents/{incident_id}/bookings/quote")
    async def quote_booking(incident_id: str, http_request: Request, request: QuoteRequest | None = None) -> dict[str, Any]:
        """Price the paid carriers and services of a current plan (the approved one by default):
        cost, service fee and IGV 18 %, valid for ten minutes. A quote charges nothing."""
        return bookings.quote(incident_id, request.plan_id if request else None, actor_of(http_request))

    @routes.post("/quotes/{quote_id}/confirm")
    async def confirm_booking(quote_id: str, http_request: Request, request: BookingConfirmation) -> dict[str, Any]:
        """Book and pay a quote once. The confirmed total must equal the quoted total recalculated now,
        the quote must be valid, and the plan approved; the same idempotency key returns the same booking."""
        return bookings.confirm(quote_id, request.confirmed_total_usd, request.idempotency_key, actor_of(http_request))

    @routes.get("/bookings/{number}")
    async def get_booking(number: str) -> dict[str, Any]:
        return bookings.get(number)

    @routes.get("/bookings/{number}/receipt", response_class=HTMLResponse)
    async def booking_receipt(number: str) -> HTMLResponse:
        """A printable receipt."""
        return HTMLResponse(receipt_html(bookings.get(number)), headers={
            "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; "
                                       "form-action 'none'; frame-ancestors 'none'",
        })

    return routes
