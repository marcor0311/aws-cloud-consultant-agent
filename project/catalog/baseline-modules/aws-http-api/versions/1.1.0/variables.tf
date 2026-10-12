variable "name" {
  description = "Name for the HTTP API."
  type        = string
}

variable "lambda_function_name" {
  description = "Name of the existing Lambda function integrated with this API."
  type        = string
}

variable "lambda_invoke_arn" {
  description = "Invoke ARN of the existing Lambda function."
  type        = string
}

variable "tags" {
  description = "Tags applied to supported resources."
  type        = map(string)
  default     = {}
}

variable "access_log_retention_days" {
  description = "CloudWatch access log retention in days."
  type        = number
  default     = 30

  validation {
    condition     = contains([1, 3, 5, 7, 14, 30, 60, 90, 120, 150, 180, 365, 400, 545, 731, 1096, 1827, 2192, 2557, 2922, 3288, 3653], var.access_log_retention_days)
    error_message = "access_log_retention_days must be a supported CloudWatch Logs retention value."
  }
}

variable "throttling_burst_limit" {
  description = "Maximum burst requests for the default route."
  type        = number
  default     = 100

  validation {
    condition     = var.throttling_burst_limit >= 1 && floor(var.throttling_burst_limit) == var.throttling_burst_limit
    error_message = "throttling_burst_limit must be a positive whole number."
  }
}

variable "throttling_rate_limit" {
  description = "Steady-state requests per second for the default route."
  type        = number
  default     = 50

  validation {
    condition     = var.throttling_rate_limit > 0
    error_message = "throttling_rate_limit must be greater than zero."
  }
}
