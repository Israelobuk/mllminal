param(
    [switch]$DeleteData,
    [string]$InstallRoot = "$env:LOCALAPPDATA\MLLminal",
    [string]$DataDirectory = "$env:LOCALAPPDATA\MLLminal"
)

$ErrorActionPreference = "Stop"
$startupShortcut = Join-Path ([Environment]::GetFolderPath("Startup")) "MLLminal daemon.lnk"
if (Test-Path -LiteralPath $startupShortcut) { Remove-Item -LiteralPath $startupShortcut -Force }
if (Test-Path -LiteralPath $InstallRoot) { Remove-Item -LiteralPath $InstallRoot -Recurse -Force }
if ($DeleteData -and (Test-Path -LiteralPath $DataDirectory)) {
    Remove-Item -LiteralPath $DataDirectory -Recurse -Force
    Write-Output "MLLminal application and local data were deleted."
} else {
    Write-Output "MLLminal application was removed. Local data was retained; rerun with -DeleteData to delete history."
}
