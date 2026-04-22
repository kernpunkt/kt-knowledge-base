#!/usr/bin/env python3
"""
Minimal stdio↔HTTP bridge for the kernpunkt KB MCP server.
Use this instead of mcp-remote when Claude Desktop can't reach the Lambda URL directly.

Config in claude_desktop_config.json:
  {
    "mcpServers": {
      "kernpunkt-kb": {
        "command": "python3",
        "args": ["/path/to/mcp-server/stdio_proxy.py"],
        "env": { "MCP_API_KEY": "<your-api-key>" }
      }
    }
  }
"""
import sys
import json
import os
import urllib.request

URL = os.environ.get(
    "MCP_SERVER_URL",
    "https://zm6m6rqu5vw6i7mukkp437upfu0jcnap.lambda-url.eu-central-1.on.aws/",
)
API_KEY = os.environ["MCP_API_KEY"]


def post(payload: str):
    req = urllib.request.Request(
        URL,
        data=payload.encode(),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {API_KEY}",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode().strip() or None


for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    try:
        response = post(line)
    except Exception as e:
        msg = json.loads(line)
        response = json.dumps({
            "jsonrpc": "2.0",
            "id": msg.get("id"),
            "error": {"code": -32000, "message": str(e)},
        })
    if response:
        sys.stdout.write(response + "\n")
        sys.stdout.flush()
