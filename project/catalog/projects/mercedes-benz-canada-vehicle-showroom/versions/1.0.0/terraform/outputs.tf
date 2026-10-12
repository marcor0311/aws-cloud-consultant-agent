output "api_endpoint" {
  description = "HTTP API invoke URL."
  value       = module.http_api.api_endpoint
}

output "object_bucket_name" {
  description = "Private S3 bucket name."
  value       = module.object_storage.bucket_name
}

output "data_table_name" {
  description = "DynamoDB data table name."
  value       = module.application_data.table_name
}
