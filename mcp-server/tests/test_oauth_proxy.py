import base64
import hashlib
import json
import time
import urllib.parse

import pytest

import lambda_function
import oauth_proxy

PUBLIC = "https://kb-mcp.example.com"
NOTION_REDIRECT = "https://www.notion.so/mcp/oauth/callback"


class MemoryStore:
    def __init__(self):
        self.items = {}

    def put(self, key, data, ttl=None):
        exp = time.time() + ttl if ttl is not None else None
        self.items[key] = (json.loads(json.dumps(data)), exp)

    def get(self, key):
        data, exp = self.items.get(key, (None, None))
        if data is None or (exp is not None and exp < time.time()):
            return None
        return data

    def take(self, key):
        data = self.get(key)
        self.items.pop(key, None)
        return data


class FakeEntra:
    """Stands in for Entra's token endpoint and id_token verification."""

    def __init__(self):
        self.calls = []
        self.refresh_error = None

    def token(self, form):
        self.calls.append(form)
        if form["grant_type"] == "refresh_token":
            if self.refresh_error:
                raise self.refresh_error
            return {"refresh_token": "entra-rt-2"}
        return {"id_token": "fake-id-token", "refresh_token": "entra-rt-1"}

    def verify(self, id_token, nonce):
        assert id_token == "fake-id-token"
        return {"oid": "user-oid-1", "preferred_username": "jan@kernpunkt.de", "name": "Jan", "nonce": nonce}


@pytest.fixture
def secrets():
    return {"arn:entra-secret": "real-entra-secret", "arn:signing-key": "k" * 64, "arn:api-key": "legacy-key"}


@pytest.fixture
def entra(monkeypatch, secrets):
    store = MemoryStore()
    fake = FakeEntra()
    monkeypatch.setattr(oauth_proxy, "_store", store)
    monkeypatch.setattr(oauth_proxy, "_secret", lambda arn: secrets[arn])
    monkeypatch.setattr(oauth_proxy, "_entra_token", fake.token)
    monkeypatch.setattr(oauth_proxy, "_verify_id_token", fake.verify)
    monkeypatch.setattr(lambda_function, "_get_api_key", lambda: secrets["arn:api-key"])
    fake.store = store
    return fake


def call(method, path, query=None, body=None, form=None, headers=None, cookies=None):
    event = {
        "requestContext": {"http": {"method": method, "path": path}, "domainName": "x.lambda-url"},
        "rawQueryString": urllib.parse.urlencode(query or {}),
        "headers": headers or {},
        "cookies": cookies or [],
    }
    if form is not None:
        event["body"] = base64.b64encode(urllib.parse.urlencode(form).encode()).decode()
        event["isBase64Encoded"] = True
    elif body is not None:
        event["body"] = json.dumps(body)
    return lambda_function.handler(event, None)


def query_of(resp):
    return dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(resp["headers"]["Location"]).query))


def s256(verifier):
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()


def register(**overrides):
    body = {"client_name": "Notion", "redirect_uris": [NOTION_REDIRECT],
            "token_endpoint_auth_method": "none", **overrides}
    return call("POST", "/register", body=body)


def consent_page(client_id, verifier="v" * 50, state="client-state"):
    return call("GET", "/authorize", query={
        "client_id": client_id, "redirect_uri": NOTION_REDIRECT, "response_type": "code",
        "code_challenge": s256(verifier), "code_challenge_method": "S256",
        "state": state, "resource": PUBLIC})


def hidden(page, name):
    marker = f'name="{name}" value="'
    start = page["body"].index(marker) + len(marker)
    return page["body"][start:page["body"].index('"', start)]


def login(entra, verifier="v" * 50):
    """Runs register → consent → Entra → callback and returns (client_id, our code)."""
    client_id = json.loads(register()["body"])["client_id"]
    page = consent_page(client_id, verifier)
    rid, csrf = hidden(page, "rid"), hidden(page, "csrf")
    allowed = call("POST", "/authorize", form={"rid": rid, "csrf": csrf, "decision": "allow"},
                   cookies=[f"__Host-kbc-{rid}={csrf}"])
    entra_state = query_of(allowed)["state"]
    back = call("GET", "/oauth/callback", query={"code": "entra-code", "state": entra_state})
    return client_id, query_of(back)["code"]


# ── Dormant until the Entra secret is set ────────────────────────────────────

def test_dormant_with_placeholder_secret(entra, secrets):
    secrets["arn:entra-secret"] = oauth_proxy.PLACEHOLDER_SECRET
    assert register()["statusCode"] == 404
    assert call("GET", "/.well-known/oauth-authorization-server")["statusCode"] == 404
    meta = json.loads(call("GET", "/.well-known/oauth-protected-resource")["body"])
    assert meta["authorization_servers"] == ["https://login.microsoftonline.com/tenant-1/v2.0"]
    assert meta["scopes_supported"] == [f"{PUBLIC}/access_as_user"]


def test_legacy_api_key_still_works_when_dormant(entra, secrets, monkeypatch):
    secrets["arn:entra-secret"] = oauth_proxy.PLACEHOLDER_SECRET
    monkeypatch.setattr(lambda_function, "_validate_jwt", lambda t: False)
    resp = call("POST", "/", body={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                headers={"Authorization": "Bearer legacy-key"})
    assert resp["statusCode"] == 200


# ── Metadata and registration ────────────────────────────────────────────────

def test_metadata_points_to_us_when_enabled(entra):
    meta = json.loads(call("GET", "/.well-known/oauth-protected-resource")["body"])
    assert meta["authorization_servers"] == [PUBLIC]
    asm = json.loads(call("GET", "/.well-known/oauth-authorization-server")["body"])
    assert asm["issuer"] == PUBLIC
    assert asm["registration_endpoint"] == f"{PUBLIC}/register"
    assert asm["code_challenge_methods_supported"] == ["S256"]


@pytest.mark.parametrize("uri", [
    "http://evil.example.com/cb", "javascript:alert(1)", "https://x.example.com/cb#frag", "not a url",
])
def test_register_rejects_bad_redirect_uris(entra, uri):
    resp = register(redirect_uris=[uri])
    assert resp["statusCode"] == 400
    assert json.loads(resp["body"])["error"] == "invalid_redirect_uri"


@pytest.mark.parametrize("uri", ["http://localhost:3334/cb", "http://127.0.0.1/cb", "cursor://auth/cb"])
def test_register_accepts_native_redirect_uris(entra, uri):
    assert register(redirect_uris=[uri])["statusCode"] == 201


def test_register_public_client_gets_no_secret(entra):
    resp = json.loads(register()["body"])
    assert resp["token_endpoint_auth_method"] == "none"
    assert "client_secret" not in resp


# ── Consent page ─────────────────────────────────────────────────────────────

def test_consent_page_shows_redirect_host_and_escapes_name(entra):
    client_id = json.loads(register(client_name="<script>x</script>")["body"])["client_id"]
    page = consent_page(client_id)
    assert page["statusCode"] == 200
    assert "www.notion.so" in page["body"]
    assert "<script>x</script>" not in page["body"]
    assert "&lt;script&gt;" in page["body"]
    assert page["headers"]["X-Frame-Options"] == "DENY"
    assert "SameSite=Strict" in page["cookies"][0]


def test_authorize_never_redirects_to_unregistered_uri(entra):
    client_id = json.loads(register()["body"])["client_id"]
    resp = call("GET", "/authorize", query={
        "client_id": client_id, "redirect_uri": "https://evil.example.com/cb",
        "response_type": "code", "code_challenge": "x", "code_challenge_method": "S256"})
    assert resp["statusCode"] == 400
    assert "Location" not in resp["headers"]


def test_authorize_requires_pkce(entra):
    client_id = json.loads(register()["body"])["client_id"]
    resp = call("GET", "/authorize", query={
        "client_id": client_id, "redirect_uri": NOTION_REDIRECT, "response_type": "code", "state": "s"})
    assert resp["statusCode"] == 302
    assert query_of(resp)["error"] == "invalid_request"
    assert query_of(resp)["state"] == "s"


def test_consent_without_cookie_is_rejected(entra):
    """A foreign site can't submit 'allow' for a request it started itself."""
    client_id = json.loads(register()["body"])["client_id"]
    page = consent_page(client_id)
    rid, csrf = hidden(page, "rid"), hidden(page, "csrf")
    resp = call("POST", "/authorize", form={"rid": rid, "csrf": csrf, "decision": "allow"})
    assert resp["statusCode"] == 403
    assert entra.store.get(f"pending#{rid}") is not None


def test_consent_deny_returns_access_denied(entra):
    client_id = json.loads(register()["body"])["client_id"]
    page = consent_page(client_id)
    rid, csrf = hidden(page, "rid"), hidden(page, "csrf")
    resp = call("POST", "/authorize", form={"rid": rid, "csrf": csrf, "decision": "deny"},
                cookies=[f"__Host-kbc-{rid}={csrf}"])
    assert resp["headers"]["Location"].startswith(NOTION_REDIRECT)
    assert query_of(resp)["error"] == "access_denied"
    assert query_of(resp)["state"] == "client-state"


def test_consent_allow_redirects_to_entra_with_pkce(entra):
    client_id = json.loads(register()["body"])["client_id"]
    page = consent_page(client_id)
    rid, csrf = hidden(page, "rid"), hidden(page, "csrf")
    resp = call("POST", "/authorize", form={"rid": rid, "csrf": csrf, "decision": "allow"},
                cookies=[f"__Host-kbc-{rid}={csrf}"])
    loc = resp["headers"]["Location"]
    assert loc.startswith("https://login.microsoftonline.com/tenant-1/oauth2/v2.0/authorize?")
    q = query_of(resp)
    assert q["client_id"] == "entra-client-1"
    assert q["redirect_uri"] == f"{PUBLIC}/oauth/callback"
    assert q["code_challenge_method"] == "S256"
    assert "offline_access" in q["scope"]


# ── Full flow, tokens and refresh ────────────────────────────────────────────

def test_full_flow_issues_token_accepted_by_mcp_endpoint(entra):
    verifier = "v" * 50
    client_id, code = login(entra, verifier)
    assert entra.calls[0]["grant_type"] == "authorization_code"

    resp = call("POST", "/token", form={"grant_type": "authorization_code", "code": code,
                                         "client_id": client_id, "redirect_uri": NOTION_REDIRECT,
                                         "code_verifier": verifier})
    assert resp["statusCode"] == 200
    tokens = json.loads(resp["body"])
    assert tokens["token_type"] == "Bearer"

    mcp = call("POST", "/", body={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
               headers={"Authorization": f"Bearer {tokens['access_token']}"})
    assert mcp["statusCode"] == 200
    assert "retrieve_from_knowledge_bases" in mcp["body"]


def test_code_is_single_use_and_pkce_checked(entra):
    client_id, code = login(entra, "v" * 50)
    bad = call("POST", "/token", form={"grant_type": "authorization_code", "code": code,
                                        "client_id": client_id, "code_verifier": "w" * 50})
    assert json.loads(bad["body"])["error"] == "invalid_grant"
    # The failed attempt consumed the code.
    again = call("POST", "/token", form={"grant_type": "authorization_code", "code": code,
                                          "client_id": client_id, "code_verifier": "v" * 50})
    assert json.loads(again["body"])["error"] == "invalid_grant"


def test_callback_state_is_single_use(entra):
    client_id = json.loads(register()["body"])["client_id"]
    page = consent_page(client_id)
    rid, csrf = hidden(page, "rid"), hidden(page, "csrf")
    allowed = call("POST", "/authorize", form={"rid": rid, "csrf": csrf, "decision": "allow"},
                   cookies=[f"__Host-kbc-{rid}={csrf}"])
    state = query_of(allowed)["state"]
    assert call("GET", "/oauth/callback", query={"code": "c", "state": state})["statusCode"] == 302
    assert call("GET", "/oauth/callback", query={"code": "c", "state": state})["statusCode"] == 400


def _tokens(entra):
    client_id, code = login(entra, "v" * 50)
    resp = call("POST", "/token", form={"grant_type": "authorization_code", "code": code,
                                         "client_id": client_id, "code_verifier": "v" * 50})
    return client_id, json.loads(resp["body"])


def test_refresh_rotates_and_rechecks_entra(entra):
    client_id, tokens = _tokens(entra)
    resp = call("POST", "/token", form={"grant_type": "refresh_token", "client_id": client_id,
                                         "refresh_token": tokens["refresh_token"]})
    assert resp["statusCode"] == 200
    assert entra.calls[-1] == {"grant_type": "refresh_token", "refresh_token": "entra-rt-1",
                               "scope": oauth_proxy.ENTRA_SCOPES}
    reused = call("POST", "/token", form={"grant_type": "refresh_token", "client_id": client_id,
                                           "refresh_token": tokens["refresh_token"]})
    assert json.loads(reused["body"])["error"] == "invalid_grant"


def test_refresh_denied_when_entra_refuses_user(entra):
    client_id, tokens = _tokens(entra)
    entra.refresh_error = oauth_proxy.EntraError(400, "invalid_grant: user disabled")
    resp = call("POST", "/token", form={"grant_type": "refresh_token", "client_id": client_id,
                                         "refresh_token": tokens["refresh_token"]})
    assert json.loads(resp["body"])["error"] == "invalid_grant"


def test_refresh_survives_transient_entra_outage(entra):
    client_id, tokens = _tokens(entra)
    entra.refresh_error = oauth_proxy.EntraError(None, "timeout")
    form = {"grant_type": "refresh_token", "client_id": client_id, "refresh_token": tokens["refresh_token"]}
    assert call("POST", "/token", form=form)["statusCode"] == 503
    entra.refresh_error = None
    assert call("POST", "/token", form=form)["statusCode"] == 200


def test_confidential_client_must_authenticate(entra):
    reg = json.loads(register(token_endpoint_auth_method="client_secret_basic")["body"])
    resp = call("POST", "/token", form={"grant_type": "authorization_code", "code": "x",
                                         "client_id": reg["client_id"]})
    assert resp["statusCode"] == 401
    basic = base64.b64encode(f"{reg['client_id']}:{reg['client_secret']}".encode()).decode()
    resp = call("POST", "/token", form={"grant_type": "authorization_code", "code": "x"},
                headers={"Authorization": f"Basic {basic}"})
    assert json.loads(resp["body"])["error"] == "invalid_grant"  # authenticated, code just invalid


def test_expired_or_foreign_tokens_are_rejected(entra, secrets):
    import jwt
    now = int(time.time())
    claims = {"iss": PUBLIC, "aud": PUBLIC, "sub": "u", "token_use": "kb_access", "exp": now - 10}
    assert not oauth_proxy.validate_access_token(jwt.encode(claims, secrets["arn:signing-key"], "HS256"))
    claims["exp"] = now + 60
    assert not oauth_proxy.validate_access_token(jwt.encode(claims, "other-key-" * 4, "HS256"))
    assert oauth_proxy.validate_access_token(jwt.encode(claims, secrets["arn:signing-key"], "HS256"))
    assert not oauth_proxy.validate_access_token("legacy-key")
