output "api_id" {
  description = "Created API Gateway HTTP API identifier."
  value       = module.baseline.api_id
}

output "api_endpoint" {
  description = "Default stage invoke URL."
  value       = module.baseline.api_endpoint
}
