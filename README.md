# kt-knowledge-base

Zentrale Wissensdatenbank der kernpunkt GmbH — ein RAG-System auf AWS Bedrock, das Projektdokumentation aus GitHub-Repositories semantisch durchsuchbar macht.

## Architektur

```
GitHub Repos (push to main)
        │
        ▼
GitHub Action (enrich-metadata.py + aws s3 sync)
        │
        ▼
Amazon S3  (kernpunkt-kb-documents-{env})
        │
        ▼
AWS Bedrock Knowledge Base
  - Embedding: amazon.titan-embed-text-v2:0 (1024 dims)
  - Chunking:  Semantic (maxTokens: 300)
  - Vektorspeicher: Amazon S3 Vectors
        │
        ▼ Retrieve API
KI-Agenten (Dev-Assistent, PM-Agent, Konzept/UX-Agent)
```

## Ein neues Repository anbinden

### 1. Workflow-Datei anlegen

Kopiere diese Datei in das Consumer-Repository unter `.github/workflows/sync-to-kb.yml`:

```yaml
name: Sync Docs to Knowledge Base

on:
  push:
    branches: [main, master]
    paths: ['**.md', '**.png', '**.jpg', '**.jpeg', '**.svg']
  workflow_dispatch:

permissions:
  id-token: write
  contents: read

jobs:
  sync:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - uses: kernpunkt/kt-knowledge-base/.github/actions/sync-to-kb@main
        with:
          aws-role-arn: ${{ vars.KB_GITHUB_ACTIONS_ROLE_ARN }}
          s3-bucket: ${{ vars.KB_S3_BUCKET }}
          knowledge-base-id: ${{ vars.KB_KNOWLEDGE_BASE_ID }}
          data-source-id: ${{ vars.KB_DATA_SOURCE_ID }}
```

### 2. Repository-Variablen setzen

Im Consumer-Repository unter **Settings → Secrets and variables → Variables**:

| Variable | Wert (dev) |
|---|---|
| `KB_GITHUB_ACTIONS_ROLE_ARN` | `arn:aws:iam::343345067181:role/KernpunktKbGitHubActionsRole-dev` |
| `KB_S3_BUCKET` | `kernpunkt-kb-documents-dev` |
| `KB_KNOWLEDGE_BASE_ID` | `I3WHA5QNNJ` |
| `KB_DATA_SOURCE_ID` | `MHEEAFXZR5` |

### 3. Ersten Sync anstoßen

Da beim ersten Push keine `.md`-Dateien *geändert* wurden, den Workflow manuell auslösen:

**Actions → Sync Docs to Knowledge Base → Run workflow**

Danach läuft der Sync automatisch bei jedem Push auf `main`/`master`, der Dokumentation ändert.

---

## Die Wissensdatenbank abfragen

### Abfrage ohne Filter (alle Repositories)

```python
import boto3

client = boto3.client("bedrock-agent-runtime", region_name="eu-central-1")

response = client.retrieve(
    knowledgeBaseId="I3WHA5QNNJ",
    retrievalQuery={"text": "Wie haben wir Caching in Shopware-Projekten gelöst?"},
    retrievalConfiguration={
        "vectorSearchConfiguration": {"numberOfResults": 5}
    },
)

for result in response["retrievalResults"]:
    print(result["content"]["text"])
    print(result["location"]["s3Location"]["uri"])
    print()
```

### Abfrage gefiltert nach einem bestimmten Repository

Der `source_repo`-Filter schränkt die Suche auf Dokumente aus einem einzelnen Repository ein. Der Wert entspricht dem GitHub-Repository-Namen im Format `owner/repo` (z.B. `kernpunkt/mup-docs`).

```python
import boto3

client = boto3.client("bedrock-agent-runtime", region_name="eu-central-1")

response = client.retrieve(
    knowledgeBaseId="I3WHA5QNNJ",
    retrievalQuery={"text": "Welche Architekturentscheidungen wurden zum Thema Checkout getroffen?"},
    retrievalConfiguration={
        "vectorSearchConfiguration": {
            "numberOfResults": 5,
            "filter": {
                "equals": {
                    "key": "source_repo",
                    "value": "kernpunkt/mup-docs",  # <-- Repository-Name anpassen
                }
            },
        }
    },
)

for result in response["retrievalResults"]:
    print(result["content"]["text"])
    print(result["location"]["s3Location"]["uri"])
    print()
```

### Abfrage über MCP (Claude Desktop / Claude Code)

Der MCP-Server ist zentral auf AWS Lambda gehostet — kein lokales Tooling nötig. Clients authentifizieren sich mit einem API-Key im `Authorization`-Header.

**API-Key abrufen** (einmalig, erfordert AWS-Zugriff):

```bash
aws secretsmanager get-secret-value \
  --secret-id KernpunktKbMcpApiKey-dev \
  --query SecretString --output text \
  --profile kt-kb-deployer
```

**URL abrufen:**

```bash
aws cloudformation describe-stacks \
  --stack-name KernpunktKbDev \
  --query "Stacks[0].Outputs[?OutputKey=='McpServerUrl'].OutputValue" \
  --output text \
  --profile kt-kb-deployer
```

**Konfiguration für Claude Code** (`~/.claude/settings.json`):

```json
{
  "mcpServers": {
    "kernpunkt-kb": {
      "type": "http",
      "url": "<McpServerUrl>",
      "headers": {
        "Authorization": "Bearer <api-key>"
      }
    }
  }
}
```

**Konfiguration für Claude Desktop** (`~/Library/Application Support/Claude/claude_desktop_config.json`):

Claude Desktop unterstützt den HTTP-Transport aktuell nicht nativ. Als Workaround liegt im Repository ein minimales Python-Skript (`mcp-server/stdio_proxy.py`), das als lokale stdio↔HTTP-Brücke fungiert — es leitet jede MCP-Nachricht per HTTP POST an den Lambda-Server weiter. Das Skript benötigt keine externen Abhängigkeiten (nur Python stdlib).

```json
{
  "mcpServers": {
    "kernpunkt-kb": {
      "command": "/Users/<username>/.pyenv/versions/<version>/bin/python3",
      "args": ["/path/to/kt-knowledge-base/mcp-server/stdio_proxy.py"],
      "env": {
        "MCP_API_KEY": "<api-key>",
        "MCP_SERVER_URL": "<McpServerUrl>"
      }
    }
  }
}
```

> **Hinweis:** Claude Desktop startet MCP-Server mit einem eingeschränkten `PATH`. Daher muss der vollständige Pfad zur Python-Binary angegeben werden (z.B. via `pyenv which python3`).

---

## Infrastruktur

Die Infrastruktur ist als AWS CDK App (TypeScript) in `infra/` definiert.

```bash
cd infra
npm install
npm run build
npm test

# Deploy
export KB_DEV_ACCOUNT=<aws-account-id>
export KB_PROD_ACCOUNT=<aws-account-id>
npm run deploy:dev
npm run deploy:prod
```

Weitere Details siehe [CLAUDE.md](./CLAUDE.md) und [docs/PRD_kernpunkt_wissensdatenbank.md](./docs/PRD_kernpunkt_wissensdatenbank.md).
