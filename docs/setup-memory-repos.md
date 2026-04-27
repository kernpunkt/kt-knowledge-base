# Memory-Repos einrichten

Für Teams-Zusammenfassungen und JIRA-Exporte werden separate GitHub-Repos pro Projekt angelegt. Diese werden genauso an die Knowledge Base angebunden wie jedes andere Dokumentations-Repo.

## Namenskonvention

| Zweck | Repo-Name |
|-------|-----------|
| Teams-Zusammenfassungen (projektspezifisch) | `[projektname]-team-memory` |
| JIRA-Exporte | `[projektname]-jira-memory` |
| Teams-Zusammenfassungen (kanalübergreifend/zentral) | `kernpunkt-team-memory` |

## Repo-Struktur

```
[projekt]-team-memory/
├── .kb-config.yaml
├── .github/
│   └── workflows/
│       └── sync-to-kb.yml
└── teams/
    └── YYYY-MM/
        └── YYYY-MM-DD_[kanal].md
```

## `.kb-config.yaml`

```yaml
display_name: "[Projektname] – Teams Memory"
description: "Teams-Zusammenfassungen aus dem Projekt [Projektname]"
```

## GitHub Actions Workflow

Datei `.github/workflows/sync-to-kb.yml`:

```yaml
name: Sync to Knowledge Base

on:
  push:
    branches: [main]

jobs:
  sync:
    uses: kernpunkt/kt-knowledge-base/.github/actions/sync-to-kb@main
    with:
      repo-name: ${{ github.repository }}
    secrets:
      role-arn: ${{ vars.KB_GITHUB_ACTIONS_ROLE_ARN }}
      s3-bucket: ${{ vars.KB_S3_BUCKET }}
      knowledge-base-id: ${{ vars.KB_KNOWLEDGE_BASE_ID }}
      data-source-id: ${{ vars.KB_DATA_SOURCE_ID }}
```

## Repository Variables (GitHub Settings → Secrets and variables → Actions)

| Variable | Wert (aus CDK Stack Output) |
|----------|-----------------------------|
| `KB_GITHUB_ACTIONS_ROLE_ARN` | `GitHubActionsRoleArn` |
| `KB_S3_BUCKET` | `BucketName` |
| `KB_KNOWLEDGE_BASE_ID` | `KnowledgeBaseId` |
| `KB_DATA_SOURCE_ID` | `DataSourceId` |

Die Stack Outputs für Dev und Prod stehen in `docs/` bzw. können per `aws cloudformation describe-stacks` abgerufen werden.

## Dokument-Vorlagen

Vorlagen für den Inhalt der Markdown-Dateien findest du in:
- `docs/templates/teams-summary-template.md`
- `docs/templates/jira-export-template.md`
