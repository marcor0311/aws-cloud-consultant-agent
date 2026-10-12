locals {
  common_tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "Terraform"
    CatalogCase = "verbier-4-vallees-skipass-operations"
  }
}

module "http_api" {
  source                 = "../../../../../baseline-modules/aws-http-api/versions/1.1.0"
  name                   = "${var.project_name}-${var.environment}-api"
  lambda_function_name   = var.lambda_function_name
  lambda_invoke_arn      = var.lambda_invoke_arn
  throttling_rate_limit  = 500
  throttling_burst_limit = 1000
  tags                   = local.common_tags
}

module "object_storage" {
  source                             = "../../../../../baseline-modules/aws-private-object-storage/versions/1.1.0"
  bucket_name                        = var.bucket_name
  versioning_enabled                 = true
  tags                               = local.common_tags
  cors_allowed_origins               = var.cors_allowed_origins
  kms_key_arn                        = var.s3_kms_key_arn
  noncurrent_version_expiration_days = var.noncurrent_version_expiration_days != null ? var.noncurrent_version_expiration_days : 365
}

module "application_data" {
  source             = "../../../../../baseline-modules/aws-dynamodb-single-table/versions/1.1.0"
  table_name         = "${var.project_name}-${var.environment}-data"
  tags               = local.common_tags
  ttl_attribute_name = var.ttl_attribute_name
  kms_key_arn        = var.dynamodb_kms_key_arn
  billing_mode       = "PAY_PER_REQUEST"
  read_capacity      = null
  write_capacity     = null
}
