output "bucket_name" {
  description = "Created private S3 bucket name."
  value       = module.baseline.bucket_name
}

output "bucket_arn" {
  description = "Created private S3 bucket ARN."
  value       = module.baseline.bucket_arn
}
