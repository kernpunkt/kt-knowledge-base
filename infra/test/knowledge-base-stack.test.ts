import * as cdk from 'aws-cdk-lib';
import { Template, Match } from 'aws-cdk-lib/assertions';
import { KnowledgeBaseStack } from '../lib/knowledge-base-stack';
import { KbConfig } from '../lib/config';

const testConfig: KbConfig = {
  envName: 'dev',
  account: '123456789012',
  region: 'eu-central-1',
  bucketName: 'kernpunkt-kb-documents-dev',
  vectorBucketName: 'kernpunkt-kb-vectors-dev',
  kbName: 'kernpunkt-knowledge-base-dev',
  dataSourceName: 'documents-s3-dev',
  githubOrg: 'kernpunkt-digital',
  logRetentionDays: 30,
};

function buildStack(): Template {
  const app = new cdk.App();
  const stack = new KnowledgeBaseStack(app, 'TestStack', {
    env: { account: testConfig.account, region: testConfig.region },
    config: testConfig,
  });
  return Template.fromStack(stack);
}

describe('KnowledgeBaseStack', () => {
  let template: Template;

  beforeAll(() => {
    template = buildStack();
  });

  // ── S3 Bucket ──────────────────────────────────────────────────────────────

  describe('S3 Bucket', () => {
    test('has versioning enabled', () => {
      template.hasResourceProperties('AWS::S3::Bucket', {
        VersioningConfiguration: { Status: 'Enabled' },
      });
    });

    test('blocks all public access', () => {
      template.hasResourceProperties('AWS::S3::Bucket', {
        PublicAccessBlockConfiguration: {
          BlockPublicAcls: true,
          BlockPublicPolicy: true,
          IgnorePublicAcls: true,
          RestrictPublicBuckets: true,
        },
      });
    });

    test('bucket policy denies non-SSL requests', () => {
      template.hasResourceProperties('AWS::S3::BucketPolicy', {
        PolicyDocument: {
          Statement: Match.arrayWith([
            Match.objectLike({
              Effect: 'Deny',
              Condition: {
                Bool: { 'aws:SecureTransport': 'false' },
              },
            }),
          ]),
        },
      });
    });

    test('has S3-managed encryption', () => {
      template.hasResourceProperties('AWS::S3::Bucket', {
        BucketEncryption: {
          ServerSideEncryptionConfiguration: [
            {
              ServerSideEncryptionByDefault: {
                SSEAlgorithm: 'AES256',
              },
            },
          ],
        },
      });
    });
  });

  // ── S3 Vectors ─────────────────────────────────────────────────────────────

  describe('S3 Vectors Store', () => {
    test('vector bucket exists with correct name', () => {
      template.hasResourceProperties('AWS::S3Vectors::VectorBucket', {
        VectorBucketName: 'kernpunkt-kb-vectors-dev',
      });
    });

    test('vector index has correct dimension and distance metric', () => {
      template.hasResourceProperties('AWS::S3Vectors::Index', {
        IndexName: 'bedrock-kb-index',
        Dimension: 1024,
        DistanceMetric: 'cosine',
        DataType: 'float32',
      });
    });

    test('no OpenSearch Serverless resources are created', () => {
      template.resourceCountIs('AWS::OpenSearchServerless::Collection', 0);
      template.resourceCountIs('AWS::OpenSearchServerless::SecurityPolicy', 0);
      template.resourceCountIs('AWS::OpenSearchServerless::AccessPolicy', 0);
    });
  });

  // ── Bedrock Knowledge Base ─────────────────────────────────────────────────

  describe('Bedrock Knowledge Base', () => {
    test('uses Titan Embeddings v2 model', () => {
      template.hasResourceProperties('AWS::Bedrock::KnowledgeBase', {
        KnowledgeBaseConfiguration: {
          Type: 'VECTOR',
          VectorKnowledgeBaseConfiguration: {
            EmbeddingModelArn: Match.stringLikeRegexp('titan-embed-text-v2'),
          },
        },
      });
    });

    test('uses S3 Vectors storage with index ARN', () => {
      template.hasResourceProperties('AWS::Bedrock::KnowledgeBase', {
        StorageConfiguration: {
          Type: 'S3_VECTORS',
          S3VectorsConfiguration: {
            IndexArn: Match.anyValue(),
            VectorBucketArn: Match.anyValue(),
          },
        },
      });
    });

    test('data source is S3 type', () => {
      template.hasResourceProperties('AWS::Bedrock::DataSource', {
        DataSourceConfiguration: {
          Type: 'S3',
        },
      });
    });

    test('data source uses semantic chunking', () => {
      template.hasResourceProperties('AWS::Bedrock::DataSource', {
        VectorIngestionConfiguration: {
          ChunkingConfiguration: {
            ChunkingStrategy: 'SEMANTIC',
          },
        },
      });
    });
  });

  // ── IAM Roles ──────────────────────────────────────────────────────────────

  describe('IAM Roles', () => {
    test('Bedrock execution role trusts bedrock.amazonaws.com', () => {
      template.hasResourceProperties('AWS::IAM::Role', {
        AssumeRolePolicyDocument: {
          Statement: Match.arrayWith([
            Match.objectLike({
              Principal: { Service: 'bedrock.amazonaws.com' },
            }),
          ]),
        },
      });
    });

    test('Bedrock execution role has S3 Vectors permissions', () => {
      template.hasResourceProperties('AWS::IAM::Policy', {
        PolicyDocument: {
          Statement: Match.arrayWith([
            Match.objectLike({
              Action: Match.arrayWith(['s3vectors:QueryVectors']),
              Effect: 'Allow',
            }),
          ]),
        },
      });
    });

    test('Bedrock execution role has no AOSS permissions', () => {
      const policies = template.findResources('AWS::IAM::Policy', {
        Properties: {
          PolicyDocument: {
            Statement: Match.arrayWith([
              Match.objectLike({
                Action: Match.arrayWith(['aoss:APIAccessAll']),
              }),
            ]),
          },
        },
      });
      expect(Object.keys(policies).length).toBe(0);
    });

    test('GitHub Actions role uses federated OIDC principal', () => {
      template.hasResourceProperties('AWS::IAM::Role', {
        AssumeRolePolicyDocument: {
          Statement: Match.arrayWith([
            Match.objectLike({
              Principal: {
                Federated: Match.anyValue(),
              },
              Condition: Match.objectLike({
                StringEquals: Match.objectLike({
                  'token.actions.githubusercontent.com:aud': 'sts.amazonaws.com',
                }),
              }),
            }),
          ]),
        },
      });
    });

    test('agent consumer role has Retrieve permission', () => {
      template.hasResourceProperties('AWS::IAM::Policy', {
        PolicyDocument: {
          Statement: Match.arrayWith([
            Match.objectLike({
              Action: Match.arrayWith(['bedrock:Retrieve']),
              Effect: 'Allow',
            }),
          ]),
        },
      });
    });
  });

  // ── Monitoring ─────────────────────────────────────────────────────────────

  describe('Monitoring', () => {
    test('CloudWatch log group exists', () => {
      template.hasResourceProperties('AWS::Logs::LogGroup', {
        LogGroupName: Match.stringLikeRegexp('/kernpunkt/knowledge-base/'),
      });
    });

    test('CloudWatch alarm exists for ingestion failures', () => {
      template.hasResourceProperties('AWS::CloudWatch::Alarm', {
        AlarmName: Match.stringLikeRegexp('IngestionFailure'),
      });
    });
  });

  // ── Stack outputs ──────────────────────────────────────────────────────────

  describe('Stack Outputs', () => {
    test('exports Knowledge Base ID', () => {
      template.hasOutput('KnowledgeBaseId', {
        Export: Match.objectLike({
          Name: Match.stringLikeRegexp('KnowledgeBaseId'),
        }),
      });
    });

    test('exports S3 bucket name', () => {
      // CDK appends a hash to the logical ID for outputs inside nested constructs
      const outputs = template.findOutputs('*', {
        Export: { Name: Match.stringLikeRegexp('BucketName') },
      });
      expect(Object.keys(outputs).length).toBeGreaterThan(0);
    });

    test('exports vector bucket ARN', () => {
      const outputs = template.findOutputs('*', {
        Export: { Name: Match.stringLikeRegexp('VectorBucketArn') },
      });
      expect(Object.keys(outputs).length).toBeGreaterThan(0);
    });
  });
});
