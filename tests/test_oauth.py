"""OAuth 2.1 with Cognito: discovery, guests that can only read, JWT checks, scopes and the token proxy."""

import asyncio
import time
from urllib.parse import parse_qs

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from logiops.api import create_app
from logiops.oauth import GUEST_POSTS, OAuthSettings
from tests.test_agent import sse_events

BASE_URL = "http://127.0.0.1:8000"
ISSUER = "https://cognito-idp.us-east-1.amazonaws.com/us-east-1_Demo123"
DOMAIN = "https://logiops-ai-test.auth.us-east-1.amazoncognito.com"
CLIENT = "democlient123"
OPERATE = f"{BASE_URL}/mcp/incidents.operate"
BOOK = f"{BASE_URL}/mcp/bookings.write"


def keypair():
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = private.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    public = jwt.algorithms.RSAAlgorithm.to_jwk(private.public_key(), as_dict=True)
    return pem, public


SIGNING, PUBLIC_JWK = keypair()
OTHER, _ = keypair()


class Jwks:
    def __init__(self):
        self.calls = 0

    def __call__(self):
        self.calls += 1
        return {"keys": [{**PUBLIC_JWK, "kid": "k1", "alg": "RS256", "use": "sig"}]}


def token(key=SIGNING, kid="k1", **claims):
    now = int(time.time())
    body = {"sub": "user-123", "iss": ISSUER, "client_id": CLIENT, "token_use": "access", "username": "judge",
            "scope": f"openid email {OPERATE} {BOOK}", "iat": now, "exp": now + 3600, **claims}
    return jwt.encode({key: value for key, value in body.items() if value is not None}, key, algorithm="RS256", headers={"kid": kid})


def settings(**overrides):
    return OAuthSettings(ISSUER, DOMAIN, (CLIENT,), fetch_jwks=overrides.pop("fetch_jwks", Jwks()), **overrides)


def run_app(tmp_path, work, oauth=None, **app_kwargs):
    async def run():
        app = create_app(tmp_path / "oauth.sqlite3", oauth=oauth or settings(), **app_kwargs)
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE_URL) as http:
                return await work(http, app)
    return asyncio.run(run())


def bearer(value):
    return {"Authorization": f"Bearer {value}"}


def rpc(name, arguments, ident=1):
    return {"jsonrpc": "2.0", "id": ident, "method": "tools/call", "params": {"name": name, "arguments": arguments}}


MCP_HEADERS = {"accept": "application/json, text/event-stream", "content-type": "application/json", "mcp-protocol-version": "2025-11-25"}


def test_discovery_documents_point_at_cognito_with_pkce(tmp_path):
    async def work(http, _app):
        return [(await http.get(path)).json() for path in (
            "/.well-known/oauth-protected-resource/mcp", "/.well-known/oauth-protected-resource",
            "/.well-known/oauth-authorization-server", "/auth/config")]

    resource, root, server, config = run_app(tmp_path, work)
    assert resource == root and resource["resource"] == f"{BASE_URL}/mcp" and resource["authorization_servers"] == [BASE_URL]
    assert resource["scopes_supported"] == [OPERATE, BOOK] and resource["bearer_methods_supported"] == ["header"]
    assert server["issuer"] == BASE_URL and server["code_challenge_methods_supported"] == ["S256"]
    assert server["authorization_endpoint"] == f"{DOMAIN}/oauth2/authorize" and server["token_endpoint"] == f"{BASE_URL}/auth/token"
    assert server["token_endpoint_auth_methods_supported"] == ["none"] and server["jwks_uri"] == f"{ISSUER}/.well-known/jwks.json"
    assert config["client_id"] == CLIENT and OPERATE in config["scope"] and config["token_endpoint"] == "/auth/token"


def test_a_guest_reads_and_is_asked_to_sign_in_for_actions(tmp_path, monkeypatch):
    monkeypatch.setenv("LOGIOPS_AGENT_MODE", "replay")

    async def work(http, _app):
        read = await http.get("/incidents/SHIP-421")
        approve = await http.post("/incidents/SHIP-421/approvals", json={"plan_id": "x", "source_version": 1, "approved_by": "g"})
        quote = await http.post("/incidents/SHIP-421/bookings/quote")
        execute = await http.post("/mcp", headers=MCP_HEADERS, json=rpc("execute_approved_plan", {"shipment_id": "SHIP-421", "plan_id": "x", "source_version": 1}))
        book = await http.post("/mcp", headers=MCP_HEADERS, json=rpc("book_carrier", {"quote_id": "Q-1", "confirmed_total_usd": 1, "idempotency_key": "abcdefgh"}))
        receipt = await http.post("/mcp", headers=MCP_HEADERS, json={"jsonrpc": "2.0", "id": 3, "method": "resources/read", "params": {"uri": "receipt://logiops/LGO-AAAAAA"}})
        investigate = await http.post("/incidents/SHIP-421/agent/investigate", json={})
        streamed = await http.post("/incidents/SHIP-421/agent/investigate/stream", json={})
        speech = await http.post("/voice/speech", json={"text": "One moment."})
        dismiss = await http.post("/alerts/SHIP-421-v9/dismiss")
        async with streamable_http_client(f"{BASE_URL}/mcp", http_client=http) as (read_stream, write, _):
            async with ClientSession(read_stream, write) as session:
                await session.initialize()
                shipment = await session.call_tool("get_shipment", {"shipment_id": "SHIP-421"})
        return read, approve, quote, execute, book, receipt, investigate, streamed, speech, dismiss, shipment

    read, approve, quote, execute, book, receipt, investigate, streamed, speech, dismiss, shipment = run_app(tmp_path, work)
    assert read.status_code == 200 and investigate.status_code == 200
    assert speech.status_code in (200, 503) and dismiss.status_code == 404, "a guest hears the replies and gets the alert card"
    assert GUEST_POSTS.fullmatch("/voice/speech") and GUEST_POSTS.fullmatch("/alerts/SHIP-421-v2/dismiss")
    assert not GUEST_POSTS.fullmatch("/alerts") and not GUEST_POSTS.fullmatch("/alerts/SHIP-421-v2/dismiss/all")
    assert streamed.status_code == 200 and streamed.headers["content-type"].startswith("text/event-stream")
    events = sse_events(streamed.text)
    assert events[-1][0] == "done" and [kind for kind, _ in events].count("step") == len(events[-1][1]["tool_trace"])
    assert not GUEST_POSTS.fullmatch("/incidents/SHIP-421/agent/investigate/stream/more")
    for response, scope in ((approve, OPERATE), (quote, BOOK), (execute, OPERATE), (book, BOOK), (receipt, OPERATE)):
        assert response.status_code == 401
        header = response.headers["www-authenticate"]
        assert header.startswith("Bearer ") and f'resource_metadata="{BASE_URL}/.well-known/oauth-protected-resource/mcp"' in header
        assert f'scope="{scope}"' in header
    assert shipment.isError is False and shipment.structuredContent["id"] == "SHIP-421"


def test_a_signed_in_user_acts_under_their_name_and_scopes(tmp_path):
    async def work(http, _app):
        plan = (await http.post("/incidents/SHIP-421/investigate")).json()["plans"][2]
        full = bearer(token())
        approved = await http.post("/incidents/SHIP-421/approvals", headers=full, json={
            "plan_id": plan["id"], "source_version": plan["source_version"], "approved_by": "judge"})
        quote = (await http.post("/incidents/SHIP-421/bookings/quote", headers=full)).json()
        narrow = bearer(token(scope=f"openid {OPERATE}"))
        refused = await http.post(f"/quotes/{quote['quote_id']}/confirm", headers=narrow,
                                  json={"confirmed_total_usd": 147.5, "idempotency_key": "user-key-1"})
        mcp_refused = await http.post("/mcp", headers={**MCP_HEADERS, **narrow}, json=rpc(
            "book_carrier", {"quote_id": quote["quote_id"], "confirmed_total_usd": 147.5, "idempotency_key": "user-key-1"}))
        paid = await http.post(f"/quotes/{quote['quote_id']}/confirm", headers=full,
                               json={"confirmed_total_usd": 147.5, "idempotency_key": "user-key-1"})
        return approved, quote, refused, mcp_refused, paid

    approved, quote, refused, mcp_refused, paid = run_app(tmp_path, work)
    assert approved.status_code == 200 and quote["quoted_by"] == "judge"
    for response in (refused, mcp_refused):
        assert response.status_code == 403 and 'error="insufficient_scope"' in response.headers["www-authenticate"]
        assert f'scope="{BOOK}"' in response.headers["www-authenticate"]
    assert paid.status_code == 200 and paid.json()["booked_by"] == "judge"


@pytest.mark.parametrize("case, value", [
    ("expired", lambda: token(exp=int(time.time()) - 120, iat=int(time.time()) - 4000)),
    ("other issuer", lambda: token(iss="https://cognito-idp.us-east-1.amazonaws.com/us-east-1_Other")),
    ("id token", lambda: token(token_use="id")),
    ("other client", lambda: token(client_id="someoneelse")),
    ("other key", lambda: token(key=OTHER)),
    ("unknown kid", lambda: token(kid="k9")),
    ("no client", lambda: token(client_id=None)),
    ("garbage", lambda: "not-a-jwt"),
])
def test_bad_tokens_are_refused_with_invalid_token(tmp_path, case, value):
    async def work(http, _app):
        return await http.get("/incidents/SHIP-421", headers=bearer(value()))

    response = run_app(tmp_path, work)
    assert response.status_code == 401, case
    assert 'error="invalid_token"' in response.headers["www-authenticate"] and "resource_metadata=" in response.headers["www-authenticate"]


def test_the_static_operator_token_still_works_and_keys_are_cached(tmp_path):
    jwks = Jwks()
    operator = "o" * 40

    async def work(http, _app):
        static = await http.post("/demo/reset", headers=bearer(operator))
        users = [await http.get("/incidents/SHIP-421", headers=bearer(token())) for _ in range(3)]
        unknown = [await http.get("/incidents/SHIP-421", headers=bearer(token(kid="k9"))) for _ in range(3)]
        return static, users, unknown

    static, users, unknown = run_app(tmp_path, work, oauth=settings(fetch_jwks=jwks), access_token=operator)
    assert static.status_code == 200 and all(item.status_code == 200 for item in users)
    assert all(item.status_code == 401 for item in unknown) and jwks.calls == 1


def test_a_public_guest_never_reaches_the_live_model(tmp_path, monkeypatch):
    monkeypatch.setenv("LOGIOPS_PUBLIC", "1")
    monkeypatch.setenv("LOGIOPS_ACCESS_TOKEN", "p" * 40)
    monkeypatch.setenv("LOGIOPS_PUBLIC_HOST", "demo.example.com")

    class Paid:
        async def converse(self, messages, system, tools, skill=None):
            raise AssertionError("a guest reached the paid model")

    async def work(http, _app):
        plain = await http.post("/incidents/SHIP-421/agent/investigate", json={})
        streamed = await http.post("/incidents/SHIP-421/agent/investigate/stream", json={})
        return plain, streamed

    response, streamed = run_app(tmp_path, work, bedrock_client=Paid())
    assert response.status_code == 200 and response.json()["mode"] == "replay" and response.json()["fallback"] == "sign_in"
    kind, done = sse_events(streamed.text)[-1]
    assert streamed.status_code == 200 and kind == "done" and done["mode"] == "replay" and done["fallback"] == "sign_in"


def test_the_token_endpoint_forwards_only_allowed_pkce_and_refresh_grants(tmp_path):
    forwarded = []

    def upstream(request):
        forwarded.append(parse_qs(request.content.decode()))
        return httpx.Response(200, json={"access_token": "a", "refresh_token": "r", "token_type": "Bearer", "expires_in": 3600})

    oauth = settings(transport=httpx.MockTransport(upstream))
    form = {"Content-Type": "application/x-www-form-urlencoded"}

    async def work(http, _app):
        code = await http.post("/auth/token", headers=form, content=(
            f"grant_type=authorization_code&client_id={CLIENT}&code=c1&redirect_uri={BASE_URL}/demo&code_verifier={'v' * 64}"))
        refresh = await http.post("/auth/token", headers=form, content=f"grant_type=refresh_token&client_id={CLIENT}&refresh_token=r1")
        stranger = await http.post("/auth/token", headers=form, content="grant_type=refresh_token&client_id=evil&refresh_token=r1")
        no_verifier = await http.post("/auth/token", headers=form, content=f"grant_type=authorization_code&client_id={CLIENT}&code=c1&redirect_uri=x")
        password = await http.post("/auth/token", headers=form, content=f"grant_type=password&client_id={CLIENT}")
        return code, refresh, stranger, no_verifier, password

    code, refresh, stranger, no_verifier, password = run_app(tmp_path, work, oauth=oauth)
    assert code.status_code == refresh.status_code == 200 and code.json()["access_token"] == "a"
    assert code.headers["cache-control"] == "no-store"
    assert forwarded[0]["code_verifier"] == ["v" * 64] and forwarded[0]["client_id"] == [CLIENT]
    assert forwarded[1] == {"grant_type": ["refresh_token"], "client_id": [CLIENT], "refresh_token": ["r1"]}
    assert stranger.status_code == no_verifier.status_code == 400 and password.json()["error"] == "unsupported_grant_type"
    assert len(forwarded) == 2


def test_without_cognito_the_page_learns_sign_in_is_off(tmp_path):
    async def run():
        app = create_app(tmp_path / "off.sqlite3", access_token="t" * 40)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE_URL) as http:
            return await http.get("/auth/config"), await http.get("/.well-known/oauth-protected-resource/mcp")

    config, metadata = asyncio.run(run())
    assert config.status_code == 200 and config.json() == {"enabled": False}
    assert metadata.status_code == 401


@pytest.mark.parametrize("issuer, domain, clients", [
    ("https://evil.example.com/pool", DOMAIN, (CLIENT,)),
    (ISSUER, "http://plain.example.com", (CLIENT,)),
    (ISSUER, DOMAIN, ()),
])
def test_settings_are_validated(issuer, domain, clients):
    with pytest.raises(RuntimeError):
        OAuthSettings(issuer, domain, clients)


def test_each_signed_in_user_keeps_their_own_preferences(tmp_path, monkeypatch):
    monkeypatch.setenv("LOGIOPS_AGENT_MODE", "replay")
    alice, bob = bearer(token(sub="alice", username="alice")), bearer(token(sub="bob", username="bob"))

    async def work(http, _app):
        await http.put("/operator/preferences", headers=alice, json={"rule": "balanced", "max_cost_usd": 250})
        mine = (await http.get("/operator/preferences", headers=alice)).json()["preferences"]
        theirs = (await http.get("/operator/preferences", headers=bob)).json()["preferences"]
        shared = (await http.get("/operator/preferences")).json()["preferences"]
        capped = (await http.post("/incidents/SHIP-433/agent/investigate", headers=alice, json={})).json()
        default = (await http.post("/incidents/SHIP-433/agent/investigate", headers=bob, json={})).json()
        incident = (await http.get("/incidents/SHIP-433", headers=alice)).json()
        await http.delete("/operator/preferences", headers=alice)
        cleared = (await http.get("/operator/preferences", headers=alice)).json()["preferences"]
        return mine, theirs, shared, capped, default, incident, cleared

    mine, theirs, shared, capped, default, incident, cleared = run_app(tmp_path, work)
    assert mine["max_cost_usd"] == 250 and theirs is None and shared is None and cleared is None
    plans = {plan["id"]: plan for plan in capped["plans"]}
    assert plans[capped["recommended_plan_id"]]["kind"] == "priority-air"
    assert {plan["id"]: plan for plan in default["plans"]}[default["recommended_plan_id"]]["kind"] == "priority-air-ground"
    assert incident["operator_preferences"]["max_cost_usd"] == 250


def test_keys_are_fetched_on_a_freshly_booted_machine(monkeypatch):
    import logiops.oauth as module

    monkeypatch.setattr(module.time, "monotonic", lambda: 5.0)
    jwks = Jwks()
    actor, scopes = settings(fetch_jwks=jwks).verify(token())
    assert actor.subject == "user-123" and OPERATE in scopes and jwks.calls == 1
