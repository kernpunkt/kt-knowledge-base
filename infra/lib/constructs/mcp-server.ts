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
  /** Azure Entra ID tenant GUID — required for Claude Desktop OAuth flow */
  entraTenantId?: string;
  /** Application (client) ID from the Entra App Registration */
  entraClientId?: string;
}

export class McpServer extends Construct {
  public readonly functionUrl: string;

  constructor(scope: Construct, id: string, props: McpServerProps) {
    super(scope, id);

    const apiKeySecret = new secretsmanager.Secret(this, 'ApiKey', {
      secretName: `KernpunktKbMcpApiKey-${props.envName}`,
      generateSecretString: {
        excludePunctuation: true,
        passwordLength: 32,
      },
    });

    const env: Record<string, string> = {
      KNOWLEDGE_BASE_ID: props.knowledgeBaseId,
      S3_BUCKET_NAME: props.documentBucket.bucketName,
      API_KEY_SECRET_ARN: apiKeySecret.secretArn,
    };

    if (props.entraTenantId) env['ENTRA_TENANT_ID'] = props.entraTenantId;
    if (props.entraClientId)  env['ENTRA_CLIENT_ID']  = props.entraClientId;

    const fn = new lambda.Function(this, 'Function', {
      functionName: `KernpunktKbMcp-${props.envName}`,
      runtime: lambda.Runtime.PYTHON_3_12,
      handler: 'lambda_function.handler',
      code: lambda.Code.fromAsset('../mcp-server', {
        bundling: {
          // Installs PyJWT[crypto] into the deployment zip (requires Docker at synth/deploy time)
          image: lambda.Runtime.PYTHON_3_12.bundlingImage,
          command: [
            'bash', '-c',
            'pip install -r requirements.txt -t /asset-output && cp -au . /asset-output',
          ],
        },
      }),
      timeout: cdk.Duration.seconds(30),
      memorySize: 256,
      environment: env,
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
      resources: [
        `${props.documentBucket.bucketArn}/*.metadata.json`,
        `${props.documentBucket.bucketArn}/*/_repo-info.json`,
      ],
    }));

    const url = fn.addFunctionUrl({
      authType: lambda.FunctionUrlAuthType.NONE,
      cors: {
        allowedOrigins: ['*'],
        allowedMethods: [lambda.HttpMethod.POST, lambda.HttpMethod.GET],
        allowedHeaders: ['authorization', 'content-type', 'accept', 'mcp-session-id'],
      },
    });

    this.functionUrl = url.url;

    new cdk.CfnOutput(scope, 'McpServerUrl', {
      value: url.url,
      description: 'MCP server URL — OAuth (Entra ID) or legacy Bearer API key',
      exportName: `KernpunktKb-${props.envName}-McpServerUrl`,
    });

    new cdk.CfnOutput(scope, 'McpApiKeySecretArn', {
      value: apiKeySecret.secretArn,
      description: 'Legacy API key — run: aws secretsmanager get-secret-value --secret-id <arn> --query SecretString --output text',
      exportName: `KernpunktKb-${props.envName}-McpApiKeySecretArn`,
    });
  }
}
