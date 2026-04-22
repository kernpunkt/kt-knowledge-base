#!/usr/bin/env node
import 'source-map-support/register';
import * as cdk from 'aws-cdk-lib';
import { KnowledgeBaseStack } from '../lib/knowledge-base-stack';
import { getConfig } from '../lib/config';

const app = new cdk.App();

const devConfig = getConfig('dev');
new KnowledgeBaseStack(app, 'KernpunktKbDev', {
  env: {
    account: devConfig.account,
    region: devConfig.region,
  },
  config: devConfig,
  description: 'kernpunkt central knowledge base — dev environment',
});

const prodConfig = getConfig('production');
new KnowledgeBaseStack(app, 'KernpunktKbProduction', {
  env: {
    account: prodConfig.account,
    region: prodConfig.region,
  },
  config: prodConfig,
  description: 'kernpunkt central knowledge base — production environment',
});
