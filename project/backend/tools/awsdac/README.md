# awsdac local tool

Block D pins `awslabs/diagram-as-code` to version `0.24`. The versioned
`dependencies.json` manifest records every supported platform asset and its
SHA-256 digest from the official GitHub release API. Binary files and release
archives are intentionally not committed.

For `awsdac-v0.24_windows-amd64.zip`, the GitHub release API reports:

```text
sha256:94023a4cee7c47bae88807440075f99c8f23b52cd01013a4a169972f48fd1c32
```

Install or verify the correct platform dependency from `project/backend/`:

```powershell
.\scripts\install_awsdac.ps1
```

On Linux or macOS with PowerShell 7:

```sh
pwsh ./scripts/install_awsdac.ps1
```

The installer detects the operating system and CPU architecture, downloads only
the asset declared in `dependencies.json`, verifies SHA-256 before extraction,
and checks `awsdac --version`. Re-running it is idempotent. Use `-Force` to
download and verify the archive again.

The application also accepts an explicit verified binary through
`AWSDAC_EXECUTABLE`.

