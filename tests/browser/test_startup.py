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
