from playwright.sync_api import expect


def test_commands_wait_for_the_initial_snapshot(page, replay_server, page_errors):
    held = []
    page.route("**/auth/config", lambda route: held.append(route))
    page.goto(f"{replay_server}/demo")
    expect(page.locator("#ask")).to_be_disabled()
    expect(page.locator("#ask-input")).to_have_attribute("readonly", "")
    expect(page.locator("#mic")).to_be_disabled()
    page.evaluate("""() => {
        document.querySelector('#ask-input').value = 'investigate SHIP-421';
        document.querySelector('#ask-form').dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
    }""")
    expect(page.locator("#device-heard")).not_to_have_text("investigate SHIP-421")
    held[0].continue_()
    expect(page.locator("#connection")).to_have_text("Connected")
    expect(page.locator("#ask")).to_be_enabled()
    assert page_errors == []


def fail_while(page, outage):
    """Refuse the incident list, over MCP and plain HTTP, for as long as the outage lasts."""
    def gate(route):
        if outage["on"]:
            route.abort()
        else:
            route.continue_()

    page.route("**/incidents", gate)
    page.route("**/mcp", gate)


def test_a_failed_first_load_says_so_keeps_controls_off_and_recovers_on_retry(page, replay_server, page_errors):
    outage = {"on": True}
    fail_while(page, outage)
    page.goto(f"{replay_server}/demo")
    expect(page.locator("#retry")).to_be_visible(timeout=20000)
    expect(page.locator("#connection")).to_have_text("Offline")
    expect(page.locator("#message")).to_contain_text("couldn't reach LogiOps")
    expect(page.locator("#message")).to_have_attribute("role", "alert")
    expect(page.locator("#ask")).to_be_disabled()
    expect(page.locator("#ask-input")).to_have_attribute("readonly", "")
    page.evaluate("""() => {
        document.querySelector('#ask-input').value = 'any delays today?';
        document.querySelector('#ask-form').dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
    }""")
    expect(page.locator("#message")).to_contain_text("isn't connected yet")
    expect(page.locator("#device-heard")).not_to_have_text("any delays today?")
    outage["on"] = False
    page.focus("#retry")
    page.keyboard.press("Enter")
    expect(page.locator("#connection")).to_have_text("Connected")
    expect(page.locator("#retry")).to_be_hidden()
    expect(page.locator("#ask")).to_be_enabled()
    expect(page.locator("#message")).to_have_text("Connected.")
    expect(page.locator("#ask-input")).to_be_focused()
    assert [error for error in page_errors if "ERR_FAILED" not in error] == []


def test_the_first_load_retries_by_itself_when_the_server_comes_back(page, replay_server, page_errors):
    outage = {"on": True}
    fail_while(page, outage)
    page.goto(f"{replay_server}/demo")
    expect(page.locator("#retry")).to_be_visible(timeout=20000)
    outage["on"] = False
    expect(page.locator("#connection")).to_have_text("Connected", timeout=15000)
    expect(page.locator("#ask")).to_be_enabled()
    expect(page.locator("#retry")).to_be_hidden()


def test_the_account_button_works_while_the_first_load_has_failed(page, replay_server):
    config = {"enabled": True, "client_id": "demo", "authorize_endpoint": "https://idp.example.com/oauth2/authorize", "scope": "openid"}
    page.route("**/auth/config", lambda route: route.fulfill(json=config))
    page.route("https://idp.example.com/**", lambda route: route.fulfill(content_type="text/html", body="<!doctype html><title>Sign in</title>"))
    fail_while(page, {"on": True})
    page.goto(f"{replay_server}/demo")
    expect(page.locator("#retry")).to_be_visible(timeout=20000)
    expect(page.locator("#account")).to_be_visible()
    expect(page.locator("#account")).to_be_enabled()
    expect(page.locator("#ask")).to_be_disabled()
    page.click("#account")
    page.wait_for_url("https://idp.example.com/oauth2/authorize?**")
