import asyncio

import httpx

from logiops.api import create_app
from tests.test_oauth import BASE_URL, bearer, run_app, token


def run_plain(tmp_path, work, base_url=BASE_URL, **app_kwargs):
    """The app without sign-in: local use, or the public deployment behind its access token."""
    async def run():
        app = create_app(tmp_path / "plain.sqlite3", **app_kwargs)
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=base_url) as http:
                return await work(http)
    return asyncio.run(run())


async def approve(http, headers=None, approved_by="someone-else", plan_index=0):
    plan = (await http.post("/incidents/SHIP-421/investigate", headers=headers)).json()["plans"][plan_index]
    return await http.post("/incidents/SHIP-421/approvals", headers=headers, json={
        "plan_id": plan["id"], "source_version": plan["source_version"], "approved_by": approved_by})


async def approval_event(http, headers=None):
    snapshot = (await http.get("/incidents/SHIP-421", headers=headers)).json()
    return [item["data"] for item in snapshot["events"] if item["name"] == "plan_approved"]


def test_approval_identity_comes_from_the_verified_actor(tmp_path):
    async def work(http, _app):
        plan = (await http.post("/incidents/SHIP-421/investigate")).json()["plans"][2]
        response = await http.post("/incidents/SHIP-421/approvals", headers=bearer(token(username="judge")), json={
            "plan_id": plan["id"], "source_version": plan["source_version"], "approved_by": "someone-else"})
        assert response.status_code == 200
        assert response.json()["approved_by"] == "judge"
        snapshot = (await http.get("/incidents/SHIP-421")).json()
        event = next(item for item in snapshot["events"] if item["name"] == "plan_approved")
        assert event["data"]["approved_subject"] == "user-123"
    run_app(tmp_path, work)


def test_operator_token_cannot_attribute_an_approval_to_someone_else(tmp_path):
    async def work(http, _app):
        headers = bearer("p" * 40)
        plan = (await http.post("/incidents/SHIP-421/investigate")).json()["plans"][0]
        response = await http.post("/incidents/SHIP-421/approvals", headers=headers, json={
            "plan_id": plan["id"], "source_version": plan["source_version"], "approved_by": "someone-else"})
        assert response.json()["approved_by"] == "demo-operator"
    run_app(tmp_path, work, access_token="p" * 40)


def test_without_sign_in_or_token_the_name_in_the_body_is_recorded_with_no_subject(tmp_path):
    async def work(http):
        response = await approve(http, approved_by="Maria")
        assert response.status_code == 200 and response.json()["approved_by"] == "Maria"
        (event,) = await approval_event(http)
        assert event["approved_by"] == "Maria" and "approved_subject" not in event
    run_plain(tmp_path, work)


def test_the_public_deployment_records_the_operator_whatever_name_the_body_carries(tmp_path, monkeypatch):
    monkeypatch.setenv("LOGIOPS_PUBLIC", "1")
    monkeypatch.setenv("LOGIOPS_PUBLIC_HOST", "demo.example.com")
    monkeypatch.delenv("LOGIOPS_COGNITO_ISSUER", raising=False)

    async def work(http):
        headers = bearer("p" * 40)
        response = await approve(http, headers, approved_by="someone-else")
        assert response.status_code == 200 and response.json()["approved_by"] == "demo-operator"
        (event,) = await approval_event(http, headers)
        assert (event["approved_by"], event["approved_subject"]) == ("demo-operator", "demo-operator")
        assert (await http.post("/incidents/SHIP-433/approvals", json={
            "plan_id": "x", "source_version": 1, "approved_by": "intruder"})).status_code == 401
    run_plain(tmp_path, work, base_url="https://demo.example.com", access_token="p" * 40)


def test_a_second_person_approving_the_same_plan_is_told_who_is_on_record(tmp_path):
    async def work(http, _app):
        first = bearer(token(username="judge"))
        second = bearer(token(username="auditor", sub="user-456"))
        plan = (await http.post("/incidents/SHIP-421/investigate")).json()["plans"][0]
        body = {"plan_id": plan["id"], "source_version": plan["source_version"], "approved_by": "auditor"}
        assert (await http.post("/incidents/SHIP-421/approvals", headers=first, json=body)).json()["approved_by"] == "judge"
        again = await http.post("/incidents/SHIP-421/approvals", headers=second, json=body)
        assert again.status_code == 200 and again.json()["approved_by"] == "judge"
        events = [item["data"] for item in (await http.get("/incidents/SHIP-421")).json()["events"] if item["name"] == "plan_approved"]
        assert [(item["approved_by"], item["approved_subject"]) for item in events] == [("judge", "user-123")]
    run_app(tmp_path, work)


def test_a_long_sign_in_name_still_approves_and_the_subject_keeps_the_exact_identity(tmp_path):
    async def work(http, _app):
        response = await approve(http, bearer(token(username="x" * 120)))
        assert response.status_code == 200 and response.json()["approved_by"] == "x" * 80
        (event,) = await approval_event(http)
        assert event["approved_subject"] == "user-123"
    run_app(tmp_path, work)
