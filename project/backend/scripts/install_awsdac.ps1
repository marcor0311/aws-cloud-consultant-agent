[CmdletBinding()]
param(
    [switch]$Force
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$backendRoot = Split-Path -Parent $PSScriptRoot
$dependencyFile = Join-Path $backendRoot "tools/awsdac/dependencies.json"
if (-not (Test-Path -LiteralPath $dependencyFile -PathType Leaf)) {
    throw "No se encontró el manifiesto de dependencias: $dependencyFile"
}

$dependency = Get-Content -LiteralPath $dependencyFile -Raw | ConvertFrom-Json
if ($dependency.schema_version -ne 1) {
    throw "Versión desconocida del manifiesto awsdac."
}

$runtime = [System.Runtime.InteropServices.RuntimeInformation]
if ($runtime::IsOSPlatform([System.Runtime.InteropServices.OSPlatform]::Windows)) {
    $operatingSystem = "windows"
    $executableName = "awsdac.exe"
}
elseif ($runtime::IsOSPlatform([System.Runtime.InteropServices.OSPlatform]::Linux)) {
    $operatingSystem = "linux"
    $executableName = "awsdac"
}
elseif ($runtime::IsOSPlatform([System.Runtime.InteropServices.OSPlatform]::OSX)) {
    $operatingSystem = "darwin"
    $executableName = "awsdac"
}
else {
    throw "Sistema operativo no soportado por el instalador de awsdac."
}

$architecture = switch ($runtime::OSArchitecture.ToString()) {
    "X64" { "amd64" }
    "X86" { "386" }
    "Arm" { "arm" }
    "Arm64" { "arm64" }
    default { throw "Arquitectura no soportada: $($runtime::OSArchitecture)" }
}

$platform = "$operatingSystem-$architecture"
$asset = $dependency.assets.PSObject.Properties[$platform].Value
if ($null -eq $asset) {
    throw "No existe un asset awsdac $($dependency.release_tag) para $platform."
}

$versionDirectory = Join-Path $backendRoot "tools/awsdac/v$($dependency.version)"
$packageName = [System.IO.Path]::GetFileNameWithoutExtension($asset.filename)
$executable = Join-Path $versionDirectory "dist/$packageName/$executableName"
$expectedVersion = "v$($dependency.version)"

function Assert-AwsDacVersion {
    param([Parameter(Mandatory)][string]$Path)

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "No se encontró el ejecutable awsdac esperado: $Path"
    }
    $reportedVersion = (& $Path --version 2>&1 | Out-String).Trim()
    if ($LASTEXITCODE -ne 0 -or $reportedVersion -notmatch [regex]::Escape($expectedVersion)) {
        throw "Versión awsdac incompatible: '$reportedVersion'; se requiere $expectedVersion."
    }
    return $reportedVersion
}

if ((-not $Force) -and (Test-Path -LiteralPath $executable -PathType Leaf)) {
    $reportedVersion = Assert-AwsDacVersion -Path $executable
    Write-Host "awsdac ya está instalado: $reportedVersion"
    Write-Host "Ejecutable: $executable"
    exit 0
}

New-Item -ItemType Directory -Force -Path $versionDirectory | Out-Null
$archive = Join-Path $versionDirectory $asset.filename
$downloadUrl = (
    "$($dependency.repository)/releases/download/" +
    "$($dependency.release_tag)/$($asset.filename)"
)

try {
    Write-Host "Descargando $downloadUrl"
    Invoke-WebRequest -Uri $downloadUrl -OutFile $archive
    $actualHash = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actualHash -ne $asset.sha256) {
        throw "SHA-256 inválido para $($asset.filename): $actualHash"
    }

    Expand-Archive -LiteralPath $archive -DestinationPath $versionDirectory -Force
    if ($operatingSystem -ne "windows") {
        & chmod +x $executable
        if ($LASTEXITCODE -ne 0) {
            throw "No se pudo marcar awsdac como ejecutable."
        }
    }
    $reportedVersion = Assert-AwsDacVersion -Path $executable
    Write-Host "Instalación verificada: $reportedVersion"
    Write-Host "Plataforma: $platform"
    Write-Host "Ejecutable: $executable"
}
finally {
    if (Test-Path -LiteralPath $archive -PathType Leaf) {
        Remove-Item -LiteralPath $archive -Force
    }
}
