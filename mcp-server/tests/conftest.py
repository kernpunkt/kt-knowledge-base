import os
import sys

# Module-level config is read at import time, so set it before anything imports the server.
os.environ.update({
    "AWS_DEFAULT_REGION": "eu-central-1",
    "KNOWLEDGE_BASE_ID": "KB123",
    "S3_BUCKET_NAME": "bucket",
    "API_KEY_SECRET_ARN": "arn:api-key",
    "ENTRA_TENANT_ID": "tenant-1",
    "ENTRA_CLIENT_ID": "entra-client-1",
    "MCP_PUBLIC_URL": "https://kb-mcp.example.com",
    "OAUTH_TABLE_NAME": "oauth-table",
    "ENTRA_CLIENT_SECRET_ARN": "arn:entra-secret",
    "OAUTH_SIGNING_KEY_SECRET_ARN": "arn:signing-key",
})

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
