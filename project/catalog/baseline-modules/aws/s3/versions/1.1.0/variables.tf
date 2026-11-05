variable "bucket_name" {
  description = "Globally unique S3 bucket name."
  type        = string
}

variable "versioning_enabled" {
  description = "Whether object versioning is enabled."
  type        = bool
  default     = true
}

variable "kms_key_arn" {
  description = "Optional customer-managed KMS key ARN. Null uses SSE-S3."
  type        = string
  default     = null
  nullable    = true
}

variable "tags" {
  description = "Tags applied to supported resources."
  type        = map(string)
  default     = {}
}

variable "noncurrent_version_expiration_days" {
  description = "Optional retention in days for noncurrent object versions; null disables expiration."
  type        = number
  default     = null
  nullable    = true

  validation {
    condition     = var.noncurrent_version_expiration_days == null ? true : (var.noncurrent_version_expiration_days >= 1 && floor(var.noncurrent_version_expiration_days) == var.noncurrent_version_expiration_days)
    error_message = "noncurrent_version_expiration_days must be a positive whole number when set."
  }
}

variable "cors_allowed_origins" {
  description = "Exact browser origins allowed for object requests; empty disables CORS."
  type        = list(string)
  default     = []
}
