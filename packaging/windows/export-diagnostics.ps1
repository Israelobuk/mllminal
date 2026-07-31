param(
    [string]$InstallRoot = "$env:LOCALAPPDATA\MLLminal",
    [string]$DataDirectory = "$env:LOCALAPPDATA\MLLminal",
    [string]$OutputPath = (Join-Path (Get-Location) "mllminal-diagnostics.zip")
)

$ErrorActionPreference = "Stop"
$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$temp = Join-Path $env:TEMP ("mllminal-diagnostics-" + [Guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Force -Path $temp | Out-Null
try {
    foreach ($name in @("mllminal.log", "first-run.json", "provider-inventory.json")) {
        $source = Join-Path $DataDirectory $name
        if (Test-Path -LiteralPath $source) { Copy-Item -LiteralPath $source -Destination $temp }
    }
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $scriptRoot "doctor.ps1") -InstallRoot $InstallRoot -DataDirectory $DataDirectory -OutputPath (Join-Path $temp "doctor.json") | Out-Null
    Get-ComputerInfo -Property WindowsProductName,WindowsVersion,OsBuildNumber | Out-File (Join-Path $temp "windows.txt")
    $python = Join-Path $InstallRoot "venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $python) {
        & $python -m mllminal system hardware 2>&1 | Out-File (Join-Path $temp "hardware.txt")
    } else {
        "MLLminal runtime not found" | Out-File (Join-Path $temp "hardware.txt")
    }
    if (Test-Path -LiteralPath $OutputPath) { Remove-Item -LiteralPath $OutputPath -Force }
    Compress-Archive -Path (Join-Path $temp "*") -DestinationPath $OutputPath
    Write-Output "Diagnostics exported to $OutputPath. Tokens, databases, credentials, and session material are excluded."
} finally {
    if (Test-Path -LiteralPath $temp) { Remove-Item -LiteralPath $temp -Recurse -Force }
}
