from playwright.sync_api import expect

from tests.browser.test_device import card_lead, card_text, say_on_device


def test_unresponsive_sandbox_preserves_actionable_plans(page, replay_server, page_errors, reset_demo):
    page.clock.install()
    page.route("**/mcp-app/sandbox.html?**", lambda route: route.fulfill(status=200, content_type="text/html", body="<!doctype html><title>Unavailable</title>"))
    page.goto(f"{replay_server}/demo#SHIP-421")
    expect(page.locator("#connection")).to_have_text("Connected")
    say_on_device(page, "investigate SHIP-421")
    expect(page.locator("#plans")).to_be_visible()
    expect(page.locator("#plans .plan")).not_to_have_count(0)
    expect(page.locator("#mcp-app-frame")).to_have_count(1)
    page.clock.fast_forward(16000)
    expect(page.locator("#mcp-app .mcp-app-note")).to_contain_text("plans are listed below")
    expect(page.locator("#mcp-app-frame")).to_have_count(0)
    say_on_device(page, "approve the recommended plan")
    expect(page.locator('[data-surface="confirm"]')).to_be_visible()
    assert page_errors == []


def test_a_slow_sandbox_still_starts_the_card_and_then_replaces_the_plan_list(page, replay_server, page_errors, reset_demo):
    held = []
    page.clock.install()
    page.route("**/mcp-app/sandbox.html?**", lambda route: held.append(route))
    page.goto(f"{replay_server}/demo#SHIP-421")
    expect(page.locator("#connection")).to_have_text("Connected")
    say_on_device(page, "investigate SHIP-421")
    expect(page.locator("#mcp-app-frame")).to_have_count(1)
    expect(page.locator("#plans")).to_be_visible()
    page.clock.fast_forward(6000)
    expect(page.locator("#mcp-app-frame")).to_have_count(1)
    expect(page.locator("#mcp-app .mcp-app-note")).to_have_count(0)
    held[0].continue_()
    assert card_lead(page).startswith("pick:")
    expect(page.locator("#plans")).to_be_hidden()
    assert page_errors == []


def test_the_plan_list_stays_hidden_while_the_card_is_replaced_after_an_approval(page, replay_server, page_errors, reset_demo):
    page.goto(f"{replay_server}/demo#SHIP-421")
    expect(page.locator("#connection")).to_have_text("Connected")
    say_on_device(page, "investigate SHIP-421")
    assert card_lead(page).startswith("pick:")
    expect(page.locator("#plans")).to_be_hidden()
    page.evaluate("""() => {
        window.__planListShown = 0;
        new MutationObserver(() => { if (!document.querySelector("#plans").hidden) window.__planListShown += 1; })
            .observe(document.querySelector("#plans"), { attributes: true, attributeFilter: ["hidden"] });
    }""")
    say_on_device(page, "approve the recommended plan")
    page.click("#confirm-yes")
    expect(page.locator("#plans-state")).to_contain_text("Approved by you")
    assert card_lead(page).startswith("pick:")
    assert card_text(page, ".done-tag") == "Approved"
    expect(page.locator("#plans")).to_be_hidden()
    assert page.evaluate("window.__planListShown") == 0
    assert page_errors == []
