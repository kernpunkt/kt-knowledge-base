"""OAuth 2.1 authorization server in front of Entra ID.

Entra has no Dynamic Client Registration, so MCP clients that rely on it (Notion, …)
cannot connect to Entra directly. This module makes the MCP server its own
authorization server for MCP clients, while being a single confidential client
towards Entra:

    client ──/register──► us             (DCR, RFC 7591)
    client ──/authorize─► consent page ──► Entra login ──/oauth/callback──► us
    client ◄── our code ── us
    client ──/token─────► our access + refresh tokens

The user still authenticates at Entra (kernpunkt tenant, MFA, Conditional Access).
Clients never see Entra tokens; the Entra refresh token stays server-side and is
redeemed on every refresh, so disabled accounts lose access within one access-token
lifetime.

The proxy is dormant until the Entra client secret is set in Secrets Manager (the
stack creates it with a placeholder value). Until then every route returns 404 and
the protected-resource metadata keeps pointing at Entra directly.
"""
import base64
import hashlib
import hmac
import html
import json
import os
import secrets as pysecrets
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request

import boto3

PUBLIC_URL = os.environ.get("MCP_PUBLIC_URL", "").rstrip("/")
ENTRA_TENANT_ID = os.environ.get("ENTRA_TENANT_ID", "")
ENTRA_CLIENT_ID = os.environ.get("ENTRA_CLIENT_ID", "")
TABLE_NAME = os.environ.get("OAUTH_TABLE_NAME", "")
CLIENT_SECRET_ARN = os.environ.get("ENTRA_CLIENT_SECRET_ARN", "")
SIGNING_KEY_ARN = os.environ.get("OAUTH_SIGNING_KEY_SECRET_ARN", "")

# Value the stack puts into the Entra client secret; replaced by hand after the
# redirect URI and secret have been created in the Entra app registration.
PLACEHOLDER_SECRET = "CHANGE_ME"

ENTRA_BASE = f"https://login.microsoftonline.com/{ENTRA_TENANT_ID}"
ENTRA_AUTHORIZE_URL = f"{ENTRA_BASE}/oauth2/v2.0/authorize"
ENTRA_TOKEN_URL = f"{ENTRA_BASE}/oauth2/v2.0/token"
ENTRA_ISSUER = f"{ENTRA_BASE}/v2.0"
ENTRA_JWKS_URL = f"{ENTRA_BASE}/discovery/v2.0/keys"
# Only identity + a refresh token: we never call an API with Entra's access token.
ENTRA_SCOPES = "openid profile email offline_access"
CALLBACK_PATH = "/oauth/callback"

SCOPE = "kb.read"
TOKEN_USE = "kb_access"
ACCESS_TOKEN_TTL = 3600
REFRESH_TOKEN_TTL = 30 * 86400
CODE_TTL = 300
PENDING_TTL = 600
SECRET_CACHE_TTL = 300

AUTH_METHODS = ("none", "client_secret_post", "client_secret_basic")
# Never valid as redirect target, even for native apps with private-use schemes.
FORBIDDEN_SCHEMES = {"javascript", "data", "file", "vbscript", "blob", "about"}
LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}


# ── Secrets and storage ──────────────────────────────────────────────────────

_secret_cache = {}


def _secret(arn):
    # Short TTL so a secret set by hand activates the proxy without a redeploy.
    hit = _secret_cache.get(arn)
    if hit and hit[1] > time.time():
        return hit[0]
    sm = boto3.client("secretsmanager")
    value = sm.get_secret_value(SecretId=arn)["SecretString"]
    _secret_cache[arn] = (value, time.time() + SECRET_CACHE_TTL)
    return value


class DynamoStore:
    """Key/value store with expiry; `take` is an atomic read-and-delete for single-use items."""

    def __init__(self, table_name):
        self._table = boto3.resource("dynamodb").Table(table_name)

    def put(self, key, data, ttl=None):
        item = {"pk": key, "data": json.dumps(data)}
        if ttl is not None:
            item["ttl"] = int(time.time()) + ttl
        self._table.put_item(Item=item)

    def get(self, key):
        return self._live(self._table.get_item(Key={"pk": key}).get("Item"))

    def take(self, key):
        from botocore.exceptions import ClientError
        try:
            resp = self._table.delete_item(
                Key={"pk": key},
                ConditionExpression="attribute_exists(pk)",
                ReturnValues="ALL_OLD",
            )
        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                return None
            raise
        return self._live(resp.get("Attributes"))

    @staticmethod
    def _live(item):
        # DynamoDB TTL deletes lazily (up to days later), so check expiry ourselves.
        if not item or ("ttl" in item and int(item["ttl"]) < time.time()):
            return None
        return json.loads(item["data"])


_store = None


def _get_store():
    global _store
    if _store is None:
        _store = DynamoStore(TABLE_NAME)
    return _store


_jwks_client = None


def _get_jwks_client():
    global _jwks_client
    if _jwks_client is None:
        from jwt import PyJWKClient
        _jwks_client = PyJWKClient(ENTRA_JWKS_URL, cache_keys=True)
    return _jwks_client


def enabled():
    if not all((PUBLIC_URL, ENTRA_TENANT_ID, ENTRA_CLIENT_ID, TABLE_NAME,
                CLIENT_SECRET_ARN, SIGNING_KEY_ARN)):
        return False
    try:
        return _secret(CLIENT_SECRET_ARN).strip() not in ("", PLACEHOLDER_SECRET)
    except Exception as e:
        print(f"[oauth] cannot read Entra client secret: {e!r}")
        return False


# ── Small helpers ────────────────────────────────────────────────────────────

def _token(nbytes=32):
    return pysecrets.token_urlsafe(nbytes)


def _hash(value):
    return hashlib.sha256(value.encode()).hexdigest()


def _s256(verifier):
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def _eq(a, b):
    return hmac.compare_digest(str(a), str(b))


def _body(event):
    body = event.get("body") or ""
    if event.get("isBase64Encoded"):
        body = base64.b64decode(body).decode()
    return body


def _params(event):
    return dict(urllib.parse.parse_qsl(event.get("rawQueryString") or "", keep_blank_values=True))


def _form(event):
    return dict(urllib.parse.parse_qsl(_body(event), keep_blank_values=True))


def _headers(event):
    return {k.lower(): v for k, v in (event.get("headers") or {}).items()}


def _cookies(event):
    raw = list(event.get("cookies") or [])
    if "cookie" in _headers(event):
        raw += _headers(event)["cookie"].split(";")
    jar = {}
    for c in raw:
        name, _, value = c.strip().partition("=")
        jar[name] = value
    return jar


def _with_query(url, params):
    parts = urllib.parse.urlsplit(url)
    query = urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
    query += [(k, v) for k, v in params.items() if v is not None]
    return urllib.parse.urlunsplit(parts._replace(query=urllib.parse.urlencode(query)))


def _json(status, obj, headers=None):
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json", "Cache-Control": "no-store",
                    "Pragma": "no-cache", **(headers or {})},
        "body": json.dumps(obj),
    }


def _oauth_error(status, error, description=None):
    obj = {"error": error}
    if description:
        obj["error_description"] = description
    return _json(status, obj)


def _redirect(url, cookies=None):
    resp = {"statusCode": 302, "headers": {"Location": url, "Cache-Control": "no-store"}, "body": ""}
    if cookies:
        resp["cookies"] = cookies
    return resp


def _valid_redirect_uri(uri):
    try:
        parts = urllib.parse.urlsplit(uri)
    except ValueError:
        return False
    scheme = parts.scheme.lower()
    if not scheme or scheme in FORBIDDEN_SCHEMES or parts.fragment:
        return False
    if scheme == "https":
        return bool(parts.hostname)
    if scheme == "http":
        return parts.hostname in LOOPBACK_HOSTS
    # Private-use scheme of a native app (e.g. cursor://…). Shown on the consent page.
    return True


# ── HTML ─────────────────────────────────────────────────────────────────────

_PAGE = """<!doctype html>
<html lang="de"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
:root {{ --bg:#f6f6f4; --card:#fff; --fg:#1c1c1a; --muted:#66655f; --line:#e2e1dc;
        --accent:#0b5cad; --accent-fg:#fff; --warn-bg:#fff6dc; --warn-line:#e7c55a; }}
@media (prefers-color-scheme: dark) {{
  :root {{ --bg:#161615; --card:#21211f; --fg:#ecebe6; --muted:#a3a29b; --line:#3a3936;
          --accent:#5aa2ef; --accent-fg:#0d1b2a; --warn-bg:#3a3216; --warn-line:#8a7428; }}
}}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--bg); color:var(--fg);
        font:16px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
main {{ max-width:520px; margin:48px auto; padding:0 16px; }}
.card {{ background:var(--card); border:1px solid var(--line); border-radius:12px; padding:28px; }}
h1 {{ font-size:1.3rem; margin:0 0 12px; }}
p {{ margin:0 0 14px; }}
.muted {{ color:var(--muted); font-size:.9rem; }}
dl {{ margin:18px 0; display:grid; grid-template-columns:auto 1fr; gap:6px 14px; }}
dt {{ color:var(--muted); }}
dd {{ margin:0; overflow-wrap:anywhere; }}
.host {{ font-size:1.15rem; font-weight:600; }}
.warn {{ background:var(--warn-bg); border:1px solid var(--warn-line); border-radius:8px;
         padding:12px 14px; margin:18px 0; font-size:.95rem; }}
.actions {{ display:flex; gap:10px; margin-top:22px; }}
button {{ font:inherit; padding:10px 18px; border-radius:8px; border:1px solid var(--line);
          background:transparent; color:var(--fg); cursor:pointer; }}
button.primary {{ background:var(--accent); border-color:var(--accent); color:var(--accent-fg); }}
</style></head>
<body><main><div class="card">{content}</div></main></body></html>"""


def _html(status, title, content, cookies=None):
    resp = {
        "statusCode": status,
        "headers": {
            "Content-Type": "text/html; charset=utf-8",
            "Cache-Control": "no-store",
            "X-Frame-Options": "DENY",
            "Content-Security-Policy":
                "default-src 'none'; style-src 'unsafe-inline'; frame-ancestors 'none'; base-uri 'none'",
            "Referrer-Policy": "no-referrer",
        },
        "body": _PAGE.format(title=html.escape(title), content=content),
    }
    if cookies:
        resp["cookies"] = cookies
    return resp


def _error_page(status, message):
    content = (f"<h1>Verbindung nicht möglich</h1><p>{html.escape(message)}</p>"
               "<p class=\"muted\">Starte die Verbindung in deiner Anwendung neu.</p>")
    return _html(status, "Fehler – kernpunkt Knowledge Base", content)


def _redirect_label(uri):
    parts = urllib.parse.urlsplit(uri)
    if parts.scheme in ("http", "https"):
        if parts.hostname in LOOPBACK_HOSTS:
            return "eine Anwendung auf deinem Rechner (localhost)"
        return parts.hostname
    return f"die App „{parts.scheme}“ auf deinem Rechner"


def _consent_page(client, redirect_uri, rid, csrf):
    e = html.escape
    content = f"""
<h1>Zugriff auf die kernpunkt Knowledge Base</h1>
<p>Eine Anwendung möchte in deinem Namen in der Knowledge Base suchen und Dokumente lesen.</p>
<dl>
  <dt>Antwort geht an</dt><dd class="host">{e(_redirect_label(redirect_uri))}</dd>
  <dt>Adresse</dt><dd class="muted">{e(redirect_uri)}</dd>
  <dt>Name laut App</dt><dd>{e(client["client_name"])}</dd>
</dl>
<div class="warn">Erlaube den Zugriff nur, wenn du die Verbindung gerade selbst gestartet hast
und du die Adresse oben kennst, z.&nbsp;B. <b>notion.so</b> oder <b>claude.ai</b>.
Den Namen kann sich jede Anwendung selbst geben.</div>
<form method="post" action="/authorize">
  <input type="hidden" name="rid" value="{e(rid)}">
  <input type="hidden" name="csrf" value="{e(csrf)}">
  <div class="actions">
    <button class="primary" type="submit" name="decision" value="allow">Zulassen</button>
    <button type="submit" name="decision" value="deny">Ablehnen</button>
  </div>
</form>
<p class="muted" style="margin-top:18px">Danach meldest du dich mit deinem kernpunkt-Microsoft-Konto an.</p>"""
    return _html(200, "Zugriff erlauben – kernpunkt Knowledge Base", content)


# ── Entra ────────────────────────────────────────────────────────────────────

class EntraError(Exception):
    def __init__(self, status, detail):
        super().__init__(f"Entra token endpoint: {status} {detail}")
        self.status = status


def _entra_token(form):
    data = {**form, "client_id": ENTRA_CLIENT_ID, "client_secret": _secret(CLIENT_SECRET_ARN)}
    req = urllib.request.Request(
        ENTRA_TOKEN_URL,
        data=urllib.parse.urlencode(data).encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        try:
            err = json.load(e)
            detail = f"{err.get('error')}: {err.get('error_description', '')[:200]}"
        except Exception:
            detail = "unparseable error body"
        raise EntraError(e.code, detail)
    except urllib.error.URLError as e:
        raise EntraError(None, repr(e.reason))


def _verify_id_token(id_token, nonce):
    from jwt import decode as jwt_decode
    key = _get_jwks_client().get_signing_key_from_jwt(id_token).key
    claims = jwt_decode(id_token, key, algorithms=["RS256"],
                        audience=ENTRA_CLIENT_ID, issuer=ENTRA_ISSUER)
    if not _eq(claims.get("nonce", ""), nonce):
        raise ValueError("id_token nonce mismatch")
    if not claims.get("oid"):
        raise ValueError("id_token without oid")
    return claims


# ── Endpoints ────────────────────────────────────────────────────────────────

def metadata(event):
    return _json(200, {
        "issuer": PUBLIC_URL,
        "authorization_endpoint": f"{PUBLIC_URL}/authorize",
        "token_endpoint": f"{PUBLIC_URL}/token",
        "registration_endpoint": f"{PUBLIC_URL}/register",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": list(AUTH_METHODS),
        "scopes_supported": [SCOPE],
    })


def register(event):
    try:
        req = json.loads(_body(event) or "{}")
    except ValueError:
        req = None
    if not isinstance(req, dict):
        return _oauth_error(400, "invalid_client_metadata", "body must be a JSON object")

    uris = req.get("redirect_uris")
    if (not isinstance(uris, list) or not 1 <= len(uris) <= 10
            or not all(isinstance(u, str) and _valid_redirect_uri(u) for u in uris)):
        return _oauth_error(400, "invalid_redirect_uri",
                            "redirect_uris must be https URLs, loopback http URLs or app schemes")

    method = req.get("token_endpoint_auth_method") or "none"
    if method not in AUTH_METHODS:
        return _oauth_error(400, "invalid_client_metadata",
                            f"token_endpoint_auth_method must be one of {', '.join(AUTH_METHODS)}")

    name = req.get("client_name")
    name = name.strip()[:100] if isinstance(name, str) and name.strip() else "Unbenannte Anwendung"

    client_id = _token(16)
    now = int(time.time())
    client = {"client_name": name, "redirect_uris": uris,
              "token_endpoint_auth_method": method, "created": now}
    resp = {"client_id": client_id, "client_id_issued_at": now, "client_name": name,
            "redirect_uris": uris, "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"], "token_endpoint_auth_method": method}
    if method != "none":
        secret = _token(32)
        client["secret_hash"] = _hash(secret)
        resp.update(client_secret=secret, client_secret_expires_at=0)

    _get_store().put(f"client#{client_id}", client)
    hosts = sorted({urllib.parse.urlsplit(u).hostname or urllib.parse.urlsplit(u).scheme for u in uris})
    print(f"[oauth] registered client {client_id} name={name!r} redirect_hosts={hosts} auth={method}")
    return _json(201, resp)


def authorize(event):
    p = _params(event)
    client = _get_store().get(f"client#{p.get('client_id', '')}")
    if not client:
        return _error_page(400, "Die Anwendung ist nicht registriert.")

    redirect_uri = p.get("redirect_uri")
    if not redirect_uri and len(client["redirect_uris"]) == 1:
        redirect_uri = client["redirect_uris"][0]
    # Never redirect to an unregistered URI, not even with an error.
    if redirect_uri not in client["redirect_uris"]:
        return _error_page(400, "Die Rücksprung-Adresse gehört nicht zu dieser Anwendung.")

    def back(error, description):
        return _redirect(_with_query(redirect_uri, {
            "error": error, "error_description": description, "state": p.get("state")}))

    if p.get("response_type") != "code":
        return back("unsupported_response_type", "only response_type=code is supported")
    if p.get("code_challenge_method") != "S256" or not p.get("code_challenge"):
        return back("invalid_request", "PKCE with code_challenge_method=S256 is required")
    resource = p.get("resource")
    if resource and resource.rstrip("/") != PUBLIC_URL:
        return back("invalid_target", f"resource must be {PUBLIC_URL}")

    rid, csrf = _token(), _token()
    _get_store().put(f"pending#{rid}", {
        "client_id": p["client_id"], "redirect_uri": redirect_uri, "state": p.get("state"),
        "code_challenge": p["code_challenge"], "csrf": csrf,
    }, PENDING_TTL)

    page = _consent_page(client, redirect_uri, rid, csrf)
    # The form is only accepted together with this cookie. SameSite=Strict keeps a
    # foreign site from submitting "allow" for a request it started itself.
    page["cookies"] = [f"__Host-kbc-{rid}={csrf}; Path=/; Secure; HttpOnly; "
                       f"SameSite=Strict; Max-Age={PENDING_TTL}"]
    return page


def consent(event):
    f = _form(event)
    rid = f.get("rid", "")
    cookie = _cookies(event).get(f"__Host-kbc-{rid}")
    if not rid or not cookie or not _eq(cookie, f.get("csrf", "")):
        return _error_page(403, "Die Anfrage ist abgelaufen oder ungültig.")
    pending = _get_store().take(f"pending#{rid}")
    if not pending or not _eq(pending["csrf"], cookie):
        return _error_page(403, "Die Anfrage ist abgelaufen oder ungültig.")

    clear = [f"__Host-kbc-{rid}=; Path=/; Secure; HttpOnly; SameSite=Strict; Max-Age=0"]
    if f.get("decision") != "allow":
        print(f"[oauth] consent denied for client {pending['client_id']}")
        return _redirect(_with_query(pending["redirect_uri"], {
            "error": "access_denied", "error_description": "user denied access",
            "state": pending.get("state")}), cookies=clear)

    verifier, nonce, login_state = _token(48), _token(), _token()
    pending.pop("csrf")
    _get_store().put(f"login#{login_state}",
                     {**pending, "entra_verifier": verifier, "nonce": nonce}, PENDING_TTL)
    print(f"[oauth] consent granted for client {pending['client_id']} "
          f"-> {_redirect_label(pending['redirect_uri'])}")
    return _redirect(_with_query(ENTRA_AUTHORIZE_URL, {
        "client_id": ENTRA_CLIENT_ID,
        "response_type": "code",
        "response_mode": "query",
        "redirect_uri": f"{PUBLIC_URL}{CALLBACK_PATH}",
        "scope": ENTRA_SCOPES,
        "state": login_state,
        "nonce": nonce,
        "code_challenge": _s256(verifier),
        "code_challenge_method": "S256",
    }), cookies=clear)


def callback(event):
    p = _params(event)
    login = _get_store().take(f"login#{p['state']}") if p.get("state") else None
    if not login:
        return _error_page(400, "Die Anmeldung ist abgelaufen oder wurde bereits verwendet.")

    def back(error, description):
        return _redirect(_with_query(login["redirect_uri"], {
            "error": error, "error_description": description, "state": login.get("state")}))

    if p.get("error"):
        print(f"[oauth] Entra returned error={p.get('error')} desc={p.get('error_description', '')[:200]}")
        return back("access_denied", "sign-in at Microsoft Entra ID failed or was cancelled")
    if not p.get("code"):
        return back("server_error", "no authorization code from Entra ID")

    try:
        tokens = _entra_token({
            "grant_type": "authorization_code",
            "code": p["code"],
            "redirect_uri": f"{PUBLIC_URL}{CALLBACK_PATH}",
            "code_verifier": login["entra_verifier"],
            "scope": ENTRA_SCOPES,
        })
        claims = _verify_id_token(tokens.get("id_token", ""), login["nonce"])
    except Exception as e:
        print(f"[oauth] Entra code exchange failed: {e!r}")
        return back("server_error", "sign-in at Microsoft Entra ID could not be completed")

    user = {"oid": claims["oid"],
            "upn": claims.get("preferred_username") or claims.get("email") or "",
            "name": claims.get("name", "")}
    code = _token()
    _get_store().put(f"code#{_hash(code)}", {
        "client_id": login["client_id"], "redirect_uri": login["redirect_uri"],
        "code_challenge": login["code_challenge"], "user": user,
        "entra_refresh": tokens.get("refresh_token"),
    }, CODE_TTL)
    print(f"[oauth] login ok upn={user['upn']} client={login['client_id']}")
    return _redirect(_with_query(login["redirect_uri"], {
        "code": code, "state": login.get("state"), "iss": PUBLIC_URL}))


def _client_credentials(event, form):
    auth = _headers(event).get("authorization", "")
    if auth.lower().startswith("basic "):
        try:
            raw = base64.b64decode(auth[6:]).decode()
            cid, _, secret = raw.partition(":")
            return urllib.parse.unquote(cid), urllib.parse.unquote(secret)
        except Exception:
            return None, None
    return form.get("client_id"), form.get("client_secret")


def _issue(client_id, user, entra_refresh):
    from jwt import encode as jwt_encode
    now = int(time.time())
    access = jwt_encode({
        "iss": PUBLIC_URL, "aud": PUBLIC_URL, "sub": user["oid"], "upn": user["upn"],
        "client_id": client_id, "scope": SCOPE, "token_use": TOKEN_USE,
        "iat": now, "exp": now + ACCESS_TOKEN_TTL, "jti": _token(8),
    }, _secret(SIGNING_KEY_ARN), algorithm="HS256")
    refresh = _token()
    _get_store().put(f"refresh#{_hash(refresh)}", {
        "client_id": client_id, "user": user, "entra_refresh": entra_refresh,
        "expires_at": now + REFRESH_TOKEN_TTL,
    }, REFRESH_TOKEN_TTL)
    return _json(200, {"access_token": access, "token_type": "Bearer",
                       "expires_in": ACCESS_TOKEN_TTL, "refresh_token": refresh, "scope": SCOPE})


def token(event):
    f = _form(event)
    client_id, client_secret = _client_credentials(event, f)
    client = _get_store().get(f"client#{client_id}") if client_id else None
    if not client:
        return _oauth_error(401, "invalid_client", "unknown client")
    if client["token_endpoint_auth_method"] != "none":
        if not client_secret or not _eq(_hash(client_secret), client["secret_hash"]):
            return _oauth_error(401, "invalid_client", "client authentication failed")

    grant = f.get("grant_type")
    if grant == "authorization_code":
        code = _get_store().take(f"code#{_hash(f.get('code', ''))}")
        if not code or code["client_id"] != client_id:
            return _oauth_error(400, "invalid_grant", "invalid or expired code")
        if f.get("redirect_uri", code["redirect_uri"]) != code["redirect_uri"]:
            return _oauth_error(400, "invalid_grant", "redirect_uri mismatch")
        verifier = f.get("code_verifier", "")
        if not verifier or not _eq(_s256(verifier), code["code_challenge"]):
            return _oauth_error(400, "invalid_grant", "PKCE verification failed")
        return _issue(client_id, code["user"], code["entra_refresh"])

    if grant == "refresh_token":
        key = f"refresh#{_hash(f.get('refresh_token', ''))}"
        rt = _get_store().take(key)  # rotation: every refresh token works once
        if not rt or rt["client_id"] != client_id:
            return _oauth_error(400, "invalid_grant", "invalid or expired refresh token")
        if not rt.get("entra_refresh"):
            return _oauth_error(400, "invalid_grant", "sign-in required")
        # Re-check the user at Entra so disabled accounts lose access at the next refresh.
        try:
            tokens = _entra_token({"grant_type": "refresh_token",
                                   "refresh_token": rt["entra_refresh"], "scope": ENTRA_SCOPES})
        except EntraError as e:
            if e.status == 400:
                print(f"[oauth] Entra refused refresh for upn={rt['user']['upn']}: {e}")
                return _oauth_error(400, "invalid_grant", "sign-in required")
            # Transient: put the token back so the client can retry.
            _get_store().put(key, rt, max(rt["expires_at"] - int(time.time()), 1))
            print(f"[oauth] Entra refresh unavailable: {e}")
            return _oauth_error(503, "temporarily_unavailable", "please retry")
        return _issue(client_id, rt["user"], tokens.get("refresh_token") or rt["entra_refresh"])

    return _oauth_error(400, "unsupported_grant_type")


ROUTES = {
    ("GET", "/.well-known/oauth-authorization-server"): metadata,
    ("GET", "/.well-known/openid-configuration"): metadata,
    ("POST", "/register"): register,
    ("GET", "/authorize"): authorize,
    ("POST", "/authorize"): consent,
    ("GET", CALLBACK_PATH): callback,
    ("POST", "/token"): token,
}


def handle(event, method, path):
    """Response for an OAuth route, or None if the path isn't one."""
    route = ROUTES.get((method, path))
    if route is None:
        return None
    if not enabled():
        return {"statusCode": 404, "body": "Not Found"}
    try:
        return route(event)
    except Exception:
        traceback.print_exc()
        return _oauth_error(500, "server_error")


def validate_access_token(token):
    """True for an unexpired access token issued by this proxy."""
    if not (PUBLIC_URL and SIGNING_KEY_ARN):
        return False
    import jwt
    # Entra tokens are RS256 and the API key isn't a JWT — skip both quietly without
    # touching the signing key.
    try:
        if jwt.get_unverified_header(token).get("alg") != "HS256":
            return False
    except jwt.PyJWTError:
        return False
    try:
        claims = jwt.decode(token, _secret(SIGNING_KEY_ARN), algorithms=["HS256"],
                            audience=PUBLIC_URL, issuer=PUBLIC_URL,
                            options={"require": ["exp", "sub"]})
    except Exception as e:  # PyJWTError, or the signing key can't be read
        print(f"[auth] proxy token rejected: {e!r}")
        return False
    return claims.get("token_use") == TOKEN_USE
