param(
    [string]$InstallRoot = "$env:LOCALAPPDATA\MLLminal\app",
    [string]$DataDirectory = "$env:LOCALAPPDATA\MLLminal\data",
    [string]$OutputPath = ""
)

$ErrorActionPreference = "Stop"
$python = Join-Path $InstallRoot "runtime\Scripts\python.exe"
$firstRunPath = Join-Path $DataDirectory "first-run.json"
$inventoryPath = Join-Path $DataDirectory "provider-inventory.json"
$firstRun = $null
$inventory = $null
$providerCount = 0
if (Test-Path -LiteralPath $firstRunPath) {
    $firstRun = Get-Content -LiteralPath $firstRunPath -Raw | ConvertFrom-Json
}
if (Test-Path -LiteralPath $inventoryPath) {
    $inventory = Get-Content -LiteralPath $inventoryPath -Raw | ConvertFrom-Json
    $providerCount = @($inventory.providers).Count
}

$report = [ordered]@{
    product = "MLLminal"
    mode = "windows_technical_preview"
    schema_version = 1
    generated_at = [DateTime]::UtcNow.ToString("o")
    checks = [ordered]@{
        windows = [Environment]::OSVersion.Platform -eq "Win32NT"
        python_runtime = [bool](Test-Path -LiteralPath $python)
        first_run_policy = [bool]($null -ne $firstRun)
        provider_inventory = [bool]($null -ne $inventory)
        daemon_entrypoint = [bool]($null -ne (Get-Command (Join-Path $InstallRoot "runtime\Scripts\mllminald.exe") -ErrorAction SilentlyContinue))
    }
    capability_discovery = [ordered]@{
        mode = "bounded_registered_adapters"
        provider_count = $providerCount
        external_submission_supported = $false
    }
    safety = [ordered]@{
        observation_enabled = if ($null -eq $firstRun) { $false } else { [bool]$firstRun.observation_enabled }
        automatic_execution_enabled = $false
        automatic_model_download = $false
        credentials_exported = $false
        external_submission_enabled = $false
    }
    paths = [ordered]@{
        install_root = $InstallRoot
        data_directory = $DataDirectory
    }
}
$json = $report | ConvertTo-Json -Depth 8
if ($OutputPath) {
    $json | Set-Content -LiteralPath $OutputPath -Encoding utf8
}
Write-Output $json
