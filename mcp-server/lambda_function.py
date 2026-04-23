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
        "architecture decisions, and concepts."
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
        source_repo = None
        resp = s3.list_objects_v2(Bucket=S3_BUCKET, Prefix=prefix + "/", MaxKeys=20)
        for obj in resp.get("Contents", []):
            if obj["Key"].endswith(".metadata.json"):
                try:
                    body = s3.get_object(Bucket=S3_BUCKET, Key=obj["Key"])["Body"].read()
                    source_repo = json.loads(body).get("metadataAttributes", {}).get("source_repo")
                    if source_repo:
                        break
                except Exception:
                    pass
        repos.append(source_repo or prefix)

    lines = ["**Repositories in the knowledge base:**\n"]
    lines += [f"- `{r}`" for r in repos]
    return [{"type": "text", "text": "\n".join(lines)}]


def _retrieve(args):
    params = {
        "knowledgeBaseId": KB_ID,
        "retrievalQuery": {"text": args["query"]},
        "retrievalConfiguration": {
            "vectorSearchConfiguration": {
                "numberOfResults": args.get("numberOfResults", 5),
            }
        },
    }
    if "source_repo" in args:
        params["retrievalConfiguration"]["vectorSearchConfiguration"]["filter"] = {
            "equals": {"key": "source_repo", "value": args["source_repo"]}
        }

    results = bedrock.retrieve(**params)["retrievalResults"]
    if not results:
        return [{"type": "text", "text": "No results found."}]

    text = "\n\n---\n\n".join(
        f"**Source**: {r['location']['s3Location']['uri']}\n"
        f"**Score**: {r['score']:.3f}\n\n{r['content']['text']}"
        for r in results
    )
    return [{"type": "text", "text": text}]


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
