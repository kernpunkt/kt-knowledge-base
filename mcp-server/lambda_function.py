import json
import os
import functools
import boto3

KB_ID = os.environ["KNOWLEDGE_BASE_ID"]
S3_BUCKET = os.environ["S3_BUCKET_NAME"]
REGION = os.environ.get("AWS_REGION", "eu-central-1")
bedrock = boto3.client("bedrock-agent-runtime", region_name=REGION)
s3 = boto3.client("s3", region_name=REGION)
secrets = boto3.client("secretsmanager", region_name=REGION)


@functools.lru_cache(maxsize=1)
def _get_api_key():
    """Fetch API key from Secrets Manager; cached for the lifetime of the container."""
    return secrets.get_secret_value(SecretId=os.environ["API_KEY_SECRET_ARN"])["SecretString"]


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

        # Preferred: dedicated repo-info file written by the sync action
        try:
            body = s3.get_object(Bucket=S3_BUCKET, Key=f"{prefix}/_repo-info.json")["Body"].read()
            info.update(json.loads(body))
        except Exception:
            # Fallback: read source_repo from first document sidecar
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

    # Fields shown in their own line for quick orientation
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


def handler(event, context):
    # Validate API key from Authorization: Bearer <key> header
    headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
    token = headers.get("authorization", "").removeprefix("Bearer ").strip()
    if not token or token != _get_api_key():
        return {"statusCode": 401, "body": json.dumps({"error": "Unauthorized"})}

    body = json.loads(event.get("body") or "{}")
    method = body.get("method", "")
    msg_id = body.get("id")

    if method == "notifications/initialized":
        return {"statusCode": 202, "body": ""}

    if method == "initialize":
        result = {
            "protocolVersion": "2025-03-26",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "kernpunkt-kb", "version": "1.0.0"},
        }
    elif method == "tools/list":
        result = {"tools": [LIST_REPOS_TOOL, RETRIEVE_TOOL]}
    elif method == "tools/call":
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

    return {
        "statusCode": 200,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps({"jsonrpc": "2.0", "id": msg_id, "result": result}),
    }
