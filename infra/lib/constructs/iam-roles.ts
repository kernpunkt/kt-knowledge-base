import * as cdk from 'aws-cdk-lib';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as s3 from 'aws-cdk-lib/aws-s3';
import { Construct } from 'constructs';

export interface BedrockExecutionRoleProps {
  bucket: s3.IBucket;
  account: string;
  region: string;
  envName: string;
  vectorIndexArn: string;
}

export class BedrockExecutionRole extends Construct {
  public readonly role: iam.Role;

  constructor(scope: Construct, id: string, props: BedrockExecutionRoleProps) {
    super(scope, id);

    this.role = new iam.Role(this, 'Role', {
      roleName: `KernpunktKbBedrockRole-${props.envName}`,
      assumedBy: new iam.ServicePrincipal('bedrock.amazonaws.com', {
        conditions: {
          StringEquals: {
            'aws:SourceAccount': props.account,
          },
          ArnLike: {
            'aws:SourceArn': `arn:aws:bedrock:${props.region}:${props.account}:knowledge-base/*`,
          },
        },
      }),
      description: 'Role assumed by AWS Bedrock Knowledge Base service',
    });

    // S3 read access for document ingestion
    this.role.addToPolicy(new iam.PolicyStatement({
      sid: 'S3ReadForIngestion',
      effect: iam.Effect.ALLOW,
      actions: ['s3:GetObject', 's3:ListBucket'],
      resources: [props.bucket.bucketArn, `${props.bucket.bucketArn}/*`],
    }));

    // Bedrock Titan Embeddings model invocation
    this.role.addToPolicy(new iam.PolicyStatement({
      sid: 'TitanEmbeddingsAccess',
      effect: iam.Effect.ALLOW,
      actions: ['bedrock:InvokeModel'],
      resources: [
        `arn:aws:bedrock:${props.region}::foundation-model/amazon.titan-embed-text-v2:0`,
      ],
    }));

    // S3 Vectors access for vector storage and retrieval
    this.role.addToPolicy(new iam.PolicyStatement({
      sid: 'S3VectorsAccess',
      effect: iam.Effect.ALLOW,
      actions: [
        's3vectors:PutVectors',
        's3vectors:GetVectors',
        's3vectors:DeleteVectors',
        's3vectors:QueryVectors',
        's3vectors:GetIndex',
      ],
      resources: [props.vectorIndexArn],
    }));
  }
}

export interface GitHubActionsRoleProps {
  bucket: s3.IBucket;
  account: string;
  region: string;
  githubOrg: string;
  envName: string;
}

export class GitHubActionsRole extends Construct {
  public readonly role: iam.Role;

  constructor(scope: Construct, id: string, props: GitHubActionsRoleProps) {
    super(scope, id);

    // GitHub OIDC provider — one per AWS account
    // If the provider already exists in the account, import it instead of creating
    const githubProvider = new iam.OpenIdConnectProvider(this, 'GitHubOidcProvider', {
      url: 'https://token.actions.githubusercontent.com',
      clientIds: ['sts.amazonaws.com'],
    });

    this.role = new iam.Role(this, 'Role', {
      roleName: `KernpunktKbGitHubActionsRole-${props.envName}`,
      assumedBy: new iam.WebIdentityPrincipal(
        githubProvider.openIdConnectProviderArn,
        {
          StringEquals: {
            'token.actions.githubusercontent.com:aud': 'sts.amazonaws.com',
          },
          StringLike: {
            // Any repo in the org on main or master branch
            'token.actions.githubusercontent.com:sub': [
              `repo:${props.githubOrg}/*:ref:refs/heads/main`,
              `repo:${props.githubOrg}/*:ref:refs/heads/master`,
            ],
          },
        },
      ),
      description: 'Role assumed by GitHub Actions via OIDC for S3 sync',
    });

    // S3 write access for document sync
    this.role.addToPolicy(new iam.PolicyStatement({
      sid: 'S3SyncAccess',
      effect: iam.Effect.ALLOW,
      actions: ['s3:PutObject', 's3:DeleteObject', 's3:GetObject'],
      resources: [`${props.bucket.bucketArn}/*`],
    }));

    this.role.addToPolicy(new iam.PolicyStatement({
      sid: 'S3ListAccess',
      effect: iam.Effect.ALLOW,
      actions: ['s3:ListBucket', 's3:GetBucketLocation'],
      resources: [props.bucket.bucketArn],
    }));

    // StartIngestionJob is added later by the stack once the KB ARN is known
  }

  public grantStartIngestionJob(knowledgeBaseArn: string): void {
    this.role.addToPolicy(new iam.PolicyStatement({
      sid: 'BedrockStartIngestion',
      effect: iam.Effect.ALLOW,
      actions: ['bedrock:StartIngestionJob'],
      resources: [knowledgeBaseArn],
    }));
  }
}

export interface AgentConsumerRoleProps {
  account: string;
  region: string;
  knowledgeBaseArn: string;
  envName: string;
}

export class AgentConsumerRole extends Construct {
  public readonly role: iam.Role;

  constructor(scope: Construct, id: string, props: AgentConsumerRoleProps) {
    super(scope, id);

    this.role = new iam.Role(this, 'Role', {
      roleName: `KernpunktKbAgentConsumerRole-${props.envName}`,
      // Allow assumption by principals in the same account (developers / agents can be granted this role)
      assumedBy: new iam.AccountPrincipal(props.account),
      description: 'Least-privilege role for AI agents to query the knowledge base',
    });

    this.role.addToPolicy(new iam.PolicyStatement({
      sid: 'BedrockRetrieve',
      effect: iam.Effect.ALLOW,
      actions: [
        'bedrock:Retrieve',
        'bedrock:RetrieveAndGenerate',
      ],
      resources: [props.knowledgeBaseArn],
    }));

    new cdk.CfnOutput(scope, 'AgentConsumerRoleArn', {
      value: this.role.roleArn,
      description: 'ARN of the role for AI agents to assume when querying the knowledge base',
      exportName: `KernpunktKb-${props.envName}-AgentConsumerRoleArn`,
    });
  }
}
