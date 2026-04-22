import * as cdk from 'aws-cdk-lib';
import { Construct } from 'constructs';
import { KbConfig } from './config';
import { DocumentBucket } from './constructs/document-bucket';
import { BedrockExecutionRole, GitHubActionsRole, AgentConsumerRole } from './constructs/iam-roles';
import { S3VectorsStore } from './constructs/s3-vectors-store';
import { BedrockKnowledgeBase } from './constructs/bedrock-knowledge-base';
import { Monitoring } from './constructs/monitoring';

export interface KnowledgeBaseStackProps extends cdk.StackProps {
  config: KbConfig;
}

export class KnowledgeBaseStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props: KnowledgeBaseStackProps) {
    super(scope, id, props);

    const { config } = props;

    // 1. S3 bucket — no dependencies
    const documentBucket = new DocumentBucket(this, 'DocumentBucket', {
      bucketName: config.bucketName,
      envName: config.envName,
    });

    // 2. S3 Vectors store — no dependencies
    const s3VectorsStore = new S3VectorsStore(this, 'S3VectorsStore', {
      vectorBucketName: config.vectorBucketName,
      envName: config.envName,
    });

    // 3. Bedrock execution role — depends on bucket ARN and vector index ARN
    const bedrockExecutionRole = new BedrockExecutionRole(this, 'BedrockExecutionRole', {
      bucket: documentBucket.bucket,
      account: config.account,
      region: config.region,
      envName: config.envName,
      vectorIndexArn: s3VectorsStore.vectorIndexArn,
    });

    // 4. GitHub Actions OIDC role — depends on bucket ARN (KB ARN added after KB creation)
    const githubActionsRole = new GitHubActionsRole(this, 'GitHubActionsRole', {
      bucket: documentBucket.bucket,
      account: config.account,
      region: config.region,
      githubOrg: config.githubOrg,
      envName: config.envName,
    });

    // 5. Bedrock Knowledge Base — depends on role + S3 Vectors store.
    //    Bedrock validates IAM permissions at KB creation time, so we must ensure the
    //    role's policy (a separate AWS::IAM::Policy resource) is fully applied before
    //    the KB is created — an explicit dependency achieves this.
    const bedrockRolePolicy = bedrockExecutionRole.role.node.tryFindChild('DefaultPolicy');
    const knowledgeBase = new BedrockKnowledgeBase(this, 'BedrockKnowledgeBase', {
      kbName: config.kbName,
      dataSourceName: config.dataSourceName,
      bedrockRoleArn: bedrockExecutionRole.role.roleArn,
      bucketArn: documentBucket.bucket.bucketArn,
      vectorBucketArn: s3VectorsStore.vectorBucketArn,
      vectorIndexArn: s3VectorsStore.vectorIndexArn,
      envName: config.envName,
    });

    if (bedrockRolePolicy) {
      knowledgeBase.node.addDependency(bedrockRolePolicy);
    }

    // 6. Grant GitHub Actions role permission to trigger ingestion (now that KB ARN is known)
    githubActionsRole.grantStartIngestionJob(knowledgeBase.knowledgeBaseArn);

    // Output the GitHub Actions role ARN for use in consumer repos
    new cdk.CfnOutput(this, 'GitHubActionsRoleArn', {
      value: githubActionsRole.role.roleArn,
      description: 'ARN of the GitHub Actions OIDC role — set as KB_GITHUB_ACTIONS_ROLE_ARN in consumer repos',
      exportName: `KernpunktKb-${config.envName}-GitHubActionsRoleArn`,
    });

    // 7. Agent consumer role — depends on KB ARN
    new AgentConsumerRole(this, 'AgentConsumerRole', {
      account: config.account,
      region: config.region,
      knowledgeBaseArn: knowledgeBase.knowledgeBaseArn,
      envName: config.envName,
    });

    // 8. Monitoring — log groups and alarms
    new Monitoring(this, 'Monitoring', {
      knowledgeBaseId: knowledgeBase.knowledgeBaseId,
      envName: config.envName,
      logRetentionDays: config.logRetentionDays,
      alarmEmail: config.alarmEmail,
    });

    // Stack-level tags
    cdk.Tags.of(this).add('Project', 'kt-knowledge-base');
    cdk.Tags.of(this).add('Environment', config.envName);
    cdk.Tags.of(this).add('ManagedBy', 'aws-cdk');
  }
}
