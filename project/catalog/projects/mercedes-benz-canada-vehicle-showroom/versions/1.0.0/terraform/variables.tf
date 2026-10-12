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
