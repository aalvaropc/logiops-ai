"""The Alexa+ device: home queue, incident, plans with the MCP App card, confirmation, result, purchase, receipt and alerts."""

import re

import pytest
from playwright.sync_api import expect

from tests.browser.conftest import REPLY_TIMEOUT_MS, WIDTHS, assert_accessible


def say_on_device(page, text: str) -> str:
    """Send one line from the device's field and return the spoken reply once the device is idle again."""
    page.fill("#ask-input", text)
    page.click("#ask")
    page.wait_for_function("""(text) => document.querySelector("#device-heard").textContent === text && !document.querySelector("#ask").disabled
                              && document.querySelector("#agent-stage").hidden""", arg=text, timeout=REPLY_TIMEOUT_MS)
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


def card_frame(page):
    """The MCP App's inner frame once its card has rendered."""
    for _ in range(50):
        outer = next((frame for frame in page.frames if "/mcp-app/sandbox.html" in frame.url), None)
        inner = outer.child_frames[0] if outer and outer.child_frames else None
        try:
            if inner and inner.evaluate("Boolean(document.querySelector('.plan'))"):
                return inner
        except Exception:
            pass
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
    expect(home.locator("h2#home-title")).to_have_text("4 open incidents")
    expect(home.locator(".incident-card")).to_have_count(4)
    expect(page).to_have_title("LogiOps AI · SHIP-433")
    expect(home.locator(".incident-card[aria-pressed]")).to_have_count(0)
    expect(page.locator("#chips .chip").nth(1)).to_have_text("What's happening with SHIP-433?")
    card = home.locator('.incident-card[data-incident="SHIP-433"]')
    page.evaluate("document.querySelector('#inbox .incident-card').dataset.marker = 'before-metrics'")
    expect(home.locator(".session-strip")).to_be_visible()
    assert page.evaluate("document.querySelector('#inbox .incident-card').dataset.marker") == "before-metrics", "metrics must not rebuild the queue"

    card.click()
    incident = page.locator('[data-surface="incident"]')
    expect(incident).to_be_visible()
    expect(incident.locator(".incident-id")).to_have_text("SHIP-433")
    expect(incident.locator("#device-map")).to_be_visible()
    expect(incident).to_contain_text("12 critical units at risk")
    expect(incident.locator(".incident-figure")).to_have_text("12 critical units at risk")

    assert "SHIP-433" in say_on_device(page, "What's happening with SHIP-433, and which plan should we choose?")
    plans = page.locator('[data-surface="plans"]')
    expect(plans).to_be_visible()
    expect(page.locator("#mcp-app")).to_be_visible()
    assert card_lead(page).startswith("pick: Fly the hospital order; rebook the store order on ground")
    assert card_text(page, ".pick .diff") == "rebook"
    assert card_text(page, ".field .dot-label.chosen") == "$390"
    expect(page.locator("#plans-state")).to_contain_text("Only you approve")
    page.locator("#chips .chip", has_text="Show the incident").click()
    expect(incident).to_be_visible()
    expect(incident.locator(".promise-list")).to_contain_text("Cusco regional hospital")
    expect(incident.locator(".incident-figure")).to_have_text("12 critical units at risk")
    expect(incident.locator(".plan-line")).to_contain_text("keeps 12 critical units on time")
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
    expect(confirm.locator("dt .track")).to_have_count(2)
    expect(confirm.locator("dt .track.late .over")).to_have_count(1)
    page.click("#confirm-yes")
    expect(page.locator("#device-spoken")).to_contain_text("Approved")
    expect(plans).to_be_visible()
    expect(page.locator("#plans-state")).to_contain_text("Approved by you")
    assert card_lead(page).startswith("pick: Fly the hospital order")
    assert card_text(page, ".done-tag") == "Approved" and card_text(page, ".plan button") == ""

    assert "executed" in say_on_device(page, "execute it")
    result = page.locator('[data-surface="result"]')
    expect(result).to_be_visible()
    expect(result).to_contain_text("Units accounted for")
    expect(result).to_contain_text("30")
    expect(result.locator(".result-figure")).to_have_text("12 critical units on time projected")
    expect(result.locator("dd .outcome.late")).to_have_text("+8 h late")
    expect(result.locator(".result-map path.trail")).to_have_count(3)
    expect(result.locator(".result-map path.trail.late")).to_have_count(1)

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
    expect(page.locator("#conversation .turn-trace[open]")).to_have_count(1)
    expect(page.locator("#conversation .turn-trace[open] .device-steps li").first).to_be_visible()
    page.click("#sheet-close")
    expect(page.locator("#sheet")).to_be_hidden()

    assert_accessible(page)
    assert page_errors == []


def test_the_plans_card_fits_a_phone_with_its_look_alike_and_its_font(page, replay_server, page_errors, reset_demo):
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto(f"{replay_server}/demo")
    expect(page.locator("#connection")).to_have_text("Connected")
    say_on_device(page, "What's happening with SHIP-433, and which plan should we choose?")
    expect(page.locator("#mcp-app")).to_be_visible()
    frame = card_frame(page)
    page.wait_for_function("""() => {
        const frame = document.querySelector("#mcp-app iframe");
        return frame && frame.getBoundingClientRect().height > 400;
    }""")
    card = frame.evaluate("""() => ({
        compact: document.body.classList.contains("compact"),
        others: document.querySelectorAll(".plans .plan").length,
        lookAlike: document.querySelector(".plans .plan .diff")?.textContent || "",
        more: document.querySelector("button.more")?.textContent || "",
        scrolls: document.documentElement.scrollHeight > innerHeight + 1,
    })""")
    assert card["compact"] and card["others"] == 1 and card["lookAlike"], card
    assert card["more"].startswith("See ") and not card["scrolls"], card
    loaded = frame.evaluate("""() => document.fonts.load('800 16px "Overpass"')
        .then((faces) => faces.length > 0 && faces.every((face) => face.status === "loaded")).catch(() => false)""")
    assert loaded, "the card must render in its own embedded font"
    assert page_errors == []


def test_the_sheet_opens_at_the_latest_turn_and_keeps_focus_inside_and_enter_keeps_the_field(page, replay_server, page_errors, reset_demo):
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto(f"{replay_server}/demo")
    expect(page.locator("#connection")).to_have_text("Connected")
    say_on_device(page, "Any delays today?")
    say_on_device(page, "What's happening with SHIP-433, and which plan should we choose?")
    assert page.evaluate("document.activeElement.id") == "ask-input"
    for line in ("show the incident", "show the plans", "show the incident", "show the plans"):
        say_on_device(page, line)
        assert page.evaluate("document.activeElement.id") == "ask-input", line

    page.click("#more")
    expect(page.locator("#sheet")).to_be_visible()
    expect(page.locator("#sheet-close")).to_be_focused()
    view = page.evaluate("""() => {
        const list = document.querySelector("#conversation");
        const last = list.lastElementChild.getBoundingClientRect();
        return { scrolled: list.scrollTop > 0, lastVisible: last.bottom <= list.getBoundingClientRect().bottom + 1, open: list.querySelectorAll(".turn-trace[open]").length };
    }""")
    assert view == {"scrolled": True, "lastVisible": True, "open": 1}, view
    outside = []
    for _ in range(15):
        page.keyboard.press("Tab")
        outside.append(page.evaluate("""() => {
            const node = document.activeElement;
            return node && node !== document.body && !node.closest("#sheet") ? node.id || node.className : null;
        }"""))
    assert [item for item in outside if item] == [], outside
    page.keyboard.press("Escape")
    expect(page.locator("#sheet")).to_be_hidden()
    expect(page.locator("#more")).to_be_focused()
    assert page.evaluate("document.querySelector('.talk').inert") is False
    assert_accessible(page)
    assert page_errors == []


@pytest.mark.parametrize("width", (320, 360))
def test_the_lifecycle_strip_reads_whole_on_narrow_phones(page, replay_server, page_errors, reset_demo, width):
    page.set_viewport_size({"width": width, "height": 740})
    page.goto(f"{replay_server}/demo#SHIP-433")
    expect(page.locator("#lifecycle")).to_be_visible()
    clipped = page.evaluate("""[...document.querySelectorAll("#lifecycle li")]
        .filter((item) => item.scrollWidth > item.clientWidth).map((item) => item.textContent)""")
    assert clipped == [], clipped
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    expect(page.locator('[data-surface="incident"] .incident-id')).to_have_css("white-space", "nowrap")
    assert page_errors == []


def test_an_approval_blocks_a_second_one_and_can_be_withdrawn(page, replay_server, page_errors, reset_demo):
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto(f"{replay_server}/demo#SHIP-421")
    expect(page.locator("#connection")).to_have_text("Connected")
    say_on_device(page, "What's happening with SHIP-421?")
    say_on_device(page, "approve the recommended plan")
    page.click("#confirm-yes")
    expect(page.locator("#plans-state")).to_contain_text("Approved by you")
    assert "already approved" in say_on_device(page, "approve the wait plan")
    expect(page.locator('[data-surface="plans"]')).to_be_visible()
    expect(page.locator("#message")).to_have_text("")

    say_on_device(page, "withdraw the approval")
    confirm = page.locator('[data-surface="confirm"]')
    expect(confirm).to_contain_text("Withdraw this approval?")
    page.keyboard.press("Escape")
    expect(page.locator("#device-spoken")).to_contain_text("stays")
    expect(page.locator('[data-surface="plans"]')).to_be_visible()

    say_on_device(page, "withdraw the approval")
    page.click("#confirm-yes")
    expect(page.locator('[data-surface="incident"]')).to_be_visible()
    expect(page.locator("#device-spoken")).to_contain_text("is withdrawn")
    expect(page.locator('#lifecycle li[aria-current="step"]')).to_have_text("Detected")
    assert_accessible(page)
    assert page_errors == []


def test_the_phone_dock_expands_its_reply_toggles_the_voice_and_keeps_the_shell_bar_whole(page, replay_server, page_errors, reset_demo):
    page.set_viewport_size({"width": 360, "height": 740})
    page.goto(f"{replay_server}/demo#SHIP-421")
    expect(page.locator("#connection")).to_have_text("Connected")
    say_on_device(page, "What's happening with SHIP-421?")
    say_on_device(page, "open SHIP-433")
    line = page.locator("#device-spoken")
    assert line.evaluate("(node) => node.scrollHeight > node.clientHeight + 1"), "a long reply starts clamped"
    line.click()
    expect(page.locator(".talk")).to_have_class(re.compile(r"\bexpanded\b"))
    assert line.evaluate("(node) => node.scrollHeight <= node.clientHeight + 1"), "a tap shows the whole reply"
    orb = page.locator("#device-orb")
    pressed = orb.get_attribute("aria-pressed")
    orb.click()
    expect(orb).not_to_have_attribute("aria-pressed", pressed)
    assert page.locator("#speak-replies").is_checked() == (pressed == "false")

    say_on_device(page, "open SHIP-433")
    expect(page.locator(".talk")).not_to_have_class(re.compile(r"\bexpanded\b"))
    changed = page.request.post(f"{replay_server}/demo/inventory", data={"incident_id": "SHIP-421", "available": 20})
    assert changed.ok, changed.text()
    expect(page.locator("#alerts-bell")).to_be_visible(timeout=20000)
    assert page.evaluate("(() => { const bar = document.querySelector('.device-bar'); return bar.scrollWidth <= bar.clientWidth; })()")
    assert page.locator(".send-label").is_hidden() and page.locator("#ask").get_attribute("aria-label") == "Send"
    assert_accessible(page)
    assert page_errors == []


def test_the_echo_show_reads_each_decision_without_scrolling(page, replay_server, page_errors, reset_demo):
    page.set_viewport_size({"width": 1280, "height": 800})
    page.goto(f"{replay_server}/demo#SHIP-433")
    expect(page.locator("#connection")).to_have_text("Connected")
    expect(page.locator("#device-bars")).to_contain_text("Cusco regional hospital · 12 units")
    expect(page.locator("#device-bars")).to_contain_text("no plan yet")
    scrolls = "(() => { const s = document.querySelector('#surface'); return s.scrollHeight > s.clientHeight + 1; })()"
    say_on_device(page, "What's happening with SHIP-433, and which plan should we choose?")
    say_on_device(page, "approve the recommended plan")
    assert not page.evaluate(scrolls), "the confirmation fits"
    page.click("#confirm-yes")
    expect(page.locator("#plans-state")).to_contain_text("Approved by you")
    say_on_device(page, "execute it")
    expect(page.locator(".result-card .times")).to_be_visible()
    columns = page.evaluate("getComputedStyle(document.querySelector('.result-card .label-split')).gridTemplateColumns.split(' ').length")
    assert columns == 2 and not page.evaluate(scrolls), "the result is a two-column label that fits"
    assert_accessible(page)
    assert page_errors == []


@pytest.mark.parametrize("size", ((320, 700), (360, 740), (960, 480)))
def test_the_yes_of_a_confirmation_is_in_reach_on_small_phones(page, replay_server, page_errors, reset_demo, size):
    page.set_viewport_size({"width": size[0], "height": size[1]})
    page.goto(f"{replay_server}/demo#SHIP-433")
    expect(page.locator("#connection")).to_have_text("Connected")
    say_on_device(page, "What's happening with SHIP-433, and which plan should we choose?")
    say_on_device(page, "approve the recommended plan")
    expect(page.locator('[data-surface="confirm"]')).to_be_visible()
    inside = page.evaluate("""() => {
        const surface = document.querySelector("#surface").getBoundingClientRect();
        return ["#confirm-yes", "#confirm-no"].map((id) => {
            const box = document.querySelector(id).getBoundingClientRect();
            return box.top >= surface.top && box.bottom <= surface.bottom + 1;
        });
    }""")
    assert inside == [True, True], inside
    page.click("#confirm-yes")
    expect(page.locator("#plans-state")).to_contain_text("Approved by you")
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


def test_a_briefing_reorders_the_queue_and_a_no_dismisses_a_confirmation(page, replay_server, page_errors, reset_demo):
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


def test_after_execution_the_queue_moves_on_and_start_over_says_what_stays(page, replay_server, page_errors, reset_demo):
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto(f"{replay_server}/demo")
    expect(page.locator("#connection")).to_have_text("Connected")
    say_on_device(page, "Any delays today?")
    home = page.locator('[data-surface="home"]')
    expect(home.locator('.incident-card[data-incident="SHIP-433"] .start-here')).to_have_text("Start here")
    say_on_device(page, "What's happening with SHIP-433, and which plan should we choose?")
    say_on_device(page, "approve the recommended plan")
    page.click("#confirm-yes")
    expect(page.locator("#plans-state")).to_contain_text("Approved by you")
    say_on_device(page, "show the incident")
    expect(page.locator('[data-surface="incident"] .band')).to_have_text("Approved · 12 critical units projected on time once executed")
    say_on_device(page, "show the plans")
    expect(page.locator("#plans-state")).to_contain_text("Nothing has run yet")
    expect(page.locator("#chips .chip.act")).to_have_text(["Execute approved plan", "Book and pay"])
    page.locator("#chips .chip", has_text="Execute approved plan").click()
    expect(page.locator('[data-surface="result"]')).to_be_visible()
    expect(page.locator('[data-surface="result"] .times')).to_be_visible()
    page.wait_for_timeout(300)
    assert page.evaluate("Boolean(document.activeElement.closest('[data-surface=\"result\"]')) && document.activeElement.tagName === 'H2'"), "focus stays on the result"
    expect(page.locator("#chips .chip", has_text="Execute approved plan")).to_have_count(0)
    next_chip = page.locator("#chips .chip", has_text="Open SHIP-")
    expect(next_chip).to_have_count(1)
    target = next_chip.inner_text().removeprefix("Open ")
    assert target != "SHIP-433"

    assert "executed plan stays" in say_on_device(page, "start over")
    expect(home).to_be_visible()
    done = home.locator('.incident-card[data-incident="SHIP-433"]')
    expect(done.locator(".executed")).to_have_text("Executed")
    expect(done.locator(".start-here")).to_have_count(0)
    expect(page.locator("#chips .chip").nth(1)).not_to_contain_text("SHIP-433")

    say_on_device(page, "show the result")
    expect(page.locator('[data-surface="result"]')).to_be_visible()
    page.locator("#chips .chip", has_text=f"Open {target}").click()
    expect(page.locator('[data-surface="incident"] .incident-id')).to_have_text(target)
    page.locator("#chips .chip", has_text="Back to queue").click()
    expect(home).to_be_visible()
    expect(home.locator("h2#home-title")).to_contain_text("open incident")
    assert "Here's your queue" in say_on_device(page, "go back")
    assert_accessible(page)
    assert page_errors == []


def test_an_alert_elsewhere_opens_as_a_card(page, replay_server, page_errors, reset_demo):
    tool_calls, reads = [], []
    page.on("request", lambda request: tool_calls.append((request.post_data_json or {}).get("params", {}).get("name"))
            if request.method == "POST" and request.url.endswith("/mcp") else None)
    page.on("request", lambda request: reads.append(request.url.removeprefix(replay_server)) if request.method == "GET" else None)
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
    expect(bell).to_be_visible(timeout=20000)
    expect(bell).to_contain_text("SHIP-421")
    bell.click()
    alert = page.locator('[data-surface="alert"]')
    expect(alert).to_be_visible()
    expect(alert).to_contain_text("Heads up on SHIP-421")
    expect(alert.locator(".was-plan")).to_contain_text("Fulfill local stock and send the rest express")
    expect(alert.locator(".new-plan")).to_contain_text("Now")
    expect(page.locator("#device-spoken")).to_contain_text("Heads up on SHIP-421")
    assert {"list_incidents", "list_alerts"} <= set(tool_calls), "the device is an MCP client: it reads its inbox and alerts with tools/call"
    assert "/incidents" not in reads and "/alerts" not in reads
    assert_accessible(page)
    assert page_errors == []


def test_the_device_reads_its_inbox_from_the_api_when_mcp_refuses(page, replay_server, reset_demo):
    page.route("**/mcp", lambda route: route.fulfill(status=429, content_type="application/json", body="{}"))
    page.goto(f"{replay_server}/demo")
    expect(page.locator("#connection")).to_have_text("Connected")
    expect(page.locator('[data-surface="home"] .incident-card')).to_have_count(4)


def test_alerts_reach_the_device_from_the_api_when_mcp_refuses_them(page, replay_server, page_errors, reset_demo):
    def refuse_alerts(route):
        if (route.request.post_data_json or {}).get("params", {}).get("name") == "list_alerts":
            route.fulfill(status=429, content_type="application/json", body="{}")
        else:
            route.continue_()

    page.route("**/mcp", refuse_alerts)
    page.set_viewport_size({"width": 1440, "height": 1000})
    page.goto(f"{replay_server}/demo#SHIP-421")
    expect(page.locator("#connection")).to_have_text("Connected")
    say_on_device(page, "What's happening with SHIP-421?")
    say_on_device(page, "open SHIP-433")
    expect(page.locator('[data-surface="incident"] .incident-id')).to_have_text("SHIP-433")
    changed = page.request.post(f"{replay_server}/demo/inventory", data={"incident_id": "SHIP-421", "available": 20})
    assert changed.ok, changed.text()
    expect(page.locator("#alerts-bell")).to_contain_text("SHIP-421", timeout=20000)
    assert [error for error in page_errors if "429" not in error] == []


def test_a_failed_switch_keeps_the_open_incident(page, replay_server, reset_demo):
    page.goto(f"{replay_server}/demo#SHIP-421")
    expect(page.locator('[data-surface="incident"] .incident-id')).to_have_text("SHIP-421")
    page.route("**/incidents/SHIP-433", lambda route: route.abort())
    page.evaluate("location.hash = '#SHIP-433'")
    expect(page.locator("#message")).not_to_have_text("")
    expect(page).to_have_url(re.compile(r"#SHIP-421$"))
    expect(page.locator('[data-surface="incident"] .incident-id')).to_have_text("SHIP-421")
    expect(page).to_have_title(re.compile("SHIP-421"))
    page.unroute("**/incidents/SHIP-433")
    say_on_device(page, "open SHIP-433")
    expect(page.locator('[data-surface="incident"] .incident-id')).to_have_text("SHIP-433")


def test_the_agent_stage_shows_the_work_before_the_answer_then_gives_way(page, replay_server, page_errors, reset_demo):
    page.goto(f"{replay_server}/demo#SHIP-433")
    expect(page.locator("#connection")).to_have_text("Connected")
    agent_posts = []
    page.on("request", lambda request: agent_posts.append(request.url) if request.method == "POST" and "/agent/" in request.url else None)
    page.fill("#ask-input", "What's happening with SHIP-433, and which plan should we choose?")
    with page.expect_response("**/agent/investigate/stream") as streamed:
        page.click("#ask")
    assert streamed.value.ok and streamed.value.headers["content-type"].startswith("text/event-stream")
    stage = page.locator("#agent-stage")
    expect(stage).to_be_visible()
    expect(page.locator("#device-spoken")).to_have_text("Asking the agent about SHIP-433…")
    assert page.evaluate("document.querySelector('#chips').inert"), "chips wait for the stage"
    expect(stage.locator(".agent-ask")).to_have_text("Asking the agent about SHIP-433")
    stations = stage.locator(".agent-stations li")
    expect(stations).to_have_count(6)
    expect(stations.first).to_have_text("Shipment · SHIP-433")
    expect(stations.last).to_have_text("Checked against the data")
    expect(stage.locator(".agent-meta")).to_have_text("Replayed from a recorded run · 5 MCP calls · scripted model")
    expect(page.locator("#device-spoken")).to_have_text("Asking the agent about SHIP-433…")
    expect(page.locator(".talk")).to_have_attribute("data-voice", "thinking")
    expect(stage).to_be_hidden(timeout=6000)
    expect(page.locator("#device-spoken")).to_contain_text("Fly the hospital order")
    assert not page.evaluate("document.querySelector('#chips').inert")
    expect(page.locator("#plans-agent")).to_have_text("5 MCP calls by the agent · Checked against the data · scripted model")
    assert [url.split("/incidents/")[-1] for url in agent_posts] == ["SHIP-433/agent/investigate/stream"], "the device streamed and never fell back"
    expect(page.locator("#plans-agent .agent-dots span")).to_have_count(6)
    assert_accessible(page)
    assert page_errors == []


SPEECH_STUB = """(() => {
  window.spokenLines = [];
  class Utterance extends EventTarget { constructor(text) { super(); this.text = text; } }
  const synth = {
    speaking: false, pending: false, getVoices: () => [], cancel() {},
    speak(utterance) { window.spokenLines.push(utterance.text); setTimeout(() => utterance.dispatchEvent(new Event("end")), 0); },
  };
  Object.defineProperty(window, "speechSynthesis", { configurable: true, get: () => synth });
  window.SpeechSynthesisUtterance = Utterance;
})();"""


def test_a_held_reply_stays_silent_once_the_voice_is_off_or_the_next_question_is_asked(page, replay_server, page_errors, reset_demo):
    page.add_init_script(SPEECH_STUB)
    page.goto(f"{replay_server}/demo#SHIP-433")
    expect(page.locator("#connection")).to_have_text("Connected")
    orb, stage = page.locator("#device-orb"), page.locator("#agent-stage")
    orb.click()
    expect(orb).to_have_attribute("aria-pressed", "true")
    say_on_device(page, "open SHIP-421")
    assert page.evaluate("window.spokenLines.length") == 1, "the voice is on and a reply is read"

    page.fill("#ask-input", "What's happening with SHIP-433, and which plan should we choose?")
    page.click("#ask")
    expect(stage).to_have_attribute("data-phase", "replay")
    orb.click()
    expect(orb).to_have_attribute("aria-pressed", "false")
    expect(stage).to_be_hidden(timeout=6000)
    expect(page.locator("#device-spoken")).to_contain_text("Fly the hospital order")
    expect(page.locator(".talk")).to_have_attribute("data-voice", "ready")

    orb.click()
    page.fill("#ask-input", "What's happening with SHIP-433, and which plan should we choose?")
    page.click("#ask")
    expect(stage).to_have_attribute("data-phase", "replay")
    reply = say_on_device(page, "What's happening with SHIP-421?")
    assert "hospital" not in reply
    page.wait_for_timeout(300)
    spoken = page.evaluate("window.spokenLines")
    assert not any("hospital" in line for line in spoken), spoken
    assert len(spoken) == 2, spoken
    assert page_errors == []


def test_a_touch_echo_show_reads_larger_type_without_scrolling(browser, replay_server, reset_demo):
    context = browser.new_context(viewport={"width": 1280, "height": 800}, has_touch=True, is_mobile=True)
    page = context.new_page()
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    try:
        page.goto(f"{replay_server}/demo#SHIP-433")
        expect(page.locator("#connection")).to_have_text("Connected")
        assert page.evaluate("matchMedia('(pointer: coarse)').matches")
        sizes = page.evaluate("""(() => { const style = getComputedStyle(document.documentElement);
            return ["--type-body", "--type-meta", "--type-tag"].map((name) => style.getPropertyValue(name).trim()); })()""")
        assert sizes == ["18px", "16px", "14px"]
        scrolls = "(() => { const s = document.querySelector('#surface'); return s.scrollHeight > s.clientHeight + 1; })()"
        say_on_device(page, "What's happening with SHIP-433, and which plan should we choose?")
        say_on_device(page, "approve the recommended plan")
        assert not page.evaluate(scrolls), "the confirmation fits"
        page.click("#confirm-yes")
        expect(page.locator("#plans-state")).to_contain_text("Approved by you")
        say_on_device(page, "execute it")
        expect(page.locator('[data-surface="result"]')).to_be_visible()
        assert not page.evaluate(scrolls), "the result fits"
        assert errors == []
    finally:
        context.close()


def test_a_refused_approve_and_pay_closes_its_card_and_charges_nothing(page, replay_server, page_errors, reset_demo):
    page.set_viewport_size({"width": 1440, "height": 1000})
    page.goto(f"{replay_server}/demo#SHIP-421")
    expect(page.locator("#connection")).to_have_text("Connected")
    say_on_device(page, "What's happening with SHIP-421?")
    say_on_device(page, "book it")
    expect(page.locator('[data-surface="confirm"]')).to_be_visible()
    page.route("**/incidents/SHIP-421/approvals", lambda route: route.fulfill(
        status=409, content_type="application/json", body='{"detail": "Plan is stale; investigate the incident again"}'))
    page.click("#confirm-yes")
    expect(page.locator('[data-surface="confirm"]')).to_be_hidden()
    expect(page.locator("#device-spoken")).to_contain_text("Nothing was approved or charged")
    assert page.evaluate("sessionStorage.getItem('logiops-pending-purchase')") is None
    assert "Nothing is waiting" in say_on_device(page, "yes")


def test_a_recheck_after_a_new_spend_cap_shows_the_new_pick_everywhere(page, replay_server, reset_demo):
    page.set_viewport_size({"width": 1440, "height": 1000})
    page.goto(f"{replay_server}/demo#SHIP-433")
    expect(page.locator("#connection")).to_have_text("Connected")
    say_on_device(page, "What's happening with SHIP-433?")
    say_on_device(page, "remember my spend cap is $250")
    say_on_device(page, "Recheck")
    say_on_device(page, "show the incident")
    incident = page.locator('[data-surface="incident"]')
    expect(incident).to_contain_text("$240")
    expect(incident).not_to_contain_text("$390")


def test_losing_the_network_says_so_in_plain_words_and_recovers(page, replay_server, reset_demo):
    page.goto(f"{replay_server}/demo#SHIP-421")
    expect(page.locator("#connection")).to_have_text("Connected")
    page.route("**/*", lambda route: route.abort())
    page.fill("#ask-input", "Any delays today?")
    page.click("#ask")
    expect(page.locator("#message")).to_contain_text("couldn't reach LogiOps")
    expect(page.locator("#message")).not_to_contain_text("Failed to fetch")
    expect(page.locator("#connection")).to_have_text("Offline")
    page.unroute("**/*")
    say_on_device(page, "show the incident")
    say_on_device(page, "Any delays today?")
    expect(page.locator("#connection")).to_have_text("Connected")


def test_a_chip_keeps_the_keyboard_focus_when_the_card_stays(page, replay_server, reset_demo):
    page.set_viewport_size({"width": 1440, "height": 1000})
    page.goto(f"{replay_server}/demo#SHIP-421")
    expect(page.locator("#connection")).to_have_text("Connected")
    say_on_device(page, "What's happening with SHIP-421?")
    chip = page.locator("#chips .chip", has_text="Why")
    chip.focus()
    page.keyboard.press("Enter")
    page.wait_for_function("() => !document.querySelector('#ask').disabled && document.querySelector('#agent-stage').hidden")
    expect(page.locator("#chips .chip").first).to_be_attached()
    page.wait_for_function("() => document.activeElement.classList.contains('chip')")


def test_plan_buttons_name_their_plan_and_the_result_map_keeps_its_legend(page, replay_server, reset_demo):
    page.route("**/mcp-app/sandbox.html*", lambda route: route.fulfill(status=404, body=""))
    page.set_viewport_size({"width": 1440, "height": 1000})
    page.goto(f"{replay_server}/demo#SHIP-421")
    expect(page.locator("#connection")).to_have_text("Connected")
    say_on_device(page, "What's happening with SHIP-421?")
    names = page.locator("#plans .plan-select").evaluate_all("(buttons) => buttons.map((button) => button.getAttribute('aria-label'))")
    assert names and all(re.match(r"^(Select|Selected): .+", name) for name in names), names
    say_on_device(page, "approve the recommended plan")
    page.click("#confirm-yes")
    expect(page.locator("#plans-state")).to_contain_text("Approved by you")
    say_on_device(page, "execute it")
    expect(page.locator(".result-map figcaption")).not_to_be_empty()


def test_a_guest_refused_on_yes_lands_on_link_account(page, replay_server, reset_demo):
    config = {"enabled": True, "client_id": "demo", "authorize_endpoint": "https://idp.example.com/oauth2/authorize", "scope": "openid"}
    page.route("**/auth/config", lambda route: route.fulfill(json=config))
    page.goto(f"{replay_server}/demo#SHIP-421")
    expect(page.locator("#connection")).to_have_text("Connected")
    say_on_device(page, "What's happening with SHIP-421?")
    say_on_device(page, "approve the recommended plan")
    page.route("**/incidents/SHIP-421/approvals", lambda route: route.fulfill(
        status=401, content_type="application/json", body='{"detail": "Sign in to do this; guests can only read."}',
        headers={"WWW-Authenticate": 'Bearer resource_metadata="x", scope="incidents.operate"'}))
    page.locator("#confirm-yes").focus()
    page.keyboard.press("Enter")
    expect(page.locator("#message")).to_contain_text("Sign in to do that")
    expect(page.locator("#account")).to_be_focused()



def test_a_large_spend_cap_is_read_back_with_a_thousands_separator(page, replay_server, reset_demo):
    page.goto(f"{replay_server}/demo#SHIP-421")
    expect(page.locator("#connection")).to_have_text("Connected")
    say_on_device(page, "What's happening with SHIP-421?")
    assert "$1,500" in say_on_device(page, "remember my spend cap is $1,500")
