"""The operator console: investigate, approve, execute and pay in replay, at desktop and phone widths."""

import re

import pytest
from playwright.sync_api import expect

from tests.browser.conftest import WIDTHS, assert_accessible, say


@pytest.mark.parametrize("width", WIDTHS)
def test_console_walkthrough(page, replay_server, page_errors, reset_demo, width):
    page.set_viewport_size({"width": width, "height": 1000})
    page.goto(f"{replay_server}/console#SHIP-421")
    expect(page.locator("#connection")).to_have_text("Connected")
    expect(page.locator("#inbox > li > button")).to_have_count(4)
    expect(page.locator("#metrics")).to_contain_text("No plan approved yet this session")

    say(page, "What's happening with SHIP-421?")
    expect(page.locator("#plans input[type=radio]")).to_have_count(3)
    expect(page.locator("#plans-field circle.field-dot")).to_have_count(3)
    expect(page.locator("#plans-field .field-label.chosen")).to_have_text("$120")
    expect(page.locator("#approve")).to_be_enabled()

    page.click("#approve")
    expect(page.locator("#execute")).to_be_enabled()
    page.click("#execute")
    expect(page.locator("#execution-result")).to_be_visible()
    expect(page.locator("#execution-result")).to_contain_text("Verified: 20 units accounted for")
    expect(page.locator("#event-count")).to_contain_text("7 events")
    expect(page.locator("#metrics li")).to_have_count(6)

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


def test_a_scenario_pack_imported_from_the_drawer_reaches_the_device(page, fresh_replay_server, page_errors):
    from pathlib import Path

    replay_server = fresh_replay_server
    page.set_viewport_size({"width": 1440, "height": 1000})
    page.goto(f"{replay_server}/console")
    expect(page.locator("#connection")).to_have_text("Connected")
    page.locator("#developer summary").click()
    page.set_input_files("#pack-file", str(Path(__file__).resolve().parents[1] / "fixtures" / "scenario_pack.json"))
    page.click("#import-pack")
    expect(page.locator("#pack-result")).to_contain_text("Registered SHIP-470", timeout=15000)
    expect(page.locator("#inbox > li > button")).to_have_count(5)

    page.goto(f"{replay_server}/demo#SHIP-470")
    expect(page.locator("#connection")).to_have_text("Connected")
    incident = page.locator('[data-surface="incident"]')
    expect(incident.locator(".incident-id")).to_have_text("SHIP-470")
    expect(incident.locator("#device-map")).to_be_visible()
    expect(incident.locator("#device-map-caption")).to_contain_text("Investigate to see a plan's legs")
    from tests.browser.test_device import card_lead, say_on_device

    say_on_device(page, "What's happening with SHIP-470, and which plan should we choose?")
    expect(page.locator('[data-surface="plans"]')).to_be_visible()
    assert card_lead(page).startswith("pick: ")
    assert_accessible(page)
    assert page_errors == []


def test_the_console_says_who_the_server_recorded_as_approver(page, token_server, page_errors):
    page.add_init_script("sessionStorage.setItem('logiops-access-token', 't'.repeat(40))")
    page.goto(f"{token_server}/console#SHIP-421")
    expect(page.locator("#connection")).to_have_text("Connected")
    say(page, "What's happening with SHIP-421?")
    page.fill("#approver", "Maria")
    page.click("#approve")
    expect(page.locator("#execute")).to_be_enabled()
    expect(page.locator("#approver")).to_have_value("demo-operator")
    expect(page.locator("#conversation > li").last).to_contain_text("Recorded as “demo-operator”, not “Maria”")
    assert page_errors == []


def test_a_failed_switch_keeps_the_open_incident_on_the_console(page, replay_server, reset_demo):
    page.goto(f"{replay_server}/console#SHIP-421")
    expect(page.locator("#incident-id")).to_have_text("SHIP-421")
    page.route("**/incidents/SHIP-433", lambda route: route.abort())
    page.locator(".incident-card", has_text="SHIP-433").click()
    expect(page.locator("#message")).not_to_have_text("")
    expect(page).to_have_url(re.compile(r"#SHIP-421$"))
    expect(page.locator("#incident-id")).to_have_text("SHIP-421")
    expect(page.locator('.incident-card[aria-pressed="true"]')).to_contain_text("SHIP-421")



def test_a_guest_sees_link_account_but_no_sign_out(page, replay_server):
    config = {"enabled": True, "client_id": "demo", "authorize_endpoint": "https://idp.example.com/oauth2/authorize", "scope": "openid"}
    page.route("**/auth/config", lambda route: route.fulfill(json=config))
    page.goto(f"{replay_server}/console")
    expect(page.locator("#link-account")).to_be_visible()
    expect(page.locator("#sign-out")).to_be_hidden()


def test_a_file_that_is_not_json_is_explained_under_import(page, replay_server, tmp_path):
    broken = tmp_path / "pack.json"
    broken.write_text("{ not json")
    page.goto(f"{replay_server}/console")
    expect(page.locator("#connection")).to_have_text("Connected")
    page.locator("#developer summary").click()
    page.click("#import-pack")
    expect(page.locator("#pack-result")).to_contain_text("Choose a JSON scenario pack first")
    page.set_input_files("#pack-file", str(broken))
    page.click("#import-pack")
    expect(page.locator("#pack-result")).to_contain_text("That file is not JSON")


def test_without_the_token_the_console_opens_developer_and_says_where_to_paste_it(page, token_server):
    page.goto(f"{token_server}/console")
    expect(page.locator("#connection")).to_have_text("Token required")
    expect(page.locator("#developer")).to_have_attribute("open", "")
    expect(page.locator("#access-token")).to_be_focused()
    expect(page.locator("#message")).to_contain_text("open Developer")


def test_a_stock_change_on_the_console_still_reaches_the_device(page, replay_server, reset_demo):
    from tests.browser.test_device import say_on_device

    page.set_viewport_size({"width": 1440, "height": 1000})
    page.goto(f"{replay_server}/demo#SHIP-421")
    expect(page.locator("#connection")).to_have_text("Connected")
    say_on_device(page, "What's happening with SHIP-421?")
    say_on_device(page, "open SHIP-433")
    expect(page.locator('[data-surface="incident"] .incident-id')).to_have_text("SHIP-433")

    console = page.context.new_page()
    console.set_viewport_size({"width": 1440, "height": 1000})
    console.goto(f"{replay_server}/console#SHIP-421")
    expect(console.locator("#connection")).to_have_text("Connected")
    console.locator("#developer summary").click()
    console.fill("#stock-input", "11")
    console.click("#set-stock")
    expect(console.locator("#conversation")).to_contain_text("Heads up on SHIP-421", timeout=15000)

    bell = page.locator("#alerts-bell")
    expect(bell).to_contain_text("SHIP-421", timeout=20000)
    bell.click()
    expect(page.locator('[data-surface="alert"]')).to_contain_text("Heads up on SHIP-421")
    console.wait_for_timeout(6000)
    assert console.locator("#conversation").inner_text().count("Heads up on SHIP-421") == 1
