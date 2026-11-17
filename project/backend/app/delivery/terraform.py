"""Generate Terraform for the pinned S3 integration scenario."""

import json

from app.delivery.models import DemoRequest


def terraform_files(request: DemoRequest) -> dict[str, bytes]:
    architecture = request.architecture
    source = f"git::{architecture.baseline.repository}//aws/s3?ref={architecture.baseline.commit}"
    main = f'''# DEMO: baseline pendiente de aprobación. No desplegar sin revisión.
terraform {{
  required_version = ">= 1.9.0, < 2.0.0"
  required_providers {{
    aws = {{
      source  = "hashicorp/aws"
      version = ">= 6.71.0, < 7.0.0"
    }}
  }}
}}

provider "aws" {{
  region = var.region
}}

module "documents" {{
  source = "{source}"

  bucket_name = var.bucket_name
  kms_key_arn = var.kms_key_arn
  tags = {{
    Project     = "{request.project_id}"
    Environment = "{architecture.environment}"
    Owner       = "demo"
    CostCenter  = "PSWE07"
  }}
}}

output "bucket_id" {{
  value = module.documents.bucket_id
}}
'''
    variables = """variable "region" {
  type = string
}

variable "bucket_name" {
  type = string
}

variable "kms_key_arn" {
  type = string
}
"""
    values = {
        "region": architecture.region,
        "bucket_name": architecture.bucket_name,
        "kms_key_arn": architecture.kms_key_arn,
    }
    example = (
        "# Valores simulados. No constituyen accesos ni recursos existentes.\n"
        + "\n".join(f"{key} = {json.dumps(value)}" for key, value in values.items())
        + "\n"
    )
    return {
        "main.tf": main.encode(),
        "variables.tf": variables.encode(),
        "terraform.tfvars.example": example.encode(),
    }
