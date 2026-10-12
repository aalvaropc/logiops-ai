import { test } from "node:test";
import assert from "node:assert/strict";
import { webcrypto } from "node:crypto";
import { moduleUrl, memoryStorage, jsonResponse, fetchScript, jwt } from "./helpers.mjs";

const { createApi, createStorage, explainError, sessionFrom, tokenClaims, base64url, OAUTH_KEY, SESSION_KEY, TOKEN_KEY } = await import(moduleUrl("app/api.js"));

function setup({ routes = {}, token = "", session = null, auth = { enabled: false } } = {}) {
  const backing = memoryStorage();
  const storage = createStorage(backing);
  const { fetcher, calls } = fetchScript(routes);
  const state = { token, session, auth };
  const phases = [];
  const sessions = [];
  const api = createApi({
    fetch: fetcher, storage, crypto: webcrypto, origin: "http://127.0.0.1:8000",
    credentials: () => state,
    onSession: (next) => { sessions.push(next); state.session = next; state.token = next ? next.access : api.storedToken(); },
    onAgentCall: (phase) => phases.push(phase),
  });
  return { api, storage, backing, calls, state, phases, sessions };
}

test("errors are explained for guests, signed-in users and the operator token", () => {
  assert.match(explainError(401, "x", { authEnabled: true }), /Sign in to do that/);
  assert.match(explainError(401, "x", { authEnabled: true, signedIn: true }), /sign-in expired/);
  assert.match(explainError(403, "x", { authEnabled: true }), /does not allow/);
  assert.match(explainError(401, "x", { hasToken: true }), /not accepted/);
  assert.match(explainError(401, "x"), /needs the access token/);
  assert.match(explainError(429, "Agent rate limit"), /per-minute question limit/);
  assert.match(explainError(429, "MCP rate limit"), /Too many requests/);
  assert.match(explainError(502, "boom"), /couldn't reach the planning service/);
  assert.equal(explainError(409, "Nothing was charged."), "Nothing was charged.");
});

test("storage never throws and the token lives in sessionStorage only", () => {
  const broken = createStorage({ getItem() { throw new Error("blocked"); }, setItem() { throw new Error("blocked"); }, removeItem() { throw new Error("blocked"); } });
  assert.equal(broken.get("x"), null);
  broken.set("x", "1");
  broken.remove("x");
  assert.equal(broken.getJson("x"), null);
  const { api, backing } = setup();
  api.storeToken("abc");
  assert.equal(backing.getItem(TOKEN_KEY), "abc");
  assert.equal(api.storedToken(), "abc");
  api.storeToken("");
  assert.equal(backing.getItem(TOKEN_KEY), null);
});

test("sessions are built from the token claims and a refresh is kept", () => {
  const body = { access_token: jwt({ username: "judge", sub: "s" }), expires_in: 60 };
  const session = sessionFrom(body, { refresh: "r-old" }, 1000);
  assert.deepEqual(session, { access: body.access_token, refresh: "r-old", expiresAt: 61000, username: "judge" });
  assert.equal(sessionFrom({ access_token: "nope" }).username, "you");
  assert.deepEqual(tokenClaims("not-a-jwt"), {});
  assert.equal(base64url(new Uint8Array([251, 255, 254])), "-__-");
});

test("requests carry the bearer token and explain failures with the status attached", async () => {
  const { api, calls } = setup({
    token: "tok", routes: {
      "/incidents": jsonResponse(200, { incidents: [] }),
      "/incidents/SHIP-421/approvals": jsonResponse(409, { detail: "A different plan is already approved for this version" }),
    },
  });
  assert.deepEqual(await api.request("/incidents"), { incidents: [] });
  assert.equal(calls[0].init.headers.Authorization, "Bearer tok");
  assert.equal(calls[0].init.cache, "no-store");
  await assert.rejects(api.request("/incidents/SHIP-421/approvals", "POST", { plan_id: "x" }), (error) => {
    assert.equal(error.status, 409);
    assert.equal(error.message, "A different plan is already approved for this version");
    return true;
  });
  assert.equal(calls[1].init.headers["Content-Type"], "application/json");
  assert.equal(calls[1].init.body, JSON.stringify({ plan_id: "x" }));
});

test("an agent call reports its phases so the device can show thinking and errors", async () => {
  const { api, phases } = setup({ routes: {
    "/incidents/SHIP-421/agent/investigate": jsonResponse(200, { answer: "ok" }),
    "/incidents/SHIP-421/agent/ask": jsonResponse(502, { detail: "down" }),
    "/agent/briefing": () => { throw new TypeError("network"); },
  } });
  await api.request("/incidents/SHIP-421/agent/investigate", "POST", {});
  await assert.rejects(api.request("/incidents/SHIP-421/agent/ask", "POST", {}));
  await assert.rejects(api.request("/agent/briefing", "POST", {}), TypeError);
  assert.deepEqual(phases, ["request", "done", "request", "done", "error", "request", "error"]);
});

test("a 401 invalid_token refreshes the session once and retries", async () => {
  const fresh = jwt({ username: "judge" });
  let incidents = 0;
  const { api, calls, state, sessions } = setup({
    token: "stale", session: { access: "stale", refresh: "r1", username: "judge" }, auth: { enabled: true, client_id: "c1" },
    routes: {
      "/incidents": () => (++incidents === 1
        ? jsonResponse(401, { detail: "expired" }, { "www-authenticate": 'Bearer error="invalid_token", resource_metadata="x"' })
        : jsonResponse(200, { incidents: ["ok"] })),
      "/auth/token": jsonResponse(200, { access_token: fresh, expires_in: 3600 }),
    },
  });
  assert.deepEqual(await api.request("/incidents"), { incidents: ["ok"] });
  assert.equal(String(calls[1].init.body), "client_id=c1&grant_type=refresh_token&refresh_token=r1");
  assert.equal(calls[2].init.headers.Authorization, `Bearer ${fresh}`);
  assert.equal(sessions.length, 1);
  assert.equal(state.session.refresh, "r1", "the refresh token is kept when the grant returns none");
});

test("a failed refresh signs the person out and the error is not retried twice", async () => {
  const { api, sessions, calls } = setup({
    token: "stale", session: { access: "stale", refresh: "r1", username: "judge" }, auth: { enabled: true, client_id: "c1" },
    routes: {
      "/incidents": jsonResponse(401, { detail: "expired" }, { "www-authenticate": 'Bearer error="invalid_token"' }),
      "/auth/token": jsonResponse(400, { error: "invalid_grant" }),
    },
  });
  await assert.rejects(api.request("/incidents"), (error) => error.status === 401);
  assert.deepEqual(sessions, [null]);
  assert.equal(calls.length, 2);
});

test("sign-in uses PKCE S256 and a random state kept for the callback", async () => {
  const auth = { enabled: true, client_id: "c1", authorize_endpoint: "https://pool.example.com/oauth2/authorize", scope: "openid x" };
  const { api, storage } = setup({ auth });
  const url = new URL(await api.beginSignIn({ hash: "#SHIP-433" }));
  const pending = storage.getJson(OAUTH_KEY);
  assert.equal(url.origin + url.pathname, "https://pool.example.com/oauth2/authorize");
  assert.equal(url.searchParams.get("response_type"), "code");
  assert.equal(url.searchParams.get("code_challenge_method"), "S256");
  assert.equal(url.searchParams.get("redirect_uri"), "http://127.0.0.1:8000/demo");
  assert.equal(url.searchParams.get("state"), pending.state);
  assert.equal(pending.hash, "#SHIP-433");
  assert.ok(pending.verifier.length >= 43 && pending.state.length >= 24);
  const digest = await webcrypto.subtle.digest("SHA-256", new TextEncoder().encode(pending.verifier));
  assert.equal(url.searchParams.get("code_challenge"), base64url(new Uint8Array(digest)));
  assert.equal(await setup().api.beginSignIn(), null, "no sign-in without the auth config");
  const console = setup({ auth });
  await console.api.beginSignIn({ hash: "#SHIP-421", returnTo: "/console" });
  assert.equal(console.storage.getJson(OAUTH_KEY).returnTo, "/console");
});

test("the callback checks the state, exchanges the code with the verifier and cleans the path", async () => {
  const auth = { enabled: true, client_id: "c1" };
  const access = jwt({ username: "judge" });
  const { api, storage, calls, sessions } = setup({ auth, routes: { "/auth/token": jsonResponse(200, { access_token: access, refresh_token: "r1", expires_in: 3600 }) } });
  assert.equal(await api.finishSignIn({ search: "", hash: "#SHIP-421" }), null);
  storage.set(OAUTH_KEY, JSON.stringify({ verifier: "v".repeat(64), state: "nonce", hash: "#SHIP-433" }));
  const forged = await api.finishSignIn({ search: "?code=c&state=other", hash: "#SHIP-421" });
  assert.match(forged.note, /didn't match this browser's request/);
  assert.equal(forged.path, "/demo#SHIP-433");
  assert.equal(storage.get(OAUTH_KEY), null, "a used or forged callback consumes the pending entry");
  storage.set(OAUTH_KEY, JSON.stringify({ verifier: "v".repeat(64), state: "nonce", hash: "#SHIP-433" }));
  const linked = await api.finishSignIn({ search: "?code=c1&state=nonce", hash: "" });
  assert.equal(linked.session.username, "judge");
  assert.equal(linked.path, "/demo#SHIP-433");
  assert.match(linked.note, /signed in as judge/);
  assert.equal(String(calls[0].init.body), `client_id=c1&grant_type=authorization_code&code=c1&redirect_uri=http%3A%2F%2F127.0.0.1%3A8000%2Fdemo&code_verifier=${"v".repeat(64)}`);
  assert.equal(sessions[0].access, access);
  assert.equal(JSON.parse(storage.get(SESSION_KEY)).refresh, "r1");
  storage.set(OAUTH_KEY, JSON.stringify({ verifier: "v", state: "n", hash: "" }));
  assert.match((await api.finishSignIn({ search: "?error=access_denied&state=n" })).note, /cancelled/);
  storage.set(OAUTH_KEY, JSON.stringify({ verifier: "v".repeat(64), state: "nonce", hash: "#SHIP-452", returnTo: "/console" }));
  assert.equal((await api.finishSignIn({ search: "?code=c2&state=nonce" })).path, "/console#SHIP-452");
});

test("sign out drops the session and falls back to the stored operator token", async () => {
  const { api, state, backing } = setup({ token: "sess", session: { access: "sess", refresh: null, username: "judge" } });
  backing.setItem(TOKEN_KEY, "operator-token");
  api.signOut();
  assert.equal(state.session, null);
  assert.equal(state.token, "operator-token");
  assert.equal(backing.getItem(SESSION_KEY), null);
});
