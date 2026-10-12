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
