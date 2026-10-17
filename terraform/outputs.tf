output "function_name" {
  value = aws_lambda_function.ingest.function_name
}

output "data_bucket" {
  value = aws_s3_bucket.data.bucket
}

output "dlq_url" {
  value = aws_sqs_queue.dlq.url
}

output "athena_workgroup" {
  value = aws_athena_workgroup.market.name
}

output "athena_table" {
  value = "${aws_glue_catalog_database.market.name}.${aws_glue_catalog_table.day_ahead_prices.name}"
}
