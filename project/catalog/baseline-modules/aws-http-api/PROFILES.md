# Baseline profiles — aws-http-api

Each profile is a complete example root module under `examples/profiles/`. It pins the module snapshot, declares environment inputs, and documents a named baseline configuration. Select the profile matching measured load and service requirements; document and review project-specific deviations.

| Profile | Class/pattern | Example |
|---|---|---|
| `throttling_25rps_burst_50` | `small` | [`examples/profiles/throttling_25rps_burst_50`](examples/profiles/throttling_25rps_burst_50/README.md) |
| `throttling_100rps_burst_200` | `medium` | [`examples/profiles/throttling_100rps_burst_200`](examples/profiles/throttling_100rps_burst_200/README.md) |
| `throttling_500rps_burst_1000` | `large` | [`examples/profiles/throttling_500rps_burst_1000`](examples/profiles/throttling_500rps_burst_1000/README.md) |
| `throttling_2000rps_burst_5000` | `extra_large` | [`examples/profiles/throttling_2000rps_burst_5000`](examples/profiles/throttling_2000rps_burst_5000/README.md) |

Values are design presets only. They require workload, quota, security, recovery, and cost review before production use.
