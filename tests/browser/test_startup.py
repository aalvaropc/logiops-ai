import json

import pytest
from playwright.sync_api import expect


def test_commands_wait_for_the_initial_snapshot(page, replay_server, page_errors):
    held = []
    page.route("**/incidents", lambda route: held.append(route))
    page.route("**/mcp", lambda route: held.append(route))
    page.goto(f"{replay_server}/demo")
    expect(page.locator("#ask")).to_be_disabled()
    expect(page.locator("#ask-input")).to_have_attribute("readonly", "")
    expect(page.locator("#mic")).to_be_disabled()
    page.evaluate("""() => {
        document.querySelector('#ask-input').value = 'investigate SHIP-421';
        document.querySelector('#ask-form').dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
    }""")
    expect(page.locator("#device-heard")).not_to_have_text("investigate SHIP-421")
    page.unroute("**/incidents")
    page.unroute("**/mcp")
    expect(page.locator("#connection")).to_have_text("Connected")
    expect(page.locator("#ask")).to_be_enabled()
    assert page_errors == []


def fail_while(page, outage):
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


AUTH_CONFIG = {"enabled": True, "client_id": "demo", "authorize_endpoint": "https://idp.example.com/oauth2/authorize", "scope": "openid"}


@pytest.mark.parametrize("surface", ["demo", "console"])
def test_sign_in_recovers_automatically_when_only_its_configuration_failed(page, replay_server, surface):
    calls = []

    def config(route):
        calls.append(True)
        route.fulfill(status=503, json={}) if len(calls) == 1 else route.fulfill(json=AUTH_CONFIG)

    page.route("**/auth/config", config)
    page.goto(f"{replay_server}/{surface}")
    expect(page.locator("#connection")).to_have_text("Connected")
    expect(page.locator("#account")).to_be_visible(timeout=10000)
    assert len(calls) == 2
    expect(page.locator("#auth-status")).to_be_hidden()


@pytest.mark.parametrize("surface", ["demo", "console"])
def test_a_temporary_auth_outage_preserves_the_session_and_offers_a_manual_retry(page, replay_server, surface):
    session = {"access": "test-access", "refresh": "test-refresh", "expiresAt": 9999999999999, "username": "alice"}
    page.add_init_script(f"sessionStorage.setItem('logiops-session', {json.dumps(json.dumps(session))})")
    outage = {"on": True}
    page.route("**/auth/config", lambda route: route.fulfill(status=503, json={}) if outage["on"] else route.fulfill(json=AUTH_CONFIG))
    page.goto(f"{replay_server}/{surface}")
    expect(page.locator("#connection")).to_have_text("Connected")
    expect(page.locator("#auth-status")).to_be_visible()
    assert page.evaluate("JSON.parse(sessionStorage.getItem('logiops-session'))") == session
    outage["on"] = False
    page.locator("#auth-retry").focus()
    page.keyboard.press("Enter")
    expect(page.locator("#auth-status")).to_be_hidden()
    expect(page.locator("#account")).to_contain_text("alice")
    assert page.evaluate("JSON.parse(sessionStorage.getItem('logiops-session'))") == session
    expect(page.locator("#connection")).to_have_text("Connected")
