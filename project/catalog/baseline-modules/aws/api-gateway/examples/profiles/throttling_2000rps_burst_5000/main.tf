provider "aws" {
  region = var.aws_region
}

module "baseline" {
  source = "../../../versions/1.1.0"

  name                      = var.api_name
  lambda_function_name      = var.lambda_function_name
  lambda_invoke_arn         = var.lambda_invoke_arn
  throttling_rate_limit     = 2000
  throttling_burst_limit    = 5000
  access_log_retention_days = var.access_log_retention_days
  tags                      = var.tags
}
