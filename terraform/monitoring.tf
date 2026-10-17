resource "aws_sns_topic" "alerts" {
  name              = "${local.name}-alerts"
  kms_master_key_id = aws_kms_key.data.arn
}

resource "aws_sns_topic_subscription" "email" {
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email
}

data "aws_iam_policy_document" "alerts" {
  statement {
    actions   = ["sns:Publish"]
    resources = [aws_sns_topic.alerts.arn]
    principals {
      type        = "Service"
      identifiers = ["cloudwatch.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [local.account_id]
    }
  }
}

resource "aws_sns_topic_policy" "alerts" {
  arn    = aws_sns_topic.alerts.arn
  policy = data.aws_iam_policy_document.alerts.json
}

# Something failed after all retries.
resource "aws_cloudwatch_metric_alarm" "dlq" {
  alarm_name          = "${local.name}-dlq-not-empty"
  alarm_description   = "Failed ingestion events are waiting in the DLQ. Inspect, fix, then replay with scripts/replay_dlq.py."
  namespace           = "AWS/SQS"
  metric_name         = "ApproximateNumberOfMessagesVisible"
  dimensions          = { QueueName = aws_sqs_queue.dlq.name }
  statistic           = "Maximum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
  ok_actions          = [aws_sns_topic.alerts.arn]
}

# Data freshness, per zone. The metric is only emitted by the two daily runs,
# so missing datapoints count as breaching and the alarm needs five
# consecutive empty 6-hour windows: it fires after 30 hours without prices,
# even if every run "succeeded".
resource "aws_cloudwatch_metric_alarm" "freshness" {
  for_each = toset(var.bidding_zones)

  alarm_name          = "${local.name}-no-data-${each.key}"
  alarm_description   = "No day-ahead prices ingested for ${each.key} in the last 30 hours."
  namespace           = "EnergyMarketIngestion"
  metric_name         = "IntervalsIngested"
  dimensions          = { BiddingZone = each.key }
  statistic           = "Sum"
  period              = 21600
  evaluation_periods  = 5
  datapoints_to_alarm = 5
  threshold           = 1
  comparison_operator = "LessThanThreshold"
  treat_missing_data  = "breaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
  ok_actions          = [aws_sns_topic.alerts.arn]
}
