resource "aws_glue_catalog_database" "market" {
  name = "${local.snake}_market"
}

# Partition projection: new zones/days are queryable immediately, no crawler.
resource "aws_glue_catalog_table" "day_ahead_prices" {
  name          = "day_ahead_prices"
  database_name = aws_glue_catalog_database.market.name
  table_type    = "EXTERNAL_TABLE"

  parameters = {
    classification                           = "parquet"
    "projection.enabled"                     = "true"
    "projection.bidding_zone.type"           = "enum"
    "projection.bidding_zone.values"         = join(",", var.bidding_zones)
    "projection.delivery_date.type"          = "date"
    "projection.delivery_date.format"        = "yyyy-MM-dd"
    "projection.delivery_date.range"         = "2015-01-01,NOW+2DAYS"
    "projection.delivery_date.interval"      = "1"
    "projection.delivery_date.interval.unit" = "DAYS"
    "storage.location.template"              = "s3://${aws_s3_bucket.data.bucket}/day_ahead_prices/bidding_zone=$${bidding_zone}/delivery_date=$${delivery_date}/"
  }

  partition_keys {
    name = "bidding_zone"
    type = "string"
  }
  partition_keys {
    name = "delivery_date"
    type = "date"
  }

  storage_descriptor {
    location      = "s3://${aws_s3_bucket.data.bucket}/day_ahead_prices/"
    input_format  = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetInputFormat"
    output_format = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetOutputFormat"

    ser_de_info {
      serialization_library = "org.apache.hadoop.hive.ql.io.parquet.serde.ParquetHiveSerDe"
    }

    columns {
      name = "delivery_start"
      type = "timestamp"
    }
    columns {
      name = "delivery_end"
      type = "timestamp"
    }
    columns {
      name = "resolution_minutes"
      type = "smallint"
    }
    columns {
      name    = "price_eur_mwh"
      type    = "double"
      comment = "Day-ahead clearing price, EUR/MWh"
    }
    columns {
      name = "source"
      type = "string"
    }
    columns {
      name = "ingested_at"
      type = "timestamp"
    }
  }
}

resource "aws_athena_workgroup" "market" {
  name          = local.name
  force_destroy = true

  configuration {
    enforce_workgroup_configuration    = true
    bytes_scanned_cutoff_per_query     = 1073741824
    publish_cloudwatch_metrics_enabled = true

    result_configuration {
      output_location = "s3://${aws_s3_bucket.data.bucket}/athena-results/"
      encryption_configuration {
        encryption_option = "SSE_KMS"
        kms_key_arn       = aws_kms_key.data.arn
      }
    }
  }
}

resource "aws_athena_named_query" "daily_stats" {
  name      = "daily-price-stats"
  workgroup = aws_athena_workgroup.market.id
  database  = aws_glue_catalog_database.market.name
  query     = file("${path.module}/../sql/daily_price_stats.sql")
}

resource "aws_athena_named_query" "spreads" {
  name      = "fr-de-spread-and-battery-arbitrage"
  workgroup = aws_athena_workgroup.market.id
  database  = aws_glue_catalog_database.market.name
  query     = file("${path.module}/../sql/spread_and_arbitrage.sql")
}
