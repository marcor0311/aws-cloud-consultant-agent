locals {
  common_tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "Terraform"
    CatalogCase = "mercedes-benz-canada-vehicle-showroom"
  }
}

module "http_api" {
  source               = "../../../../../baseline-modules/aws-http-api/versions/1.0.0"
  name                 = "${var.project_name}-${var.environment}-api"
  lambda_function_name = var.lambda_function_name
  lambda_invoke_arn    = var.lambda_invoke_arn
  tags                 = local.common_tags
}

module "object_storage" {
  source             = "../../../../../baseline-modules/aws-private-object-storage/versions/1.0.0"
  bucket_name        = var.bucket_name
  versioning_enabled = true
  tags               = local.common_tags
}

module "application_data" {
  source     = "../../../../../baseline-modules/aws-dynamodb-single-table/versions/1.0.0"
  table_name = "${var.project_name}-${var.environment}-data"
  tags       = local.common_tags
}
