provider "aws" {
  region = var.aws_region
}

module "baseline" {
  source = "../../../versions/1.1.0"

  table_name                  = var.table_name
  ttl_attribute_name          = var.ttl_attribute_name
  billing_mode                = "PAY_PER_REQUEST"
  read_capacity               = null
  write_capacity              = null
  deletion_protection_enabled = true
  kms_key_arn                 = var.kms_key_arn
  tags                        = var.tags
}
