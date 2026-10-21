from tests.test_oauth import bearer, run_app, token


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
