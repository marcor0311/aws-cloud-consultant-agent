variable "bucket_name" {
  description = "Globally unique S3 bucket name."
  type        = string
}

variable "versioning_enabled" {
  description = "Whether object versioning is enabled."
  type        = bool
  default     = true
}

variable "tags" {
  description = "Tags applied to supported resources."
  type        = map(string)
  default     = {}
}
