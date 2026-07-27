import * as cdk from 'aws-cdk-lib';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as secretsmanager from 'aws-cdk-lib/aws-secretsmanager';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as cloudfront from 'aws-cdk-lib/aws-cloudfront';
import * as origins from 'aws-cdk-lib/aws-cloudfront-origins';
import * as acm from 'aws-cdk-lib/aws-certificatemanager';
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
  /** Custom domain in front of the Function URL, e.g. kb-mcp.kernpunkt.de.
   *  Entra requires the OAuth resource (App ID URI) to live on a verified domain. */
  domainName?: string;
  /** ACM certificate ARN for domainName — MUST be in us-east-1 (CloudFront requirement). */
  certificateArn?: string;
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
    // Canonical public URL — used for the OAuth resource, aud check and advertised scope.
    if (props.domainName) env['MCP_PUBLIC_URL'] = `https://${props.domainName}`;

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

    // Custom domain via CloudFront — required for Entra OAuth (verified-domain App ID URI).
    // The Function URL uses AuthType NONE and the Lambda enforces its own Bearer auth,
    // so no OAC/SigV4 signing is needed between CloudFront and the origin.
    if (props.domainName && props.certificateArn) {
      const distribution = new cloudfront.Distribution(this, 'Distribution', {
        comment: `MCP server ${props.envName} (${props.domainName})`,
        domainNames: [props.domainName],
        certificate: acm.Certificate.fromCertificateArn(this, 'Cert', props.certificateArn),
        defaultBehavior: {
          origin: new origins.FunctionUrlOrigin(url),
          allowedMethods: cloudfront.AllowedMethods.ALLOW_ALL,
          viewerProtocolPolicy: cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
          // API traffic: don't cache, and forward everything except Host (Function URL
          // rejects a mismatched Host) — including the Authorization header.
          cachePolicy: cloudfront.CachePolicy.CACHING_DISABLED,
          originRequestPolicy: cloudfront.OriginRequestPolicy.ALL_VIEWER_EXCEPT_HOST_HEADER,
        },
      });

      new cdk.CfnOutput(scope, 'McpPublicUrl', {
        value: `https://${props.domainName}`,
        description: 'Public MCP server URL (custom domain) — use this as the Entra App ID URI and in Claude',
        exportName: `KernpunktKb-${props.envName}-McpPublicUrl`,
      });

      new cdk.CfnOutput(scope, 'McpDistributionDomain', {
        value: distribution.distributionDomainName,
        description: 'CloudFront domain — create a CNAME: <domainName> -> this value',
        exportName: `KernpunktKb-${props.envName}-McpDistributionDomain`,
      });
    }

    new cdk.CfnOutput(scope, 'McpApiKeySecretArn', {
      value: apiKeySecret.secretArn,
      description: 'Legacy API key — run: aws secretsmanager get-secret-value --secret-id <arn> --query SecretString --output text',
      exportName: `KernpunktKb-${props.envName}-McpApiKeySecretArn`,
    });
  }
}
