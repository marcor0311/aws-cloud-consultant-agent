# `provisioned_250_rcu_100_wcu` profile

- Resource: `aws-dynamodb-single-table`
- Profile class: `medium`
- Pinned module snapshot: `1.1.0`
- Purpose: Provisioned capacity for a measured moderate workload.

This example calls the versioned module with this profile's exact Terraform inputs. Replace every `replace-with-*` value and review the security, quota, recovery, cost, and workload requirements before use. The profile is a starting configuration, not a production approval or service guarantee.

## Use

1. Copy `terraform.tfvars.example` to `terraform.tfvars` and fill in approved values.
2. Configure the organization's remote, encrypted, access-controlled Terraform state backend before a production run.
3. Run `terraform init`, `terraform validate`, `terraform plan`, and required policy/security checks from this directory.
4. Obtain the required review and approval before any apply.

Never commit credentials or state files. Authenticate through the organization's approved AWS identity mechanism.
