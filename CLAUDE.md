# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**kt-knowledge-base** is the infrastructure and tooling for kernpunkt GmbH's central knowledge base — a RAG system on AWS Bedrock that makes project documentation semantically searchable for AI agents and project members.

See `docs/PRD_kernpunkt_wissensdatenbank.md` for full requirements.

## Repository Structure

```
kt-knowledge-base/
├── docs/                         # Project documentation
│   └── PRD_kernpunkt_wissensdatenbank.md
├── infra/                        # AWS CDK app (TypeScript)
│   ├── bin/app.ts                # Entry point — two stacks: dev + production
│   ├── lib/
│   │   ├── config.ts             # KbConfig interface + getConfig()
│   │   ├── knowledge-base-stack.ts
│   │   └── constructs/
│   │       ├── document-bucket.ts
│   │       ├── s3-vectors-store.ts
│   │       ├── bedrock-knowledge-base.ts
│   │       ├── iam-roles.ts
│   │       └── monitoring.ts
│   └── test/
│       └── knowledge-base-stack.test.ts
├── scripts/
│   └── enrich-metadata.py        # Metadata sidecar generator
└── .github/
    ├── action.yml                 # Reusable composite action for consumer repos
    └── workflows/
        ├── deploy-infra.yml       # CDK deploy pipeline
        └── sync-to-kb.yml         # Example consumer workflow
```

## CDK Development

```bash
cd infra
npm install
npm run build     # compile TypeScript
npm test          # run CDK assertion tests
npm run synth     # cdk synth (requires KB_DEV_ACCOUNT + KB_PROD_ACCOUNT env vars)
npm run deploy:dev   # deploy dev stack
npm run deploy:prod  # deploy production stack
```

### Required environment variables for synth/deploy

```bash
export KB_DEV_ACCOUNT=<aws-account-id>
export KB_PROD_ACCOUNT=<aws-account-id>
export KB_ALARM_EMAIL=<optional-email>  # for CloudWatch alarm notifications
```

## Python Metadata Script

```bash
python scripts/enrich-metadata.py \
  --repo-name "my-project" \
  --root-dir /path/to/repo \
  --output-dir /path/to/staging
```

PyYAML is recommended (`pip install pyyaml`) for full frontmatter support, but the script also works without it using a minimal built-in parser.

## Architecture

```
GitHub Repos
    │ push to main
    ▼
GitHub Action (.github/action.yml)
    │ enriches metadata → stages files → aws s3 sync
    ▼
Amazon S3 (kernpunkt-kb-documents-{env})
    │ automatic ingestion
    ▼
AWS Bedrock Knowledge Base
  - Embedding: amazon.titan-embed-text-v2:0 (1024 dims)
  - Chunking: Semantic (maxTokens: 300)
  - Vector store: Amazon S3 Vectors (float32, 1024 dims, cosine)
    │
    ▼ Retrieve API
AI Agents (Dev assistant, PM agent, UX/Concept agent)
```

## Adding a New Repo to the Knowledge Base

In the consumer repo, create `.github/workflows/sync-to-kb.yml` and set these repository variables:

| Variable | Description |
|---|---|
| `KB_GITHUB_ACTIONS_ROLE_ARN` | From CDK stack output `GitHubActionsRoleArn` |
| `KB_S3_BUCKET` | From CDK stack output `BucketName` |
| `KB_KNOWLEDGE_BASE_ID` | From CDK stack output `KnowledgeBaseId` |
| `KB_DATA_SOURCE_ID` | From CDK stack output `DataSourceId` |

Then reference the reusable action:
```yaml
uses: kernpunkt/kt-knowledge-base/.github/actions/sync-to-kb@main
```

## Key Technical Notes

- **L1 CDK constructs** are used for Bedrock and S3 Vectors (no stable L2 yet)
- **IAM dependency**: Bedrock validates S3 Vectors permissions at KB creation time — the KB resource has an explicit `DependsOn` the IAM policy to avoid race conditions
- **Metadata sidecar format**: `{ "metadataAttributes": { "source_repo": "...", ... } }` — file named `<doc>.metadata.json` in same S3 prefix
- **OIDC trust**: any repo in the `kernpunkt` GitHub org on `main`/`master` can sync — no per-repo AWS config needed
- **Tags** (frontmatter lists) are serialized as comma-separated strings because Bedrock metadata only supports primitives
