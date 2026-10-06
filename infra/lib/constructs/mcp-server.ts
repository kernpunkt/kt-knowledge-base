import * as cdk from 'aws-cdk-lib';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as secretsmanager from 'aws-cdk-lib/aws-secretsmanager';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as cloudfront from 'aws-cdk-lib/aws-cloudfront';
import * as origins from 'aws-cdk-lib/aws-cloudfront-origins';
import * as acm from 'aws-cdk-lib/aws-certificatemanager';
import * as dynamodb from 'aws-cdk-lib/aws-dynamodb';
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

    // OAuth proxy (DCR + consent page in front of Entra) — needs Entra and the custom
    // domain, because Entra redirects back to https://<domain>/oauth/callback.
    // It stays dormant until the Entra client secret below is set by hand.
    const oauthProxy = props.entraTenantId && props.entraClientId && props.domainName;
    let oauthTable: dynamodb.Table | undefined;
    let entraClientSecret: secretsmanager.Secret | undefined;
    let signingKey: secretsmanager.Secret | undefined;
    if (oauthProxy) {
      // Registered clients, pending logins, one-time codes, refresh tokens — all short-lived
      // except clients, so losing the table only forces clients to re-register.
      oauthTable = new dynamodb.Table(this, 'OAuthTable', {
        partitionKey: { name: 'pk', type: dynamodb.AttributeType.STRING },
        billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
        timeToLiveAttribute: 'ttl',
        removalPolicy: cdk.RemovalPolicy.DESTROY,
      });
      entraClientSecret = new secretsmanager.Secret(this, 'EntraClientSecret', {
        secretName: `KernpunktKbMcpEntraClientSecret-${props.envName}`,
        description: 'Client secret of the Entra app registration. Placeholder CHANGE_ME keeps the OAuth proxy disabled.',
        secretStringValue: cdk.SecretValue.unsafePlainText('CHANGE_ME'),
      });
      signingKey = new secretsmanager.Secret(this, 'OAuthSigningKey', {
        secretName: `KernpunktKbMcpOAuthSigningKey-${props.envName}`,
        description: 'HMAC key for access tokens issued by the MCP OAuth proxy',
        generateSecretString: { excludePunctuation: true, passwordLength: 64 },
      });
      env['OAUTH_TABLE_NAME'] = oauthTable.tableName;
      env['ENTRA_CLIENT_SECRET_ARN'] = entraClientSecret.secretArn;
      env['OAUTH_SIGNING_KEY_SECRET_ARN'] = signingKey.secretArn;
    }

    const fn = new lambda.Function(this, 'Function', {
      functionName: `KernpunktKbMcp-${props.envName}`,
      runtime: lambda.Runtime.PYTHON_3_12,
      handler: 'lambda_function.handler',
      code: lambda.Code.fromAsset('../mcp-server', {
        exclude: ['tests', '__pycache__', '.pytest_cache'],
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
    oauthTable?.grantReadWriteData(fn);
    entraClientSecret?.grantRead(fn);
    signingKey?.grantRead(fn);

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
      // Function URLs rename WWW-Authenticate to x-amzn-remapped-www-authenticate, which
      // hides the OAuth discovery hint in our 401s from MCP clients. Rename it back.
      const restoreWwwAuthenticate = new cloudfront.Function(this, 'RestoreWwwAuthenticate', {
        runtime: cloudfront.FunctionRuntime.JS_2_0,
        code: cloudfront.FunctionCode.fromInline(`
function handler(event) {
  var headers = event.response.headers;
  var remapped = headers['x-amzn-remapped-www-authenticate'];
  if (remapped) {
    headers['www-authenticate'] = remapped;
    delete headers['x-amzn-remapped-www-authenticate'];
  }
  return event.response;
}`),
      });

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
          functionAssociations: [{
            function: restoreWwwAuthenticate,
            eventType: cloudfront.FunctionEventType.VIEWER_RESPONSE,
          }],
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

    if (entraClientSecret) {
      new cdk.CfnOutput(scope, 'McpEntraClientSecretArn', {
        value: entraClientSecret.secretArn,
        description: 'Set the Entra client secret here to enable the OAuth proxy: aws secretsmanager put-secret-value --secret-id <arn> --secret-string <value>',
        exportName: `KernpunktKb-${props.envName}-McpEntraClientSecretArn`,
      });
    }

    new cdk.CfnOutput(scope, 'McpApiKeySecretArn', {
      value: apiKeySecret.secretArn,
      description: 'Legacy API key — run: aws secretsmanager get-secret-value --secret-id <arn> --query SecretString --output text',
      exportName: `KernpunktKb-${props.envName}-McpApiKeySecretArn`,
    });
  }
}
