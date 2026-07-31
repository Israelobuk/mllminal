param(
    [switch]$EnableStartup,
    [switch]$Lightweight,
    [switch]$InstallOptionalProviders,
    [switch]$UseSystemPython,
    [string]$InstallRoot = "$env:LOCALAPPDATA\MLLminal\app",
    [string]$DataDirectory = "$env:LOCALAPPDATA\MLLminal\data"
)

$ErrorActionPreference = "Stop"
$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$runtimeRoot = Join-Path $InstallRoot "runtime"
$wheel = Get-ChildItem (Join-Path $scriptRoot "dist") -Filter "mllminal-*.whl" | Select-Object -First 1
if (-not $wheel) { throw "No MLLminal wheel found under packaging/windows/dist." }

New-Item -ItemType Directory -Force -Path $InstallRoot, $DataDirectory | Out-Null
$bundledCandidates = @(
    (Join-Path $runtimeRoot "Scripts\python.exe"),
    (Join-Path $runtimeRoot "python.exe")
)
$python = $bundledCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $python -and $UseSystemPython) {
    $venv = Join-Path $InstallRoot "venv"
    if (-not (Test-Path (Join-Path $venv "Scripts\python.exe"))) { & py -3.12 -m venv $venv }
    $python = Join-Path $venv "Scripts\python.exe"
}
if (-not $python) { throw "This installer requires the bundled runtime under runtime. Use -UseSystemPython only for development packaging." }
& $python -m pip install --disable-pip-version-check --no-index --upgrade $wheel.FullName
$firstRun = [ordered]@{
    schema_version = 1
    mode = "windows_technical_preview"
    observation_enabled = $false
    temporary_vision_enabled = $false
    model_download_confirmed = $false
    external_submission_enabled = $false
    automatic_execution_enabled = $false
    startup_enabled = [bool]$EnableStartup
    lightweight_mode = [bool]$Lightweight
    optional_provider_consent = [bool]$InstallOptionalProviders
    capability_discovery = "bounded_registered_adapters"
    installed_at = [DateTime]::UtcNow.ToString("o")
} | ConvertTo-Json
$firstRun | Set-Content -LiteralPath (Join-Path $DataDirectory "first-run.json") -Encoding utf8

$isWindows = $env:OS -eq "Windows_NT"
$excelDetected = [bool](Get-Command EXCEL.EXE -ErrorAction SilentlyContinue)
$outlookDetected = [bool](Get-Command OUTLOOK.EXE -ErrorAction SilentlyContinue)
$modernOutlookDetected = [bool](Get-Command olk.exe -ErrorAction SilentlyContinue)
$libreOfficeDetected = [bool](Get-Command soffice.exe -ErrorAction SilentlyContinue)
$portableEnabled = [bool]$InstallOptionalProviders -and -not [bool]$Lightweight

$providerInventory = [ordered]@{
    schema_version = 1
    mode = "windows_technical_preview"
    generated_at = [DateTime]::UtcNow.ToString("o")
    capabilities_are_bounded = $true
    external_submission_supported = $false
    providers = @(
        [ordered]@{
            provider = "windows-observer"
            kind = "native"
            surface = "windows"
            detected = $isWindows
            enabled = $isWindows
            capabilities = @("application.inspect_state", "control.invoke")
            note = "Metadata-only Windows observation and explicitly approved control; raw text, credentials, and screenshots are excluded."
        }
        [ordered]@{
            provider = "workspace-filesystem"
            kind = "bundled"
            surface = "filesystem"
            detected = $true
            enabled = $true
            capabilities = @("filesystem.list", "filesystem.inspect", "filesystem.find_latest", "filesystem.exists", "filesystem.hash", "filesystem.create_folder", "filesystem.rename", "filesystem.copy", "filesystem.move", "filesystem.delete_to_recycle_bin", "filesystem.restore")
            note = "Confined to approved roots with preview, authorization, idempotency, and verification."
        }
        [ordered]@{
            provider = "browser-bridge"
            kind = "browser"
            surface = "browser"
            detected = $false
            enabled = $false
            capabilities = @("application.inspect_state", "control.invoke", "table.read", "draft.create")
            note = "Optional signed-in browser surface; requires explicit extension and domain permission."
        }
        [ordered]@{
            provider = "manual-handoff"
            kind = "manual"
            surface = "user"
            detected = $true
            enabled = $true
            capabilities = @("document.export", "draft.create", "control.invoke")
            note = "Explicit user handoff; no automatic external submission or send action."
        }
        [ordered]@{
            provider = "excel-desktop"
            kind = "optional-native"
            surface = "document"
            detected = $isWindows -and $excelDetected
            enabled = $isWindows -and $excelDetected
            optional = $true
            capabilities = @("spreadsheet.inspect", "spreadsheet.export_pdf")
            note = "Optional provider-specific document surface; Excel-quality rendering requires a detected installation."
        }
        [ordered]@{
            provider = "outlook-classic-drafts"
            kind = "optional-native"
            surface = "draft"
            detected = $isWindows -and $outlookDetected
            enabled = $isWindows -and $outlookDetected
            optional = $true
            capabilities = @("email.create_draft")
            note = "Optional draft-only provider; sending and credential access are not supported."
        }
        [ordered]@{
            provider = "outlook-modern-ui-drafts"
            kind = "optional-native"
            surface = "draft"
            detected = $isWindows -and $modernOutlookDetected
            enabled = $isWindows -and $modernOutlookDetected
            optional = $true
            capabilities = @("email.create_draft")
            note = "Optional UI Automation draft surface; an active visible session may be required."
        }
        [ordered]@{
            provider = "portable-document-renderer"
            kind = "optional-portable"
            surface = "document"
            detected = $isWindows -and $libreOfficeDetected
            enabled = $isWindows -and $libreOfficeDetected -and $portableEnabled
            optional = $true
            consent_required = $true
            capabilities = @("spreadsheet.inspect", "spreadsheet.export_pdf")
            note = "Optional portable provider; never downloaded silently and skipped in lightweight mode."
        }
    )
} | ConvertTo-Json -Depth 8
$providerInventory | Set-Content -LiteralPath (Join-Path $DataDirectory "provider-inventory.json") -Encoding utf8

if ($EnableStartup) {
    $startup = [Environment]::GetFolderPath("Startup")
    $shortcutPath = Join-Path $startup "MLLminal daemon.lnk"
    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($shortcutPath)
    $shortcut.TargetPath = (Join-Path (Split-Path $python -Parent) "mllminald.exe")
    $shortcut.WorkingDirectory = $InstallRoot
    $shortcut.WindowStyle = 7
    $shortcut.Save()
}

Write-Output "MLLminal Windows technical preview installed under $InstallRoot. Observation remains disabled until explicitly enabled."
