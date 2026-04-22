import * as cdk from 'aws-cdk-lib';
import { aws_s3vectors as s3vectors } from 'aws-cdk-lib';
import { Construct } from 'constructs';

const VECTOR_INDEX_NAME = 'bedrock-kb-index';

export interface S3VectorsStoreProps {
  vectorBucketName: string;
  envName: string;
}

export class S3VectorsStore extends Construct {
  public readonly vectorBucketArn: string;
  public readonly vectorIndexArn: string;
  public readonly vectorIndexName: string;

  constructor(scope: Construct, id: string, props: S3VectorsStoreProps) {
    super(scope, id);

    const vectorBucket = new s3vectors.CfnVectorBucket(this, 'VectorBucket', {
      vectorBucketName: props.vectorBucketName,
    });

    // 1024 dims matches Titan Embeddings v2; cosine is correct for its normalized output
    const vectorIndex = new s3vectors.CfnIndex(this, 'VectorIndex', {
      vectorBucketArn: vectorBucket.attrVectorBucketArn,
      indexName: VECTOR_INDEX_NAME,
      dataType: 'float32',
      dimension: 1024,
      distanceMetric: 'cosine',
    });

    this.vectorBucketArn = vectorBucket.attrVectorBucketArn;
    this.vectorIndexArn = vectorIndex.attrIndexArn;
    this.vectorIndexName = VECTOR_INDEX_NAME;

    new cdk.CfnOutput(scope, 'VectorBucketArn', {
      value: vectorBucket.attrVectorBucketArn,
      description: 'S3 Vectors bucket ARN',
      exportName: `KernpunktKb-${props.envName}-VectorBucketArn`,
    });

    new cdk.CfnOutput(scope, 'VectorIndexArn', {
      value: vectorIndex.attrIndexArn,
      description: 'S3 Vectors index ARN',
      exportName: `KernpunktKb-${props.envName}-VectorIndexArn`,
    });
  }
}
