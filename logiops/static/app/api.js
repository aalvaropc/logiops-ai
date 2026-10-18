export const TOKEN_KEY = "logiops-access-token";
export const SESSION_KEY = "logiops-session";
export const OAUTH_KEY = "logiops-oauth";
export const SIGN_IN_PATH = "/demo";

export function createStorage(backing) {
  const store = () => backing ?? globalThis.sessionStorage;
  return {
    get(key) {
      try { return store().getItem(key); } catch (_) { return null; }
    },
    set(key, value) {
      try { if (value === null || value === undefined) store().removeItem(key); else store().setItem(key, value); } catch (_) { }
    },
    remove(key) {
      try { store().removeItem(key); } catch (_) { }
    },
    getJson(key) {
      try { return JSON.parse(store().getItem(key) || "null"); } catch (_) { return null; }
    },
  };
}

const PLAIN_ERRORS = {
  "A different plan is already approved for this version": "Another plan is already approved for this data. Say “withdraw the approval” to choose again.",
  "Plan is stale; investigate the incident again": "The data changed after these plans were calculated. Ask me what's happening to recalculate them.",
  "The exact plan and version must be approved before execution": "That plan isn't approved for the current data, so nothing ran. Approve it first.",
  "The incident has already been executed": "This incident was already executed. Say “show the result” to see what ran.",
};

export function explainError(status, detail, { authEnabled = false, signedIn = false, hasToken = false } = {}) {
  if (status === 401 && authEnabled) {
    return signedIn
      ? "Your sign-in expired. Say “link my account” to sign in again."
      : "Sign in to do that: say “link my account” or press Link account. Guests can read and ask, but not act.";
  }
  if (status === 403 && authEnabled) return "Your sign-in does not allow that action.";
  if (status === 401) {
    return hasToken
      ? "That access token was not accepted. Copy it again from the testing instructions, paste it above, and press Connect."
      : "This public demo needs the access token from the testing instructions. Paste it above and press Connect.";
  }
  if (status === 429 && /agent/i.test(detail)) {
    return "That's the agent's per-minute question limit (each answer calls a paid model). Wait a minute and ask again; the plan panel and buttons still work.";
  }
  if (status === 429) return "Too many requests in the last minute. Wait a moment and try again.";
  if (status >= 500) return "I couldn't reach the planning service just now. Try again in a moment; the plans and buttons still work.";
  return PLAIN_ERRORS[detail] || detail;
}

export function base64url(bytes) {
  return btoa(String.fromCharCode(...bytes)).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

export function tokenClaims(token) {
  try { return JSON.parse(atob(String(token).split(".")[1].replace(/-/g, "+").replace(/_/g, "/"))); } catch (_) { return {}; }
}

export function sessionFrom(body, previous, now = Date.now()) {
  const claims = tokenClaims(body.access_token);
  return {
    access: body.access_token, refresh: body.refresh_token || previous?.refresh || null,
    expiresAt: now + Number(body.expires_in || 3600) * 1000, username: String(claims.username || "you").slice(0, 80),
  };
}

export function createApi({ fetch: doFetch, storage, crypto: webCrypto, origin, credentials, onSession, onAgentCall } = {}) {
  const fetcher = (...args) => (doFetch ?? globalThis.fetch)(...args);
  const vault = storage ?? createStorage();
  const randomness = () => webCrypto ?? globalThis.crypto;
  const current = () => ({ token: "", session: null, auth: { enabled: false }, ...(credentials ? credentials() : {}) });
  const agentCall = (phase, path) => { if (onAgentCall) onAgentCall(phase, path); };

  function randomText(size) {
    const bytes = new Uint8Array(size);
    randomness().getRandomValues(bytes);
    return base64url(bytes);
  }

  function storedToken() {
    return vault.get(TOKEN_KEY) || "";
  }

  function storeToken(token) {
    vault.set(TOKEN_KEY, token || null);
  }

  function readSession() {
    return vault.getJson(SESSION_KEY);
  }

  function keepSession(session) {
    vault.set(SESSION_KEY, session ? JSON.stringify(session) : null);
    if (onSession) onSession(session);
  }

  async function tokenGrant(fields) {
    const response = await fetcher("/auth/token", {
      method: "POST", headers: { "Content-Type": "application/x-www-form-urlencoded" }, cache: "no-store",
      body: new URLSearchParams({ client_id: current().auth.client_id, ...fields }),
    });
    const body = await response.json().catch(() => ({}));
    return response.ok && body.access_token ? body : null;
  }

  async function loadAuth() {
    try {
      const response = await fetcher("/auth/config", { cache: "no-store" });
      return response.ok ? await response.json() : { enabled: false };
    } catch (_) {
      return { enabled: false };
    }
  }

  async function beginSignIn({ hash = "", returnTo = null } = {}) {
    const { auth } = current();
    if (!auth.enabled) return null;
    const verifier = randomText(48);
    const digest = await randomness().subtle.digest("SHA-256", new TextEncoder().encode(verifier));
    const nonce = randomText(24);
    try {
      vault.set(OAUTH_KEY, JSON.stringify({ verifier, state: nonce, hash, returnTo: returnTo || null }));
      if (vault.getJson(OAUTH_KEY)?.state !== nonce) return null;
    } catch (_) {
      return null;
    }
    const url = new URL(auth.authorize_endpoint);
    url.search = new URLSearchParams({
      response_type: "code", client_id: auth.client_id, redirect_uri: `${origin}${SIGN_IN_PATH}`, scope: auth.scope,
      state: nonce, code_challenge: base64url(new Uint8Array(digest)), code_challenge_method: "S256",
    }).toString();
    return url.toString();
  }

  async function finishSignIn({ search = "", hash = "" } = {}) {
    const params = new URLSearchParams(search);
    const code = params.get("code");
    const failure = params.get("error");
    if (!code && !failure) return null;
    const pending = vault.getJson(OAUTH_KEY);
    vault.remove(OAUTH_KEY);
    const outcome = { session: null, note: "", path: `${pending?.returnTo || SIGN_IN_PATH}${pending?.hash || hash}` };
    if (failure || !pending || params.get("state") !== pending.state || !current().auth.enabled) {
      outcome.note = failure
        ? "Sign-in was cancelled, so you're still a guest."
        : "That sign-in didn't match this browser's request, so I ignored it. Say “link my account” to try again.";
      return outcome;
    }
    const body = await tokenGrant({ grant_type: "authorization_code", code, redirect_uri: `${origin}${SIGN_IN_PATH}`, code_verifier: pending.verifier });
    if (!body) {
      outcome.note = "Sign-in didn't complete. Say “link my account” to try again.";
      return outcome;
    }
    outcome.session = sessionFrom(body);
    keepSession(outcome.session);
    outcome.note = `Account linked: you're signed in as ${outcome.session.username}. You can now approve, execute and book.`;
    return outcome;
  }

  async function refreshSession() {
    const { session, auth } = current();
    if (!session?.refresh || !auth.enabled) return false;
    const body = await tokenGrant({ grant_type: "refresh_token", refresh_token: session.refresh }).catch(() => null);
    keepSession(body ? sessionFrom(body, session) : null);
    return Boolean(body);
  }

  function signOut() {
    keepSession(null);
  }

  async function request(path, method = "GET", body, retried = false) {
    const { token, session, auth } = current();
    const headers = {};
    if (token) headers.Authorization = `Bearer ${token}`;
    if (body !== undefined) headers["Content-Type"] = "application/json";
    const agent = method === "POST" && /\/agent\//.test(path);
    if (agent) agentCall("request", path);
    let response;
    try {
      response = await fetcher(path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body), cache: "no-store" });
    } catch (error) {
      if (agent) agentCall("error");
      throw error;
    }
    if (agent) agentCall("done");
    if (!response.ok && response.status === 401 && !retried && session
        && /invalid_token/.test(response.headers.get("www-authenticate") || "") && await refreshSession()) {
      return request(path, method, body, true);
    }
    if (!response.ok) {
      if (agent) agentCall("error");
      let detail = `HTTP ${response.status}`;
      try { detail = (await response.json()).detail || detail; } catch (_) { }
      const text = typeof detail === "string" ? detail : detail?.message || `HTTP ${response.status}`;
      const error = new Error(explainError(response.status, text, { authEnabled: auth.enabled, signedIn: Boolean(session), hasToken: Boolean(token) }));
      error.status = response.status;
      error.detail = detail;
      throw error;
    }
    return response.json();
  }

  return { request, tokenGrant, loadAuth, beginSignIn, finishSignIn, refreshSession, signOut, readSession, keepSession, storedToken, storeToken, randomText };
}
