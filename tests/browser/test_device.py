"""The Alexa+ device: home carousel, incident, plans with the MCP App card, confirmation, result, purchase, receipt and alerts."""

import pytest
from playwright.sync_api import expect

from tests.browser.conftest import REPLY_TIMEOUT_MS, WIDTHS, assert_accessible


def say_on_device(page, text: str) -> str:
    """Send one line from the device's field and return the spoken reply once the device is idle again."""
    page.fill("#ask-input", text)
    page.click("#ask")
    page.wait_for_function("""(text) => document.querySelector("#device-heard").textContent === text && !document.querySelector("#ask").disabled""",
                           arg=text, timeout=REPLY_TIMEOUT_MS)
    return page.locator("#device-spoken").inner_text()


def card_lead(page) -> str:
    """The first plan the MCP App shows and whether it is the pick, read from the sandboxed inner frame once it renders."""
    for _ in range(50):
        outer = next((frame for frame in page.frames if "/mcp-app/sandbox.html" in frame.url), None)
        inner = outer.child_frames[0] if outer and outer.child_frames else None
        if inner:
            try:
                text = inner.evaluate("""(() => {
                    const first = document.querySelector("#root .plan");
                    return first ? `${first.classList.contains("pick") ? "pick" : "other"}: ${first.querySelector("strong").textContent}` : "";
                })()""")
            except Exception:
                text = ""
            if text:
                return text
        page.wait_for_timeout(200)
    raise AssertionError("the MCP App card did not render")


def card_text(page, selector: str) -> str:
    """The text of the first element matching selector in the MCP App's inner frame, once the card has rendered again."""
    for _ in range(50):
        outer = next((frame for frame in page.frames if "/mcp-app/sandbox.html" in frame.url), None)
        inner = outer.child_frames[0] if outer and outer.child_frames else None
        try:
            if inner and inner.evaluate("Boolean(document.querySelector('.plan'))"):
                return inner.evaluate("(selector) => document.querySelector(selector)?.textContent || ''", selector)
        except Exception:
            pass
        page.wait_for_timeout(200)
    raise AssertionError("the MCP App card did not render")


@pytest.mark.parametrize("width", WIDTHS)
def test_device_walkthrough(page, replay_server, page_errors, reset_demo, width):
    page.set_viewport_size({"width": width, "height": 1000})
    page.goto(f"{replay_server}/demo")
    expect(page.locator("#connection")).to_have_text("Connected")
    home = page.locator('[data-surface="home"]')
    expect(home).to_be_visible()
    expect(home).to_contain_text("Hi, I'm LogiOps")
    expect(home.locator(".incident-card")).to_have_count(4)
    expect(page).to_have_title("LogiOps AI · SHIP-433")
    expect(home.locator(".incident-card[aria-pressed]")).to_have_count(0)
    expect(page.locator("#chips .chip").nth(1)).to_have_text("What's happening with SHIP-433?")
    card = home.locator('.incident-card[data-incident="SHIP-433"]')
    page.evaluate("document.querySelector('#inbox .incident-card').dataset.marker = 'before-metrics'")
    expect(home.locator(".session-strip")).to_be_visible()
    assert page.evaluate("document.querySelector('#inbox .incident-card').dataset.marker") == "before-metrics", "metrics must not rebuild the carousel"

    card.click()
    incident = page.locator('[data-surface="incident"]')
    expect(incident).to_be_visible()
    expect(incident.locator(".incident-id")).to_have_text("SHIP-433")
    expect(incident.locator("#device-map")).to_be_visible()
    expect(incident).to_contain_text("12 critical units at risk")

    assert "SHIP-433" in say_on_device(page, "What's happening with SHIP-433, and which plan should we choose?")
    plans = page.locator('[data-surface="plans"]')
    expect(plans).to_be_visible()
    expect(page.locator("#mcp-app")).to_be_visible()
    assert card_lead(page).startswith("pick: Fly the hospital order; rebook the store order on ground")
    assert card_text(page, ".pick .diff") == "rebook"
    expect(page.locator("#plans-state")).to_contain_text("Only you approve")
    page.locator("#chips .chip", has_text="Show the incident").click()
    expect(incident).to_be_visible()
    expect(incident.locator(".promise-list")).to_contain_text("Cusco regional hospital")
    page.locator("#chips .chip", has_text="Show the plans").click()
    expect(plans).to_be_visible()
    assert "didn't catch that" in say_on_device(page, "asdf qwer")
    expect(plans).to_be_visible()

    say_on_device(page, "approve the recommended plan")
    confirm = page.locator('[data-surface="confirm"]')
    expect(confirm).to_be_visible()
    expect(confirm).to_contain_text("Approve this plan?")
    expect(confirm).to_contain_text("Fly the hospital order")
    expect(confirm.locator("dd .outcome.on-time")).to_have_text("On time")
    expect(confirm.locator("dd .outcome.late")).to_have_text("+8 h late")
    page.click("#confirm-yes")
    expect(page.locator("#device-spoken")).to_contain_text("Approved")
    expect(plans).to_be_visible()
    expect(page.locator("#plans-state")).to_contain_text("Approved by you")
    assert card_lead(page).startswith("pick: Fly the hospital order")
    assert card_text(page, ".done-tag") == "Approved" and card_text(page, "button") == ""

    assert "executed" in say_on_device(page, "execute it")
    result = page.locator('[data-surface="result"]')
    expect(result).to_be_visible()
    expect(result).to_contain_text("Units accounted for")
    expect(result).to_contain_text("30")

    say_on_device(page, "book it")
    expect(confirm).to_be_visible()
    expect(confirm).to_contain_text("Pay for the booking?")
    expect(confirm).to_contain_text("Total")
    page.click("#confirm-yes")
    receipt = page.locator('[data-surface="receipt"]')
    expect(receipt).to_be_visible()
    expect(receipt).to_contain_text("Booked LGO-")
    expect(page.locator("#device-spoken")).to_contain_text("Your confirmation number is")

    page.click("#more")
    expect(page.locator("#sheet")).to_be_visible()
    assert page.locator("#conversation > li").count() >= 8
    expect(page.locator("#device-trace")).to_be_visible()
    page.click("#sheet-close")
    expect(page.locator("#sheet")).to_be_hidden()

    assert_accessible(page)
    assert page_errors == []


def test_the_device_fits_a_small_phone(page, replay_server, page_errors, reset_demo):
    page.set_viewport_size({"width": 360, "height": 740})
    page.goto(f"{replay_server}/demo")
    expect(page.locator("#connection")).to_have_text("Connected")
    say_on_device(page, "What's happening with SHIP-433, and which plan should we choose?")
    expect(page.locator('[data-surface="plans"]')).to_be_visible()
    expect(page.locator('#lifecycle li[aria-current="step"]')).to_have_text("Investigated")
    layout = page.evaluate("""(() => {
        const box = (node) => node.getBoundingClientRect();
        const controls = [...document.querySelectorAll("#device button, #device input")].filter((node) => node.offsetParent && !node.disabled);
        return {
            overflowX: document.documentElement.scrollWidth > innerWidth,
            pageScroll: document.documentElement.scrollHeight > innerHeight + 1,
            inputBottom: box(document.querySelector("#ask-input")).bottom,
            small: controls.filter((node) => box(node).height < 44).map((node) => node.id || node.className),
        };
    })()""")
    assert not layout["overflowX"] and not layout["pageScroll"], layout
    assert layout["inputBottom"] <= 740 and layout["small"] == [], layout
    assert_accessible(page)
    assert page_errors == []


def test_a_briefing_reorders_the_carousel_and_a_no_dismisses_a_confirmation(page, replay_server, page_errors, reset_demo):
    page.set_viewport_size({"width": 1440, "height": 1000})
    page.goto(f"{replay_server}/demo#SHIP-421")
    expect(page.locator("#connection")).to_have_text("Connected")
    expect(page.locator('[data-surface="incident"]')).to_be_visible()
    say_on_device(page, "Any delays today?")
    home = page.locator('[data-surface="home"]')
    expect(home).to_be_visible()
    expect(home.locator(".incident-card").first.locator(".start-here")).to_have_text("Start here")
    expect(home.locator(".incident-card").first).to_have_attribute("data-incident", "SHIP-433")

    say_on_device(page, "What's happening with SHIP-421?")
    expect(page.locator('[data-surface="plans"]')).to_be_visible()
    say_on_device(page, "approve the wait plan")
    expect(page.locator('[data-surface="confirm"]')).to_be_visible()
    page.click("#confirm-no")
    expect(page.locator("#device-spoken")).to_contain_text("nothing was approved")
    expect(page.locator('[data-surface="plans"]')).to_be_visible()
    say_on_device(page, "start over")
    expect(home).to_be_visible()
    assert page_errors == []


def test_an_alert_elsewhere_opens_as_a_card(page, replay_server, page_errors, reset_demo):
    page.set_viewport_size({"width": 1440, "height": 1000})
    page.goto(f"{replay_server}/demo#SHIP-421")
    expect(page.locator("#connection")).to_have_text("Connected")
    say_on_device(page, "What's happening with SHIP-421?")
    expect(page.locator('[data-surface="plans"]')).to_be_visible()
    say_on_device(page, "open SHIP-433")
    expect(page.locator('[data-surface="incident"] .incident-id')).to_have_text("SHIP-433")

    changed = page.request.post(f"{replay_server}/demo/inventory", data={"incident_id": "SHIP-421", "available": 20})
    assert changed.ok, changed.text()
    bell = page.locator("#alerts-bell")
    expect(bell).to_be_visible(timeout=12000)
    expect(bell).to_contain_text("SHIP-421")
    bell.click()
    alert = page.locator('[data-surface="alert"]')
    expect(alert).to_be_visible()
    expect(alert).to_contain_text("Heads up on SHIP-421")
    expect(page.locator("#device-spoken")).to_contain_text("Heads up on SHIP-421")
    assert_accessible(page)
    assert page_errors == []
