variable "project_name" {
  description = "Short project identifier used in names and tags."
  type        = string
}

variable "environment" {
  description = "Deployment environment name."
  type        = string
}

variable "region" {
  description = "AWS Region for the resources."
  type        = string
}

variable "lambda_function_name" {
  description = "Name of the existing application Lambda function."
  type        = string
}

variable "lambda_invoke_arn" {
  description = "Invoke ARN of the existing application Lambda function."
  type        = string
}

variable "bucket_name" {
  description = "Globally unique S3 bucket name approved for this environment."
  type        = string
}

variable "cors_allowed_origins" {
  description = "Exact approved web origins; leave empty until the UI hostname is known."
  type        = list(string)
  default     = []
}

variable "noncurrent_version_expiration_days" {
  description = "Optional noncurrent S3 version retention; null disables expiration."
  type        = number
  default     = null
  nullable    = true
}

variable "ttl_attribute_name" {
  description = "Optional attribute for expiring temporary records; null disables TTL."
  type        = string
  default     = null
  nullable    = true
}

variable "s3_kms_key_arn" {
  description = "Optional approved KMS key ARN for S3; null uses SSE-S3."
  type        = string
  default     = null
  nullable    = true
}

variable "dynamodb_kms_key_arn" {
  description = "Optional approved KMS key ARN for DynamoDB; null uses the AWS owned key."
  type        = string
  default     = null
  nullable    = true
}
