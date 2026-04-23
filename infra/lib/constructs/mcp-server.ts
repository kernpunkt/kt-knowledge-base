import * as cdk from 'aws-cdk-lib';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as secretsmanager from 'aws-cdk-lib/aws-secretsmanager';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as s3 from 'aws-cdk-lib/aws-s3';
import { Construct } from 'constructs';

export interface McpServerProps {
  knowledgeBaseId: string;
  knowledgeBaseArn: string;
  documentBucket: s3.IBucket;
  envName: string;
}

export class McpServer extends Construct {
  public readonly functionUrl: string;

  constructor(scope: Construct, id: string, props: McpServerProps) {
    super(scope, id);

    // Generate and store API key in Secrets Manager
    const apiKeySecret = new secretsmanager.Secret(this, 'ApiKey', {
      secretName: `KernpunktKbMcpApiKey-${props.envName}`,
      generateSecretString: {
        excludePunctuation: true,
        passwordLength: 32,
      },
    });

    const fn = new lambda.Function(this, 'Function', {
      functionName: `KernpunktKbMcp-${props.envName}`,
      runtime: lambda.Runtime.PYTHON_3_12,
      handler: 'lambda_function.handler',
      // Path is relative to the infra/ directory (where CDK runs from)
      code: lambda.Code.fromAsset('../mcp-server'),
      timeout: cdk.Duration.seconds(30),
      memorySize: 256,
      environment: {
        KNOWLEDGE_BASE_ID: props.knowledgeBaseId,
        S3_BUCKET_NAME: props.documentBucket.bucketName,
        API_KEY_SECRET_ARN: apiKeySecret.secretArn,
      },
    });

    apiKeySecret.grantRead(fn);

    fn.addToRolePolicy(new iam.PolicyStatement({
      sid: 'BedrockRetrieve',
      effect: iam.Effect.ALLOW,
      actions: ['bedrock:Retrieve'],
      resources: [props.knowledgeBaseArn],
    }));

    fn.addToRolePolicy(new iam.PolicyStatement({
      sid: 'S3ListRepositories',
      effect: iam.Effect.ALLOW,
      actions: ['s3:ListBucket'],
      resources: [props.documentBucket.bucketArn],
    }));

    fn.addToRolePolicy(new iam.PolicyStatement({
      sid: 'S3ReadMetadata',
      effect: iam.Effect.ALLOW,
      actions: ['s3:GetObject'],
      resources: [`${props.documentBucket.bucketArn}/*.metadata.json`],
    }));

    // NONE auth — API key validation is handled inside the Lambda handler
    const url = fn.addFunctionUrl({
      authType: lambda.FunctionUrlAuthType.NONE,
      cors: {
        allowedOrigins: ['*'],
        allowedMethods: [lambda.HttpMethod.POST],
        allowedHeaders: ['authorization', 'content-type'],
      },
    });

    this.functionUrl = url.url;

    new cdk.CfnOutput(scope, 'McpServerUrl', {
      value: url.url,
      description: 'MCP server Lambda Function URL — clients send Authorization: Bearer <key>',
      exportName: `KernpunktKb-${props.envName}-McpServerUrl`,
    });

    new cdk.CfnOutput(scope, 'McpApiKeySecretArn', {
      value: apiKeySecret.secretArn,
      description: 'Secrets Manager ARN — run: aws secretsmanager get-secret-value --secret-id <arn> --query SecretString --output text',
      exportName: `KernpunktKb-${props.envName}-McpApiKeySecretArn`,
    });
  }
}
