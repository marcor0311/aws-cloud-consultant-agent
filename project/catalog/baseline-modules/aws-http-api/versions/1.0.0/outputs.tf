output "api_id" {
  description = "API Gateway HTTP API identifier."
  value       = aws_apigatewayv2_api.this.id
}

output "api_endpoint" {
  description = "Default stage invoke URL."
  value       = aws_apigatewayv2_api.this.api_endpoint
}
