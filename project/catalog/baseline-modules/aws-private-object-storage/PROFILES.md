# Baseline profiles — aws-private-object-storage

Each profile is a complete example root module under `examples/profiles/`. It pins the module snapshot, declares environment inputs, and documents a named baseline configuration. Select the profile matching measured load and service requirements; document and review project-specific deviations.

| Profile | Class/pattern | Example |
|---|---|---|
| `private_ephemeral` | `ephemeral_objects` | [`examples/profiles/private_ephemeral`](examples/profiles/private_ephemeral/README.md) |
| `private_versioned_90d` | `versioned_working_data` | [`examples/profiles/private_versioned_90d`](examples/profiles/private_versioned_90d/README.md) |
| `private_versioned_365d` | `versioned_business_data` | [`examples/profiles/private_versioned_365d`](examples/profiles/private_versioned_365d/README.md) |
| `private_versioned_2555d` | `long_retention_data` | [`examples/profiles/private_versioned_2555d`](examples/profiles/private_versioned_2555d/README.md) |

Values are design presets only. They require workload, quota, security, recovery, and cost review before production use.
