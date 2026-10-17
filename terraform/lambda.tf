data "aws_ecr_repository" "app" {
  name = var.ecr_repository_name
}

resource "aws_cloudwatch_log_group" "lambda" {
  name              = "/aws/lambda/${local.name}"
  retention_in_days = 90
}

data "aws_iam_policy_document" "lambda_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "lambda" {
  name               = "${local.name}-lambda"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

data "aws_iam_policy_document" "lambda" {
  statement {
    sid       = "WritePrices"
    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.data.arn}/day_ahead_prices/*"]
  }
  statement {
    sid       = "EncryptObjects"
    actions   = ["kms:GenerateDataKey", "kms:Decrypt"]
    resources = [aws_kms_key.data.arn]
  }
  statement {
    sid       = "Logs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.lambda.arn}:*"]
  }
  statement {
    sid       = "FailedEventsToDlq"
    actions   = ["sqs:SendMessage"]
    resources = [aws_sqs_queue.dlq.arn]
  }
  statement {
    sid       = "Tracing"
    actions   = ["xray:PutTraceSegments", "xray:PutTelemetryRecords"]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "lambda" {
  name   = "ingest"
  role   = aws_iam_role.lambda.id
  policy = data.aws_iam_policy_document.lambda.json
}

resource "aws_lambda_function" "ingest" {
  function_name = local.name
  description   = "Day-ahead electricity prices -> S3 Parquet"
  role          = aws_iam_role.lambda.arn
  package_type  = "Image"
  image_uri     = "${data.aws_ecr_repository.app.repository_url}:${var.image_tag}"
  architectures = ["arm64"]
  memory_size   = 512
  timeout       = 300

  # Never more than one run at a time: protects the source API's rate limit
  # and avoids two runs writing the same partition concurrently.
  reserved_concurrent_executions = 1

  environment {
    variables = {
      DATA_BUCKET           = aws_s3_bucket.data.bucket
      DATA_PREFIX           = "day_ahead_prices"
      BIDDING_ZONES         = join(",", var.bidding_zones)
      PAUSE_BETWEEN_CALLS_S = "3"
    }
  }

  logging_config {
    log_format = "Text" # EMF metric lines must stay raw JSON on stdout
    log_group  = aws_cloudwatch_log_group.lambda.name
  }

  tracing_config {
    mode = "Active"
  }

  depends_on = [aws_iam_role_policy.lambda]
}

# Asynchronous invocations (from the scheduler): 2 Lambda retries, then the
# event lands in the DLQ with the error, ready to be replayed.
resource "aws_lambda_function_event_invoke_config" "ingest" {
  function_name                = aws_lambda_function.ingest.function_name
  maximum_retry_attempts       = 2
  maximum_event_age_in_seconds = 3600

  destination_config {
    on_failure {
      destination = aws_sqs_queue.dlq.arn
    }
  }
}

resource "aws_sqs_queue" "dlq" {
  name                              = "${local.name}-dlq"
  message_retention_seconds         = 1209600 # 14 days
  kms_master_key_id                 = aws_kms_key.data.arn
  kms_data_key_reuse_period_seconds = 3600
}
