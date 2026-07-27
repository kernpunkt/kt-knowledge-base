export type Environment = 'dev' | 'production';

export interface KbConfig {
  envName: Environment;
  account: string;
  region: 'eu-central-1';
  bucketName: string;
  vectorBucketName: string;
  kbName: string;
  dataSourceName: string;
  githubOrg: string;
  logRetentionDays: number;
  alarmEmail?: string;
  /** Azure Entra ID tenant GUID (KB_ENTRA_TENANT_ID) */
  entraTenantId?: string;
  /** Entra App Registration client ID (KB_ENTRA_CLIENT_ID) */
  entraClientId?: string;
  /** Custom domain for the MCP server, e.g. kb-mcp.kernpunkt.de (KB_MCP_DOMAIN).
   *  Required for Entra OAuth: the App ID URI must live on a verified domain. */
  mcpDomainName?: string;
  /** ACM certificate ARN for mcpDomainName — MUST be in us-east-1 for CloudFront (KB_MCP_CERT_ARN) */
  mcpCertificateArn?: string;
}

export function getConfig(env: Environment): KbConfig {
  const account = env === 'dev'
    ? requireEnv('KB_DEV_ACCOUNT')
    : requireEnv('KB_PROD_ACCOUNT');

  const base: Omit<KbConfig, 'envName' | 'account' | 'bucketName' | 'vectorBucketName' | 'kbName' | 'dataSourceName' | 'logRetentionDays'> = {
    region: 'eu-central-1',
    githubOrg: 'kernpunkt',
    alarmEmail: process.env['KB_ALARM_EMAIL'],
    entraTenantId: process.env['KB_ENTRA_TENANT_ID'],
    entraClientId: process.env['KB_ENTRA_CLIENT_ID'],
    mcpDomainName: process.env['KB_MCP_DOMAIN'],
    mcpCertificateArn: process.env['KB_MCP_CERT_ARN'],
  };

  if (env === 'dev') {
    return {
      ...base,
      envName: 'dev',
      account,
      bucketName: 'kernpunkt-kb-documents-dev',
      vectorBucketName: 'kernpunkt-kb-vectors-dev',
      kbName: 'kernpunkt-knowledge-base-dev',
      dataSourceName: 'documents-s3-dev-v4',
      logRetentionDays: 30,
    };
  }

  return {
    ...base,
    envName: 'production',
    account,
    bucketName: 'kernpunkt-kb-documents-prod',
    vectorBucketName: 'kernpunkt-kb-vectors-prod',
    kbName: 'kernpunkt-knowledge-base-prod',
    dataSourceName: 'documents-s3-prod',
    logRetentionDays: 90,
  };
}

function requireEnv(name: string): string {
  const value = process.env[name];
  if (!value) {
    throw new Error(`Required environment variable ${name} is not set`);
  }
  return value;
}
