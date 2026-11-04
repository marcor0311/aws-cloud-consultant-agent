output "table_name" {
  description = "Created DynamoDB table name."
  value       = module.baseline.table_name
}

output "table_arn" {
  description = "Created DynamoDB table ARN."
  value       = module.baseline.table_arn
}
