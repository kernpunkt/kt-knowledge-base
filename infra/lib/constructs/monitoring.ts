import * as cdk from 'aws-cdk-lib';
import * as cloudwatch from 'aws-cdk-lib/aws-cloudwatch';
import * as cloudwatchActions from 'aws-cdk-lib/aws-cloudwatch-actions';
import * as logs from 'aws-cdk-lib/aws-logs';
import * as sns from 'aws-cdk-lib/aws-sns';
import * as snsSubscriptions from 'aws-cdk-lib/aws-sns-subscriptions';
import { Construct } from 'constructs';

export interface MonitoringProps {
  knowledgeBaseId: string;
  envName: string;
  logRetentionDays: number;
  alarmEmail?: string;
}

export class Monitoring extends Construct {
  public readonly ingestionLogGroup: logs.LogGroup;

  constructor(scope: Construct, id: string, props: MonitoringProps) {
    super(scope, id);

    // Log group for Bedrock ingestion events
    this.ingestionLogGroup = new logs.LogGroup(this, 'IngestionLogGroup', {
      logGroupName: `/kernpunkt/knowledge-base/${props.envName}/ingestion`,
      retention: props.logRetentionDays as logs.RetentionDays,
      removalPolicy: props.envName === 'dev'
        ? cdk.RemovalPolicy.DESTROY
        : cdk.RemovalPolicy.RETAIN,
    });

    // Metric filter for ingestion failures
    // Bedrock emits ingestion status to CloudWatch Logs; filter for FAILED status
    const failureMetricFilter = new logs.MetricFilter(this, 'IngestionFailureFilter', {
      logGroup: this.ingestionLogGroup,
      metricNamespace: 'KernpunktKnowledgeBase',
      metricName: 'IngestionFailures',
      filterPattern: logs.FilterPattern.anyTerm('FAILED', 'FAILED_PARTIALLY'),
      metricValue: '1',
    });

    const ingestionFailureMetric = failureMetricFilter.metric({
      statistic: 'Sum',
      period: cdk.Duration.hours(1),
    });

    const failureAlarm = new cloudwatch.Alarm(this, 'IngestionFailureAlarm', {
      alarmName: `KernpunktKb-${props.envName}-IngestionFailure`,
      alarmDescription: 'Bedrock Knowledge Base ingestion job failed or partially failed',
      metric: ingestionFailureMetric,
      threshold: 1,
      evaluationPeriods: 1,
      comparisonOperator: cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
      treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
    });

    if (props.alarmEmail) {
      const alarmTopic = new sns.Topic(this, 'AlarmTopic', {
        topicName: `kernpunkt-kb-alarms-${props.envName}`,
        displayName: `kernpunkt Knowledge Base Alarms (${props.envName})`,
      });

      alarmTopic.addSubscription(
        new snsSubscriptions.EmailSubscription(props.alarmEmail),
      );

      failureAlarm.addAlarmAction(new cloudwatchActions.SnsAction(alarmTopic));
    }

    new cdk.CfnOutput(scope, 'IngestionLogGroupName', {
      value: this.ingestionLogGroup.logGroupName,
      description: 'CloudWatch Log Group for Bedrock ingestion events',
      exportName: `KernpunktKb-${props.envName}-IngestionLogGroupName`,
    });
  }
}
