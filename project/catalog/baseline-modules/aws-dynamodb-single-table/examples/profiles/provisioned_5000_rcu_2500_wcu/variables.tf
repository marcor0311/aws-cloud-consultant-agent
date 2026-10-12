variable "aws_region" {
  description = "AWS Region approved for this environment."
  type        = string
}

variable "table_name" {
  description = "Globally unique name for this DynamoDB table."
  type        = string
}

variable "tags" {
  description = "Organization-required tags for this table."
  type        = map(string)
  default     = {}
}

variable "kms_key_arn" {
  description = "Optional approved customer-managed KMS key ARN; null uses the AWS owned key."
  type        = string
  default     = null
  nullable    = true
}

variable "ttl_attribute_name" {
  description = "Optional approved TTL attribute for expiring records; null disables TTL."
  type        = string
  default     = null
  nullable    = true
}
