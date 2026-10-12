# Resource baselines and Terraform modules

Each top-level directory identifies a resource baseline. Profiles are executable Terraform example root modules under that resource's `examples/profiles/`; each selects a named technical configuration and pins the versioned child module snapshot. Module versions track code/API changes. Profiles track default resource settings. A profile is not a module release.

| Resource baseline | Profiles |
|---|---|
| `aws-dynamodb-single-table` | DynamoDB billing mode and technical read/write capacity units (RCU/WCU), including on-demand |
| `aws-http-api` | HTTP API stage throttling rate and burst presets |
| `aws-private-object-storage` | S3 versioning and noncurrent-object retention patterns |

The profiles are starting configurations, not guaranteed capacity tiers. Use measured workloads, regional quotas, cost estimates, resilience requirements, and security review to choose and adjust them. Extraordinary requirements stay explicit module inputs (for example KMS key ARNs, TTL, or approved CORS origins) and must be reviewed and recorded in the consuming project.

## Production use gates

Before a module or profile is approved for production: pin Terraform/provider/module versions; configure remote encrypted state and approved identity; run formatting, initialization, validation, plan, module tests, security/policy scans, and cost review in CI; review the plan and architecture; record approval and rollback/recovery ownership. These catalog entries remain drafts until evidence is recorded. Example directories are not production workspaces and do not configure an organization's backend or credentials.

## MCP access

The project's read-only Consultant MCP exposes this catalog through three tools:

| Tool | Use |
|---|---|
| `list_baseline_modules` | List resource baselines, version status, and their named technical profiles. |
| `get_baseline_module` | Read one module's purpose, profile catalog, version notes, and audit record. Accepts an optional cataloged version. |
| `get_baseline_profile` | Read one profile's class, pinned module version, documentation, and Terraform example files. |

The server reads this directory at runtime. Run it from `project/` with `python -m app.mcp_server`; it serves Streamable HTTP on port `8001`. These tools only read catalog files. They do not run Terraform, access AWS credentials, or apply infrastructure. Draft status and production review gates are included in responses so an agent can distinguish a reference profile from an approved production baseline.
