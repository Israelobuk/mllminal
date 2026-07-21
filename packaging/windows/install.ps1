param(
    [switch]$EnableStartup,
    [switch]$Lightweight,
    [switch]$InstallOptionalProviders,
    [string]$InstallRoot = "$env:LOCALAPPDATA\MLLminal",
    [string]$DataDirectory = "$env:LOCALAPPDATA\MLLminal"
)

$ErrorActionPreference = "Stop"
$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$venv = Join-Path $InstallRoot "venv"
$wheel = Get-ChildItem (Join-Path $scriptRoot "dist") -Filter "mllminal-*.whl" | Select-Object -First 1
if (-not $wheel) { throw "No MLLminal wheel found under packaging/windows/dist." }

New-Item -ItemType Directory -Force -Path $InstallRoot, $DataDirectory | Out-Null
if (-not (Test-Path (Join-Path $venv "Scripts\python.exe"))) {
    & py -3.12 -m venv $venv
}
$python = Join-Path $venv "Scripts\python.exe"
& $python -m pip install --disable-pip-version-check --upgrade $wheel.FullName

$firstRun = @{
    observation_enabled = $false
    temporary_vision_enabled = $false
    model_download_confirmed = $false
    startup_enabled = [bool]$EnableStartup
    lightweight_mode = [bool]$Lightweight
    optional_provider_consent = [bool]$InstallOptionalProviders
    installed_at = [DateTime]::UtcNow.ToString("o")
} | ConvertTo-Json
$firstRun | Set-Content -LiteralPath (Join-Path $DataDirectory "first-run.json") -Encoding utf8

$providerInventory = @(
    [ordered]@{ provider = "excel-desktop"; kind = "native"; detected = [bool](Get-Command EXCEL.EXE -ErrorAction SilentlyContinue); capabilities = @("spreadsheet.inspect", "spreadsheet.export_pdf"); note = "Optional Excel adapter; Excel-quality rendering is only available when Excel is installed." }
    [ordered]@{ provider = "outlook-classic"; kind = "native"; detected = [bool](Get-Command OUTLOOK.EXE -ErrorAction SilentlyContinue); capabilities = @("email.create_draft"); note = "Optional classic Outlook adapter; draft-only." }
    [ordered]@{ provider = "outlook-modern-uia"; kind = "native"; detected = [bool](Get-Command olk.exe -ErrorAction SilentlyContinue); capabilities = @("email.create_draft"); note = "Modern Outlook detected; active UI Automation or browser surface may still be required." }
    [ordered]@{ provider = "libreoffice"; kind = "portable"; detected = [bool](Get-Command soffice.exe -ErrorAction SilentlyContinue); capabilities = @("spreadsheet.inspect", "spreadsheet.export_pdf"); note = "Optional portable renderer; not silently installed." }
    [ordered]@{ provider = "python-spreadsheet-inspection"; kind = "bundled"; detected = $true; capabilities = @("spreadsheet.inspect"); note = "Bundled OOXML metadata inspection; does not reproduce Excel PDF rendering." }
    [ordered]@{ provider = "browser-bridge"; kind = "browser"; detected = $false; capabilities = @("spreadsheet.inspect", "spreadsheet.export_pdf", "email.create_draft"); note = "Enable the signed-in browser extension and grant a domain permission." }
    [ordered]@{ provider = "manual-handoff"; kind = "manual"; detected = $true; capabilities = @("spreadsheet.export_pdf", "email.create_draft"); note = "Always available as an explicit user handoff." }
) | ConvertTo-Json -Depth 5
$providerInventory | Set-Content -LiteralPath (Join-Path $DataDirectory "provider-inventory.json") -Encoding utf8

if ($EnableStartup) {
    $startup = [Environment]::GetFolderPath("Startup")
    $shortcutPath = Join-Path $startup "MLLminal daemon.lnk"
    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($shortcutPath)
    $shortcut.TargetPath = (Join-Path $venv "Scripts\mllminald.exe")
    $shortcut.WorkingDirectory = $InstallRoot
    $shortcut.WindowStyle = 7
    $shortcut.Save()
}

Write-Output "MLLminal installed under $InstallRoot. Observation remains disabled until explicitly enabled."
