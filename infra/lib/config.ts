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
}

export function getConfig(env: Environment): KbConfig {
  const account = env === 'dev'
    ? requireEnv('KB_DEV_ACCOUNT')
    : requireEnv('KB_PROD_ACCOUNT');

  const base: Omit<KbConfig, 'envName' | 'account' | 'bucketName' | 'vectorBucketName' | 'kbName' | 'dataSourceName' | 'logRetentionDays'> = {
    region: 'eu-central-1',
    githubOrg: 'kernpunkt',
    alarmEmail: process.env['KB_ALARM_EMAIL'],
  };

  if (env === 'dev') {
    return {
      ...base,
      envName: 'dev',
      account,
      bucketName: 'kernpunkt-kb-documents-dev',
      vectorBucketName: 'kernpunkt-kb-vectors-dev',
      kbName: 'kernpunkt-knowledge-base-dev',
      dataSourceName: 'documents-s3-dev-v3',
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
