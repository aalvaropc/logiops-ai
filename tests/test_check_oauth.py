"""check_oauth.py walks the discovery chain against the app, and fails when a link is missing."""

import asyncio
from urllib.parse import parse_qs, urlparse

import httpx

from logiops.api import create_app
from logiops.oauth import OAuthSettings
from scripts.check_oauth import check

BASE_URL = "http://127.0.0.1:8000"
ISSUER = "https://cognito-idp.us-east-1.amazonaws.com/us-east-1_Demo123"
DOMAIN = "https://logiops-ai-test.auth.us-east-1.amazoncognito.com"


def run(tmp_path, oauth):
    seen = []

    def hosted(request):
        seen.append(request.url)
        return httpx.Response(200, text="<html>Sign in</html>")

    async def go():
        app = create_app(tmp_path / "check.sqlite3", oauth=oauth, access_token="o" * 40)
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE_URL) as client, \
                    httpx.AsyncClient(transport=httpx.MockTransport(hosted)) as outside:
                try:
                    return await check(client, outside, BASE_URL), seen
                except SystemExit as stop:
                    return str(stop), seen

    return asyncio.run(go())


def test_the_chain_is_walked_and_the_pkce_request_is_well_formed(tmp_path):
    lines, seen = run(tmp_path, OAuthSettings(ISSUER, DOMAIN, ("democlient123",), fetch_jwks=lambda: {"keys": []}))
    assert [line.split()[0] for line in lines] == ["PASS"] * 4
    query = parse_qs(urlparse(str(seen[0])).query)
    assert str(seen[0]).startswith(f"{DOMAIN}/oauth2/authorize?")
    assert query["code_challenge_method"] == ["S256"] and len(query["code_challenge"][0]) == 43
    assert query["client_id"] == ["democlient123"] and query["redirect_uri"] == [f"{BASE_URL}/demo"]


def test_without_oauth_the_check_fails(tmp_path):
    outcome, seen = run(tmp_path, None)
    assert outcome.startswith("FAIL  a guest's execute_approved_plan should answer 401") and not seen
