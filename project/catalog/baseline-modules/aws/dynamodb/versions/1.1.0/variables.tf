variable "table_name" {
  description = "DynamoDB table name."
  type        = string
}

variable "tags" {
  description = "Tags applied to the table."
  type        = map(string)
  default     = {}
}

variable "ttl_attribute_name" {
  description = "Optional TTL attribute name for expiring records; null disables TTL."
  type        = string
  default     = null
  nullable    = true
}

variable "deletion_protection_enabled" {
  description = "Whether DynamoDB deletion protection is enabled."
  type        = bool
  default     = true
}

variable "billing_mode" {
  description = "DynamoDB capacity mode: PAY_PER_REQUEST or PROVISIONED."
  type        = string
  default     = "PAY_PER_REQUEST"

  validation {
    condition     = contains(["PAY_PER_REQUEST", "PROVISIONED"], var.billing_mode)
    error_message = "billing_mode must be PAY_PER_REQUEST or PROVISIONED."
  }
}

variable "read_capacity" {
  description = "Provisioned read capacity units (RCU); required when billing_mode is PROVISIONED."
  type        = number
  default     = null
  nullable    = true

  validation {
    condition     = var.read_capacity == null ? true : (var.read_capacity >= 1 && floor(var.read_capacity) == var.read_capacity)
    error_message = "read_capacity must be a positive whole number when set."
  }
}

variable "write_capacity" {
  description = "Provisioned write capacity units (WCU); required when billing_mode is PROVISIONED."
  type        = number
  default     = null
  nullable    = true

  validation {
    condition     = var.write_capacity == null ? true : (var.write_capacity >= 1 && floor(var.write_capacity) == var.write_capacity)
    error_message = "write_capacity must be a positive whole number when set."
  }
}

variable "kms_key_arn" {
  description = "Optional customer-managed KMS key ARN. Null uses the AWS owned key."
  type        = string
  default     = null
  nullable    = true
}
