variable "aws_region" {
  description = "AWS Region approved for this environment."
  type        = string
}

variable "api_name" {
  description = "Name for the HTTP API."
  type        = string
}

variable "lambda_function_name" {
  description = "Name of the existing Lambda integration target."
  type        = string
}

variable "lambda_invoke_arn" {
  description = "Invoke ARN of the existing Lambda integration target."
  type        = string
}

variable "access_log_retention_days" {
  description = "Approved CloudWatch Logs retention period."
  type        = number
  default     = 30
}

variable "tags" {
  description = "Organization-required tags for this API."
  type        = map(string)
  default     = {}
}
