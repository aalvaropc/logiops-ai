"""The operator console: investigate, approve, execute and pay in replay, at desktop and phone widths."""

import pytest
from playwright.sync_api import expect

from tests.browser.conftest import WIDTHS, assert_accessible, say


@pytest.mark.parametrize("width", WIDTHS)
def test_console_walkthrough(page, replay_server, page_errors, reset_demo, width):
    page.set_viewport_size({"width": width, "height": 1000})
    page.goto(f"{replay_server}/console#SHIP-421")
    expect(page.locator("#connection")).to_have_text("Connected")
    expect(page.locator("#inbox > li > button")).to_have_count(4)

    say(page, "What's happening with SHIP-421?")
    expect(page.locator("#plans input[type=radio]")).to_have_count(3)
    expect(page.locator("#approve")).to_be_enabled()

    page.click("#approve")
    expect(page.locator("#execute")).to_be_enabled()
    page.click("#execute")
    expect(page.locator("#execution-result")).to_be_visible()
    expect(page.locator("#execution-result")).to_contain_text("Verified: 20 units accounted for")
    expect(page.locator("#event-count")).to_contain_text("7 events")

    assert "Say “yes” to pay" in say(page, "book it")
    assert "Booked “Fulfill local stock and send the rest express”" in say(page, "yes")
    expect(page.locator("#booking")).to_be_visible()
    expect(page.locator("#booking")).to_contain_text("$147.50")

    assert_accessible(page)
    assert page_errors == []


def test_console_links_back_to_the_device(page, replay_server, page_errors):
    page.goto(f"{replay_server}/console")
    expect(page.locator("#connection")).to_have_text("Connected")
    page.locator("#developer summary").click()
    expect(page.locator("#developer a[href='/mcp']")).to_be_visible()
    expect(page.locator("a.page-link[href^='/demo']")).to_be_visible()
    assert page_errors == []
