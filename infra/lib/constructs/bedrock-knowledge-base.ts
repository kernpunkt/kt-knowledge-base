import * as cdk from 'aws-cdk-lib';
import * as bedrock from 'aws-cdk-lib/aws-bedrock';
import { Construct } from 'constructs';

// Titan Embeddings v2 at 1024 dimensions for best quality with German/English content
const EMBEDDING_MODEL_ARN = 'arn:aws:bedrock:eu-central-1::foundation-model/amazon.titan-embed-text-v2:0';
const EMBEDDING_DIMENSIONS = 1024;

export interface BedrockKnowledgeBaseProps {
  kbName: string;
  dataSourceName: string;
  bedrockRoleArn: string;
  bucketArn: string;
  vectorBucketArn: string;
  vectorIndexArn: string;
  envName: string;
}

export class BedrockKnowledgeBase extends Construct {
  public readonly knowledgeBaseId: string;
  public readonly knowledgeBaseArn: string;
  public readonly dataSourceId: string;

  constructor(scope: Construct, id: string, props: BedrockKnowledgeBaseProps) {
    super(scope, id);

    const cfnKb = new bedrock.CfnKnowledgeBase(this, 'KnowledgeBase', {
      name: props.kbName,
      description: `kernpunkt central knowledge base — project documentation for AI agents (${props.envName})`,
      roleArn: props.bedrockRoleArn,
      knowledgeBaseConfiguration: {
        type: 'VECTOR',
        vectorKnowledgeBaseConfiguration: {
          embeddingModelArn: EMBEDDING_MODEL_ARN,
          embeddingModelConfiguration: {
            bedrockEmbeddingModelConfiguration: {
              dimensions: EMBEDDING_DIMENSIONS,
            },
          },
        },
      },
      storageConfiguration: {
        type: 'S3_VECTORS',
        s3VectorsConfiguration: {
          vectorBucketArn: props.vectorBucketArn,
          indexArn: props.vectorIndexArn,
        },
      },
    });

    const cfnDataSource = new bedrock.CfnDataSource(this, 'DataSource', {
      name: props.dataSourceName,
      knowledgeBaseId: cfnKb.attrKnowledgeBaseId,
      description: 'S3 bucket with Markdown and image files from GitHub repositories',
      dataSourceConfiguration: {
        type: 'S3',
        s3Configuration: {
          bucketArn: props.bucketArn,
          // No inclusionPrefixes — sync all prefixes (each repo uses its own prefix)
        },
      },
      vectorIngestionConfiguration: {
        chunkingConfiguration: {
          chunkingStrategy: 'SEMANTIC',
          semanticChunkingConfiguration: {
            maxTokens: 300,
            bufferSize: 0,
            breakpointPercentileThreshold: 95,
          },
        },
      },
    });

    cfnDataSource.addDependency(cfnKb);

    this.knowledgeBaseId = cfnKb.attrKnowledgeBaseId;
    this.knowledgeBaseArn = cfnKb.attrKnowledgeBaseArn;
    this.dataSourceId = cfnDataSource.attrDataSourceId;

    new cdk.CfnOutput(scope, 'KnowledgeBaseId', {
      value: cfnKb.attrKnowledgeBaseId,
      description: 'Bedrock Knowledge Base ID',
      exportName: `KernpunktKb-${props.envName}-KnowledgeBaseId`,
    });

    new cdk.CfnOutput(scope, 'KnowledgeBaseArn', {
      value: cfnKb.attrKnowledgeBaseArn,
      description: 'Bedrock Knowledge Base ARN',
      exportName: `KernpunktKb-${props.envName}-KnowledgeBaseArn`,
    });

    new cdk.CfnOutput(scope, 'DataSourceId', {
      value: cfnDataSource.attrDataSourceId,
      description: 'Bedrock Knowledge Base Data Source ID',
      exportName: `KernpunktKb-${props.envName}-DataSourceId`,
    });
  }
}
