param(
    [switch]$EnableStartup,
    [switch]$Lightweight,
    [switch]$InstallOptionalProviders,
    [switch]$UseSystemPython,
    [switch]$Repair,
    [switch]$CreateDesktopShortcut,
    [switch]$RetainExistingData,
    [string]$InstallRoot = "$env:LOCALAPPDATA\Programs\MLLminal",
    [string]$DataDirectory = "$env:LOCALAPPDATA\MLLminal\data",
    [string]$BackupDirectory = "$env:LOCALAPPDATA\MLLminal\backups"
)

$ErrorActionPreference = "Stop"
$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$InstallRoot = [IO.Path]::GetFullPath($InstallRoot)
$DataDirectory = [IO.Path]::GetFullPath($DataDirectory)
$BackupDirectory = [IO.Path]::GetFullPath($BackupDirectory)
$runtimeRoot = Join-Path $InstallRoot "runtime"
$wheel = Get-ChildItem -LiteralPath (Join-Path $scriptRoot "dist") -Filter "mllminal-*.whl" | Sort-Object LastWriteTime -Descending | Select-Object -First 1
if (-not $wheel) { throw "No MLLminal wheel found under packaging/windows/dist." }

New-Item -ItemType Directory -Force -Path $InstallRoot, $DataDirectory, $BackupDirectory | Out-Null
$bundledCandidates = @(
    (Join-Path $runtimeRoot "Scripts\python.exe"),
    (Join-Path $runtimeRoot "python.exe")
)
$python = $bundledCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $python -and $UseSystemPython) {
    $venv = Join-Path $InstallRoot "venv"
    if (-not (Test-Path -LiteralPath (Join-Path $venv "Scripts\python.exe"))) {
        $launcher = Get-Command py -ErrorAction SilentlyContinue
        if (-not $launcher) { throw "Python 3.12 is required only for development fallback packaging." }
        & $launcher.Source -3.12 -m venv $venv
    }
    $python = Join-Path $venv "Scripts\python.exe"
}
if (-not $python) { throw "This installer requires the bundled runtime under runtime. Use -UseSystemPython only for development packaging." }

& $python -m pip install --disable-pip-version-check --no-index --no-deps --upgrade $wheel.FullName
if ($LASTEXITCODE -ne 0) { throw "The packaged MLLminal wheel could not be installed into the bundled runtime." }

function Add-UserPathEntry([string]$Entry) {
    $current = [Environment]::GetEnvironmentVariable("Path", "User")
    $entries = @($current -split ";" | Where-Object { $_ -and $_.Trim() })
    $normalized = [IO.Path]::GetFullPath($Entry).TrimEnd("\")
    $alreadyPresent = $entries | Where-Object {
        try { [IO.Path]::GetFullPath($_).TrimEnd("\") -ieq $normalized } catch { $false }
    }
    if (-not $alreadyPresent) {
        [Environment]::SetEnvironmentVariable("Path", (($entries + $Entry) -join ";"), "User")
    }
    return $true
}

$scriptDirectory = Split-Path $python -Parent
$pathRegistered = Add-UserPathEntry $scriptDirectory
$env:MLLMINAL_DATA_DIR = $DataDirectory
& $python -c "from pathlib import Path; from mllminal.config import Settings; from mllminal.install_lifecycle import InstallLifecycle; InstallLifecycle(Settings(), app_root=Path(r'$InstallRoot')).repair()"
if ($LASTEXITCODE -ne 0) { throw "Database repair or migration failed. Existing data was backed up before migration." }

$firstRunPath = Join-Path $DataDirectory "first-run.json"
if (-not (Test-Path -LiteralPath $firstRunPath)) {
    [ordered]@{
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
    } | ConvertTo-Json | Set-Content -LiteralPath $firstRunPath -Encoding utf8
}
$inventoryPath = Join-Path $DataDirectory "provider-inventory.json"
if (-not (Test-Path -LiteralPath $inventoryPath)) {
    [ordered]@{
        schema_version = 1
        mode = "windows_technical_preview"
        generated_at = [DateTime]::UtcNow.ToString("o")
        capabilities_are_bounded = $true
        external_submission_supported = $false
        providers = @(
            [ordered]@{ provider = "windows-observer"; kind = "native"; enabled = $true; capabilities = @("application.inspect_state", "control.invoke") }
            [ordered]@{ provider = "workspace-filesystem"; kind = "bundled"; enabled = $true; capabilities = @("filesystem.list", "filesystem.inspect", "filesystem.find_latest", "filesystem.exists", "filesystem.hash", "filesystem.create_folder", "filesystem.rename", "filesystem.copy", "filesystem.move", "filesystem.delete_to_recycle_bin", "filesystem.restore") }
            [ordered]@{ provider = "browser-bridge"; kind = "browser"; enabled = $false; capabilities = @("application.inspect_state", "control.invoke", "table.read", "draft.create") }
            [ordered]@{ provider = "manual-handoff"; kind = "manual"; enabled = $true; capabilities = @("document.export", "draft.create", "control.invoke") }
        )
    } | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $inventoryPath -Encoding utf8
}

$manifest = [ordered]@{
    schema_version = 1
    version = "0.1.0"
    app_root = $InstallRoot
    data_root = $DataDirectory
    backup_root = $BackupDirectory
    runtime_root = $runtimeRoot
    path_registered = $pathRegistered
    startup_enabled = [bool]$EnableStartup
    repaired = [bool]$Repair
    retained_existing_data = [bool]$RetainExistingData
    installed_at = [DateTime]::UtcNow.ToString("o")
}
$manifest | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $DataDirectory "install-manifest.json") -Encoding utf8

if ($EnableStartup) {
    $startup = [Environment]::GetFolderPath("Startup")
    $shortcutPath = Join-Path $startup "MLLminal daemon.lnk"
    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($shortcutPath)
    $shortcut.TargetPath = (Join-Path $scriptDirectory "mllminald.exe")
    $shortcut.WorkingDirectory = $InstallRoot
    $shortcut.WindowStyle = 7
    $shortcut.Save()
}

if ($CreateDesktopShortcut) {
    $desktopShortcut = Join-Path ([Environment]::GetFolderPath("Desktop")) "MLLminal.lnk"
    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($desktopShortcut)
    $shortcut.TargetPath = Join-Path $scriptDirectory "mllminal.exe"
    $shortcut.Arguments = "tui"
    $shortcut.WorkingDirectory = $InstallRoot
    $shortcut.Save()
}

$readiness = & $python -c "import asyncio; from mllminal.config import Settings; from mllminal.service_lifecycle import ensure_daemon; print(asyncio.run(ensure_daemon(Settings())))"
if ($LASTEXITCODE -ne 0) {
    throw "MLLminal could not start its local service. Your files were not changed. Open Diagnostics under $($DataDirectory | Split-Path -Parent)\\diagnostics."
}
Write-Output "MLLminal local service is ready: $readiness"
Write-Output "MLLminal installed for the current user. Open MLLminal or Mil from the Start Menu."