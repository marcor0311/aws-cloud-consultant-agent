provider "aws" {
  region = var.aws_region
}

module "baseline" {
  source = "../../../versions/1.1.0"

  table_name                  = var.table_name
  ttl_attribute_name          = var.ttl_attribute_name
  billing_mode                = "PROVISIONED"
  read_capacity               = 5000
  write_capacity              = 2500
  deletion_protection_enabled = true
  kms_key_arn                 = var.kms_key_arn
  tags                        = var.tags
}
