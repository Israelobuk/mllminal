param(
    [switch]$DeleteData,
    [string]$InstallRoot = "$env:LOCALAPPDATA\MLLminal\app",
    [string]$DataDirectory = "$env:LOCALAPPDATA\MLLminal\data",
    [string]$BackupDirectory = "$env:LOCALAPPDATA\MLLminal\backups"
)

$ErrorActionPreference = "Stop"
$InstallRoot = [IO.Path]::GetFullPath($InstallRoot)
$DataDirectory = [IO.Path]::GetFullPath($DataDirectory)
$BackupDirectory = [IO.Path]::GetFullPath($BackupDirectory)

foreach ($processName in @("mllminald", "mllminal", "mllminal-ui")) {
    Get-Process -Name $processName -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
}
Start-Sleep -Milliseconds 500

$scriptDirectory = Join-Path $InstallRoot "runtime\Scripts"
$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
if ($null -ne $userPath) {
    $keptPath = @(
        $userPath -split ";" | Where-Object {
            if (-not $_ -or -not $_.Trim()) { return $false }
            try {
                [IO.Path]::GetFullPath($_).TrimEnd("\") -ine [IO.Path]::GetFullPath($scriptDirectory).TrimEnd("\")
            } catch {
                $true
            }
        }
    )
    [Environment]::SetEnvironmentVariable("Path", ($keptPath -join ";"), "User")
}

$startupShortcut = Join-Path ([Environment]::GetFolderPath("Startup")) "MLLminal daemon.lnk"
if (Test-Path -LiteralPath $startupShortcut) { Remove-Item -LiteralPath $startupShortcut -Force }

$browserHostKeys = @(
    "HKCU:\Software\Google\Chrome\NativeMessagingHosts\com.mllminal.bridge",
    "HKCU:\Software\Microsoft\Edge\NativeMessagingHosts\com.mllminal.bridge",
    "HKCU:\Software\Mozilla\NativeMessagingHosts\com.mllminal.bridge"
)
foreach ($key in $browserHostKeys) {
    if (Test-Path -LiteralPath $key) { Remove-Item -LiteralPath $key -Recurse -Force }
}

if (Test-Path -LiteralPath $InstallRoot) { Remove-Item -LiteralPath $InstallRoot -Recurse -Force }
if ($DeleteData) {
    if ((Split-Path $DataDirectory -Leaf) -ine "data") { throw "Refusing to delete an unscoped data directory." }
    if (Test-Path -LiteralPath $DataDirectory) { Remove-Item -LiteralPath $DataDirectory -Recurse -Force }
    if (Test-Path -LiteralPath $BackupDirectory) { Remove-Item -LiteralPath $BackupDirectory -Recurse -Force }
    Write-Output "MLLminal application and MLLminal-owned local data were deleted. User outputs were not touched."
} else {
    Write-Output "MLLminal application was removed. Local data was retained; run mllminal install purge-data to delete it explicitly."
}