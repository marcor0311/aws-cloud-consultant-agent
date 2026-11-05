provider "aws" {
  region = var.aws_region
}

module "baseline" {
  source = "../../../versions/1.1.0"

  bucket_name                        = var.bucket_name
  versioning_enabled                 = true
  noncurrent_version_expiration_days = 90
  cors_allowed_origins               = var.cors_allowed_origins
  kms_key_arn                        = var.kms_key_arn
  tags                               = var.tags
}
