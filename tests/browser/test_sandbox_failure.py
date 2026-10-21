from playwright.sync_api import expect

from tests.browser.test_device import say_on_device


def test_unresponsive_sandbox_preserves_actionable_plans(page, replay_server, page_errors, reset_demo):
    page.route("**/mcp-app/sandbox.html?**", lambda route: route.fulfill(status=200, content_type="text/html", body="<!doctype html><title>Unavailable</title>"))
    page.goto(f"{replay_server}/demo#SHIP-421")
    expect(page.locator("#connection")).to_have_text("Connected")
    say_on_device(page, "investigate SHIP-421")
    expect(page.locator("#plans")).to_be_visible()
    expect(page.locator("#plans .plan")).not_to_have_count(0)
    expect(page.locator("#mcp-app .mcp-app-note")).to_contain_text("plans are listed below", timeout=10000)
    expect(page.locator("#mcp-app-frame")).to_have_count(0)
    say_on_device(page, "approve the recommended plan")
    expect(page.locator('[data-surface="confirm"]')).to_be_visible()
    assert page_errors == []
