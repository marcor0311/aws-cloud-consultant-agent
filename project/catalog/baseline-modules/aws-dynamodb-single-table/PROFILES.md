# Baseline profiles — aws-dynamodb-single-table

Each profile is a complete example root module under `examples/profiles/`. It pins the module snapshot, declares environment inputs, and documents a named baseline configuration. Select the profile matching measured load and service requirements; document and review project-specific deviations.

| Profile | Class/pattern | Example |
|---|---|---|
| `provisioned_50_rcu_25_wcu` | `small` | [`examples/profiles/provisioned_50_rcu_25_wcu`](examples/profiles/provisioned_50_rcu_25_wcu/README.md) |
| `provisioned_250_rcu_100_wcu` | `medium` | [`examples/profiles/provisioned_250_rcu_100_wcu`](examples/profiles/provisioned_250_rcu_100_wcu/README.md) |
| `provisioned_1000_rcu_500_wcu` | `large` | [`examples/profiles/provisioned_1000_rcu_500_wcu`](examples/profiles/provisioned_1000_rcu_500_wcu/README.md) |
| `provisioned_5000_rcu_2500_wcu` | `extra_large` | [`examples/profiles/provisioned_5000_rcu_2500_wcu`](examples/profiles/provisioned_5000_rcu_2500_wcu/README.md) |
| `on_demand` | `elastic` | [`examples/profiles/on_demand`](examples/profiles/on_demand/README.md) |

Values are design presets only. They require workload, quota, security, recovery, and cost review before production use.
