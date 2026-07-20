param(
    [string]$DataDirectory = "$env:LOCALAPPDATA\MLLminal",
    [string]$OutputPath = (Join-Path (Get-Location) "mllminal-diagnostics.zip")
)

$ErrorActionPreference = "Stop"
$temp = Join-Path $env:TEMP ("mllminal-diagnostics-" + [Guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Force -Path $temp | Out-Null
try {
    foreach ($name in @("mllminal.log", "first-run.json", "mil-provider.json")) {
        $source = Join-Path $DataDirectory $name
        if (Test-Path -LiteralPath $source) { Copy-Item -LiteralPath $source -Destination $temp }
    }
    Get-ComputerInfo -Property WindowsProductName,WindowsVersion,OsBuildNumber | Out-File (Join-Path $temp "windows.txt")
    $python = Join-Path $env:LOCALAPPDATA "MLLminal\venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $python) {
        & $python -m mllminal system hardware 2>&1 | Out-File (Join-Path $temp "hardware.txt")
    } else {
        "MLLminal runtime not found" | Out-File (Join-Path $temp "hardware.txt")
    }
    if (Test-Path -LiteralPath $OutputPath) { Remove-Item -LiteralPath $OutputPath -Force }
    Compress-Archive -Path (Join-Path $temp "*") -DestinationPath $OutputPath
    Write-Output "Diagnostics exported to $OutputPath. Tokens, databases, and credentials are excluded."
} finally {
    if (Test-Path -LiteralPath $temp) { Remove-Item -LiteralPath $temp -Recurse -Force }
}
