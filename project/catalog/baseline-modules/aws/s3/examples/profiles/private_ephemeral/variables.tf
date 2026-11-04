variable "aws_region" {
  description = "AWS Region approved for this environment."
  type        = string
}

variable "bucket_name" {
  description = "Globally unique S3 bucket name approved for this environment."
  type        = string
}

variable "cors_allowed_origins" {
  description = "Exact allowed browser origins; leave empty when browser access is not required."
  type        = list(string)
  default     = []
}

variable "tags" {
  description = "Organization-required tags for this bucket."
  type        = map(string)
  default     = {}
}

variable "kms_key_arn" {
  description = "Optional approved customer-managed KMS key ARN; null uses SSE-S3."
  type        = string
  default     = null
  nullable    = true
}
