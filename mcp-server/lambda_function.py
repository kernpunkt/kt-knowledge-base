import json
import os
import functools
import boto3

KB_ID = os.environ["KNOWLEDGE_BASE_ID"]
S3_BUCKET = os.environ["S3_BUCKET_NAME"]
REGION = os.environ.get("AWS_REGION", "eu-central-1")

ENTRA_TENANT_ID = os.environ.get("ENTRA_TENANT_ID", "")
ENTRA_CLIENT_ID = os.environ.get("ENTRA_CLIENT_ID", "")
ENTRA_ISSUER = f"https://login.microsoftonline.com/{ENTRA_TENANT_ID}/v2.0"
# Entra issues v1 access tokens (iss = sts.windows.net) unless the resource app's
# requestedAccessTokenVersion is 2. Accept both so token-version config can't break us.
ENTRA_ISSUER_V1 = f"https://sts.windows.net/{ENTRA_TENANT_ID}/"
ENTRA_VALID_ISSUERS = {ENTRA_ISSUER, ENTRA_ISSUER_V1}
ENTRA_JWKS_URL = f"https://login.microsoftonline.com/{ENTRA_TENANT_ID}/discovery/v2.0/keys"

# Canonical public URL of this server (custom domain in front of the Function URL).
# Entra issues tokens with aud = the Application ID URI, which must be this URL, and
# Claude sends it as the RFC 8707 `resource`. Falls back to the request host when unset.
MCP_PUBLIC_URL = os.environ.get("MCP_PUBLIC_URL", "").rstrip("/")

# Delegated scope defined on the Entra app (Expose an API → access_as_user). A valid
# access token must carry this in `scp`, which only delegated user tokens have.
REQUIRED_SCOPE = "access_as_user"

bedrock = boto3.client("bedrock-agent-runtime", region_name=REGION)
s3 = boto3.client("s3", region_name=REGION)
secrets = boto3.client("secretsmanager", region_name=REGION)

# Lazy-initialised; only created when Entra is configured
_jwks_client = None


def _get_jwks_client():
    global _jwks_client
    if _jwks_client is None:
        from jwt import PyJWKClient
        _jwks_client = PyJWKClient(ENTRA_JWKS_URL, cache_keys=True)
    return _jwks_client


@functools.lru_cache(maxsize=1)
def _get_api_key():
    return secrets.get_secret_value(SecretId=os.environ["API_KEY_SECRET_ARN"])["SecretString"]


def _log_rejected_token(token, err):
    """Decode without verification to log why Entra's token was rejected (no secrets)."""
    try:
        from jwt import decode as jwt_decode
        c = jwt_decode(token, options={"verify_signature": False})
        print(f"[auth] JWT verify failed: {err!r} | iss={c.get('iss')} "
              f"aud={c.get('aud')} scp={c.get('scp')} roles={c.get('roles')} "
              f"ver={c.get('ver')} appid={c.get('appid')}")
    except Exception as e2:
        print(f"[auth] JWT undecodable: {err!r} / {e2!r}")


def _validate_jwt(token: str) -> bool:
    if not ENTRA_TENANT_ID or not ENTRA_CLIENT_ID:
        return False
    from jwt import decode as jwt_decode
    try:
        signing_key = _get_jwks_client().get_signing_key_from_jwt(token)
        payload = jwt_decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            # Verify iss/aud manually below so we can accept v1+v2 issuers and log mismatches.
            options={"verify_aud": False, "verify_iss": False},
        )
    except Exception as e:
        _log_rejected_token(token, e)
        return False

    if payload.get("iss") not in ENTRA_VALID_ISSUERS:
        print(f"[auth] iss mismatch: got {payload.get('iss')!r}, expected one of {ENTRA_VALID_ISSUERS}")
        return False

    aud = payload.get("aud", "")
    if isinstance(aud, str):
        aud = [aud]
    # Entra sets aud to the Application ID URI. With a custom domain that is the
    # full server URL; without one we fall back to the client-id forms.
    if MCP_PUBLIC_URL:
        valid_audiences = {MCP_PUBLIC_URL, f"{MCP_PUBLIC_URL}/"}
    else:
        valid_audiences = {ENTRA_CLIENT_ID, f"api://{ENTRA_CLIENT_ID}"}
    if not valid_audiences.intersection(set(aud)):
        print(f"[auth] aud mismatch: got {aud}, expected one of {valid_audiences}")
        return False

    # Require a delegated user token: it carries the `scp` claim with our delegated
    # scope. App-only (client_credentials) tokens carry `roles` and no `scp`, so this
    # rejects them even if the client secret leaks — every accepted request is tied
    # to an interactive Entra user login.
    scopes = payload.get("scp", "")
    scopes = scopes.split() if isinstance(scopes, str) else list(scopes)
    if REQUIRED_SCOPE not in scopes:
        print(f"[auth] scope missing: scp={payload.get('scp')} roles={payload.get('roles')}")
        return False

    return True


def _validate_token(token: str) -> bool:
    """Accept a valid Entra ID JWT or the legacy API key."""
    if _validate_jwt(token):
        return True
    return bool(token and token == _get_api_key())


LIST_REPOS_TOOL = {
    "name": "list_repositories",
    "description": (
        "List all GitHub repositories that have synced documents into the kernpunkt "
        "knowledge base. Returns the source_repo values you can pass to "
        "retrieve_from_knowledge_bases to restrict results to a single repo."
    ),
    "inputSchema": {"type": "object", "properties": {}, "required": []},
}

RETRIEVE_TOOL = {
    "name": "retrieve_from_knowledge_bases",
    "description": (
        "Search the kernpunkt knowledge base for project documentation, "
        "architecture decisions, concepts, Teams summaries, and JIRA exports."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Natural language search query",
            },
            "source_repo": {
                "type": "string",
                "description": (
                    "Optional: restrict results to one GitHub repository, "
                    "e.g. 'kernpunkt/mup-docs'"
                ),
            },
            "verbindlichkeit": {
                "type": "string",
                "description": (
                    "Optional: filter by credibility level — "
                    "'hoch' (ADRs/concepts), 'mittel' (meeting protocols), "
                    "'niedrig' (JIRA exports), 'hinweis' (Teams summaries)"
                ),
                "enum": ["hoch", "mittel", "niedrig", "hinweis"],
            },
            "typ": {
                "type": "string",
                "description": (
                    "Optional: filter by document type, "
                    "e.g. 'teams-zusammenfassung' or 'jira-export'"
                ),
            },
            "projekt": {
                "type": "string",
                "description": "Optional: filter by project name as stored in document frontmatter",
            },
            "filter": {
                "type": "object",
                "description": (
                    "Optional: filter by any frontmatter metadata field as key-value pairs, "
                    "e.g. {\"kanal\": \"general\"} or {\"jira_project_key\": \"MUP\"}. "
                    "Combined with AND logic alongside the other filter parameters."
                ),
            },
            "numberOfResults": {
                "type": "integer",
                "default": 5,
                "minimum": 1,
                "maximum": 20,
            },
        },
        "required": ["query"],
    },
}


def _list_repositories():
    paginator = s3.get_paginator("list_objects_v2")
    prefixes = []
    for page in paginator.paginate(Bucket=S3_BUCKET, Delimiter="/"):
        for cp in page.get("CommonPrefixes", []):
            prefixes.append(cp["Prefix"].rstrip("/"))

    if not prefixes:
        return [{"type": "text", "text": "No repositories found in the knowledge base."}]

    repos = []
    for prefix in sorted(prefixes):
        info = {"source_repo": prefix, "display_name": "", "description": ""}

        try:
            body = s3.get_object(Bucket=S3_BUCKET, Key=f"{prefix}/_repo-info.json")["Body"].read()
            info.update(json.loads(body))
        except Exception:
            resp = s3.list_objects_v2(Bucket=S3_BUCKET, Prefix=prefix + "/", MaxKeys=20)
            for obj in resp.get("Contents", []):
                if obj["Key"].endswith(".metadata.json"):
                    try:
                        body = s3.get_object(Bucket=S3_BUCKET, Key=obj["Key"])["Body"].read()
                        source_repo = json.loads(body).get("metadataAttributes", {}).get("source_repo")
                        if source_repo:
                            info["source_repo"] = source_repo
                            break
                    except Exception:
                        pass

        repos.append(info)

    lines = ["**Repositories in the knowledge base:**\n"]
    for r in repos:
        name = r.get("display_name") or r["source_repo"]
        line = f"- **{name}** (`{r['source_repo']}`)"
        if r.get("description"):
            line += f"\n  {r['description']}"
        lines.append(line)

    return [{"type": "text", "text": "\n".join(lines)}]


def _retrieve(args):
    vcfg = {"numberOfResults": args.get("numberOfResults", 5)}

    filters = []
    for key in ("source_repo", "verbindlichkeit", "typ", "projekt"):
        if key in args:
            filters.append({"equals": {"key": key, "value": args[key]}})
    for key, value in (args.get("filter") or {}).items():
        filters.append({"equals": {"key": key, "value": value}})
    if len(filters) == 1:
        vcfg["filter"] = filters[0]
    elif len(filters) > 1:
        vcfg["filter"] = {"andAll": filters}

    params = {
        "knowledgeBaseId": KB_ID,
        "retrievalQuery": {"text": args["query"]},
        "retrievalConfiguration": {"vectorSearchConfiguration": vcfg},
    }

    results = bedrock.retrieve(**params)["retrievalResults"]
    if not results:
        return [{"type": "text", "text": "No results found."}]

    PROMINENT = {"verbindlichkeit", "typ", "kanal", "zeitraum_von", "zeitraum_bis"}
    standard = {"source_repo", "file_path", "last_updated", "last_editor"}

    chunks = []
    for r in results:
        meta = r.get("metadata") or {}
        repo      = meta.get("source_repo", "")
        file_path = meta.get("file_path", r["location"]["s3Location"]["uri"])
        updated   = meta.get("last_updated", "")
        editor    = meta.get("last_editor", "")

        header = f"**{repo}** · `{file_path}` · Score: {r['score']:.3f}"
        if updated or editor:
            header += f"\nLast updated: {updated}" + (f" by {editor}" if editor else "")

        prominent_parts = [f"{k}: {meta[k]}" for k in PROMINENT if k in meta]
        if prominent_parts:
            header += "\n" + "  |  ".join(prominent_parts)

        extra = {k: v for k, v in meta.items() if k not in standard and k not in PROMINENT}
        if extra:
            header += "\n" + "  |  ".join(f"{k}: {v}" for k, v in extra.items())

        chunks.append(f"{header}\n\n{r['content']['text']}")

    return [{"type": "text", "text": "\n\n---\n\n".join(chunks)}]


def _respond(event, msg_id, result):
    body = json.dumps({"jsonrpc": "2.0", "id": msg_id, "result": result})
    headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
    if "text/event-stream" in headers.get("accept", ""):
        return {
            "statusCode": 200,
            "headers": {"Content-Type": "text/event-stream", "Cache-Control": "no-cache"},
            "body": f"data: {body}\n\n",
        }
    return {
        "statusCode": 200,
        "headers": {"Content-Type": "application/json"},
        "body": body,
    }


def _resource_url(event):
    # Canonical resource per RFC 8707: lowercase scheme+host, no trailing slash.
    if MCP_PUBLIC_URL:
        return MCP_PUBLIC_URL
    domain = event.get("requestContext", {}).get("domainName", "")
    return f"https://{domain}"


def handler(event, context):
    http = event.get("requestContext", {}).get("http", {})
    method = http.get("method", "POST")
    path = http.get("path", "/")

    # OAuth resource metadata discovery — no auth required, needed for Claude Desktop OAuth flow
    if method == "GET" and path == "/.well-known/oauth-protected-resource":
        if not ENTRA_TENANT_ID or not ENTRA_CLIENT_ID:
            # OAuth not configured — don't advertise a broken authorization server
            return {"statusCode": 404, "body": "Not Found"}
        resource = _resource_url(event)
        # Scope is defined under the Entra Application ID URI. With a custom domain the
        # App ID URI is the server URL, so the full scope value is <resource>/access_as_user.
        scope_prefix = MCP_PUBLIC_URL or f"api://{ENTRA_CLIENT_ID}"
        metadata = {
            "resource": resource,
            "authorization_servers": [ENTRA_ISSUER],
            "bearer_methods_supported": ["header"],
            "scopes_supported": [f"{scope_prefix}/access_as_user"],
        }
        return {
            "statusCode": 200,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps(metadata),
        }

    if method != "POST":
        return {"statusCode": 405, "body": "Method Not Allowed"}

    # Accept Entra ID JWT (OAuth) or legacy API key — both via Authorization: Bearer
    headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
    token = headers.get("authorization", "").removeprefix("Bearer ").strip()
    if not token or not _validate_token(token):
        resource = _resource_url(event)
        metadata_url = f"{resource}/.well-known/oauth-protected-resource"
        return {
            "statusCode": 401,
            "headers": {
                "Content-Type": "application/json",
                # Point Claude at the protected-resource metadata to start the OAuth flow.
                "WWW-Authenticate": f'Bearer resource_metadata="{metadata_url}", error="invalid_token"',
            },
            "body": json.dumps({"error": "Unauthorized"}),
        }

    body = json.loads(event.get("body") or "{}")
    mcp_method = body.get("method", "")
    msg_id = body.get("id")

    if mcp_method == "notifications/initialized":
        return {"statusCode": 202, "body": ""}

    if mcp_method == "initialize":
        result = {
            "protocolVersion": "2025-03-26",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "kernpunkt-kb", "version": "1.0.0"},
        }
    elif mcp_method == "tools/list":
        result = {"tools": [LIST_REPOS_TOOL, RETRIEVE_TOOL]}
    elif mcp_method == "tools/call":
        name = body["params"]["name"]
        args = body["params"].get("arguments", {})
        if name == "list_repositories":
            result = {"content": _list_repositories()}
        elif name == "retrieve_from_knowledge_bases":
            result = {"content": _retrieve(args)}
        else:
            return {
                "statusCode": 400,
                "body": json.dumps({"error": f"Unknown tool: {name}"}),
            }
    else:
        result = {}

    return _respond(event, msg_id, result)
