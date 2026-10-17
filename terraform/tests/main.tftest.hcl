mock_provider "aws" {
  mock_data "aws_iam_policy_document" {
    defaults = { json = "{\"Version\":\"2012-10-17\",\"Statement\":[]}" }
  }
  mock_data "aws_ecr_repository" {
    defaults = { repository_url = "123456789012.dkr.ecr.eu-west-3.amazonaws.com/market-ingest" }
  }
  mock_data "aws_caller_identity" {
    defaults = { account_id = "123456789012" }
  }
  mock_data "aws_region" {
    defaults = { region = "eu-west-3" }
  }
  mock_resource "aws_kms_key" {
    defaults = { arn = "arn:aws:kms:eu-west-3:123456789012:key/11111111-2222-3333-4444-555555555555" }
  }
  mock_resource "aws_sqs_queue" {
    defaults = { arn = "arn:aws:sqs:eu-west-3:123456789012:market-ingest-prod-dlq" }
  }
  mock_resource "aws_iam_role" {
    defaults = { arn = "arn:aws:iam::123456789012:role/market-ingest-prod-lambda" }
  }
  mock_resource "aws_lambda_function" {
    defaults = { arn = "arn:aws:lambda:eu-west-3:123456789012:function:market-ingest-prod" }
  }
  mock_resource "aws_sns_topic" {
    defaults = { arn = "arn:aws:sns:eu-west-3:123456789012:market-ingest-prod-alerts" }
  }
}

variables {
  image_tag = "3f2c1ab"
}

run "lambda_is_pinned_and_safe" {
  command = plan

  assert {
    condition     = aws_lambda_function.ingest.image_uri == "123456789012.dkr.ecr.eu-west-3.amazonaws.com/market-ingest:3f2c1ab"
    error_message = "The function must run the exact image built from the commit."
  }

  assert {
    condition     = aws_lambda_function.ingest.architectures == tolist(["arm64"])
    error_message = "The function runs on Graviton."
  }

  assert {
    condition     = aws_lambda_function.ingest.reserved_concurrent_executions == 1
    error_message = "A single concurrent run protects the API rate limit and the partitions."
  }
}

run "schedules_run_after_the_auction_in_paris_time" {
  command = plan

  assert {
    condition     = alltrue([for s in aws_scheduler_schedule.ingest : s.schedule_expression_timezone == "Europe/Paris"])
    error_message = "Schedules must follow the market's local time (DST included)."
  }

  assert {
    condition     = aws_scheduler_schedule.ingest["after-auction"].schedule_expression == "cron(15 13 * * ? *)"
    error_message = "First run after the 12:45 publication."
  }
}

run "one_freshness_alarm_per_zone" {
  command = plan

  assert {
    condition     = toset(keys(aws_cloudwatch_metric_alarm.freshness)) == toset(["FR", "DE-LU", "BE", "NL", "ES"])
    error_message = "Every ingested zone needs a freshness alarm."
  }

  assert {
    condition     = aws_glue_catalog_table.day_ahead_prices.parameters["projection.bidding_zone.values"] == "FR,DE-LU,BE,NL,ES"
    error_message = "Athena partition projection must list every zone."
  }
}

run "mutable_tags_are_rejected" {
  command = plan

  variables {
    image_tag = "latest"
  }

  expect_failures = [var.image_tag]
}
