"""The Alexa+ page: an investigation renders the MCP App card from the sandbox origin with the panel's pick."""

import pytest
from playwright.sync_api import expect

from tests.browser.conftest import WIDTHS, assert_accessible, say


def card_pick(page) -> str:
    """The plan the MCP App highlights, read from the sandboxed inner frame once it renders."""
    for _ in range(50):
        outer = next((frame for frame in page.frames if "/mcp-app/sandbox.html" in frame.url), None)
        inner = outer.child_frames[0] if outer and outer.child_frames else None
        if inner:
            try:
                text = inner.evaluate("""[...document.querySelectorAll(".plan.pick strong")].map((n) => n.textContent).join(" | ")""")
            except Exception:
                text = ""
            if text:
                return text
        page.wait_for_timeout(200)
    raise AssertionError("the MCP App card did not render")


@pytest.mark.parametrize("width", WIDTHS)
def test_device_shows_the_mcp_app_card(page, replay_server, page_errors, reset_demo, width):
    page.set_viewport_size({"width": width, "height": 1000})
    page.goto(f"{replay_server}/demo#SHIP-433")
    expect(page.locator("#connection")).to_have_text("Connected")

    reply = say(page, "What's happening with SHIP-433, and which plan should we choose?")
    assert "SHIP-433" in reply
    expect(page.locator("#device-spoken")).not_to_be_empty()
    expect(page.locator("#mcp-app")).to_be_visible()
    pick = card_pick(page)
    assert pick.startswith("Fly the hospital order")
    assert pick == page.locator(".plan.recommended strong").first.text_content()

    assert_accessible(page)
    assert page_errors == []
