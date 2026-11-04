resource "aws_dynamodb_table" "this" {
  name                        = var.table_name
  billing_mode                = var.billing_mode
  read_capacity               = var.billing_mode == "PROVISIONED" ? var.read_capacity : null
  write_capacity              = var.billing_mode == "PROVISIONED" ? var.write_capacity : null
  hash_key                    = "pk"
  range_key                   = "sk"
  deletion_protection_enabled = var.deletion_protection_enabled

  lifecycle {
    precondition {
      condition     = var.billing_mode == "PROVISIONED" ? (var.read_capacity == null ? false : var.read_capacity >= 1) : true
      error_message = "Set read_capacity to at least 1 when billing_mode is PROVISIONED."
    }

    precondition {
      condition     = var.billing_mode == "PROVISIONED" ? (var.write_capacity == null ? false : var.write_capacity >= 1) : true
      error_message = "Set write_capacity to at least 1 when billing_mode is PROVISIONED."
    }
  }

  attribute {
    name = "pk"
    type = "S"
  }

  attribute {
    name = "sk"
    type = "S"
  }

  point_in_time_recovery {
    enabled = true
  }

  server_side_encryption {
    enabled     = true
    kms_key_arn = var.kms_key_arn
  }

  dynamic "ttl" {
    for_each = var.ttl_attribute_name == null ? [] : [var.ttl_attribute_name]
    content {
      attribute_name = ttl.value
      enabled        = true
    }
  }

  tags = var.tags
}
