param(
    [switch]$DeleteData,
    [string]$InstallRoot = "$env:LOCALAPPDATA\MLLminal\app",
    [string]$DataDirectory = "$env:LOCALAPPDATA\MLLminal\data"
)

$ErrorActionPreference = "Stop"
foreach ($processName in @("mllminald", "mllminal", "mllminal-ui")) {
    Get-Process -Name $processName -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
}
Start-Sleep -Milliseconds 250
$startupShortcut = Join-Path ([Environment]::GetFolderPath("Startup")) "MLLminal daemon.lnk"
if (Test-Path -LiteralPath $startupShortcut) { Remove-Item -LiteralPath $startupShortcut -Force }
if (Test-Path -LiteralPath $InstallRoot) { Remove-Item -LiteralPath $InstallRoot -Recurse -Force }
if ($DeleteData -and (Test-Path -LiteralPath $DataDirectory)) {
    Remove-Item -LiteralPath $DataDirectory -Recurse -Force
    Write-Output "MLLminal application and local data were deleted."
} else {
    Write-Output "MLLminal application was removed. Local data was retained; rerun with -DeleteData to delete history."
}
