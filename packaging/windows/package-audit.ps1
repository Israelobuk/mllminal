param(
    [string]$DistributionDirectory = (Join-Path $PSScriptRoot "dist"),
    [string]$RuntimeDirectory = (Join-Path $PSScriptRoot "runtime"),
    [string]$ReportPath = (Join-Path $DistributionDirectory "MLLminal-package-audit.json"),
    [int64]$BeforeSetupBytes = 0,
    [double]$ColdInstallSeconds = 0,
    [double]$FirstLaunchSeconds = 0,
    [double]$DaemonReadySeconds = 0
)

$ErrorActionPreference = "Stop"
$DistributionDirectory = [IO.Path]::GetFullPath($DistributionDirectory)
$RuntimeDirectory = [IO.Path]::GetFullPath($RuntimeDirectory)
$ReportPath = [IO.Path]::GetFullPath($ReportPath)

$setup = Get-ChildItem -LiteralPath $DistributionDirectory -Filter "MLLminal-Setup.exe" -File | Select-Object -First 1
if (-not $setup) { throw "MLLminal-Setup.exe was not found under $DistributionDirectory." }

$runtimeFiles = @(Get-ChildItem -LiteralPath $RuntimeDirectory -File -Recurse -ErrorAction SilentlyContinue)
$runtimeBytes = [int64](($runtimeFiles | Measure-Object -Property Length -Sum).Sum)
$report = [ordered]@{
    generated_at = [DateTime]::UtcNow.ToString("o")
    compressed_setup_bytes = [int64]$setup.Length
    installer_before_bytes = [int64]$BeforeSetupBytes
    installer_after_bytes = [int64]$setup.Length
    runtime_bytes = $runtimeBytes
    installed_file_count = [int64]$runtimeFiles.Count
    cold_install_seconds = [double]$ColdInstallSeconds
    first_launch_seconds = [double]$FirstLaunchSeconds
    daemon_ready_seconds = [double]$DaemonReadySeconds
}

$reportDirectory = Split-Path -Parent $ReportPath
New-Item -ItemType Directory -Force -Path $reportDirectory | Out-Null
$json = $report | ConvertTo-Json -Depth 4
[IO.File]::WriteAllText($ReportPath, $json + [Environment]::NewLine, [Text.UTF8Encoding]::new($false))
Write-Output $json