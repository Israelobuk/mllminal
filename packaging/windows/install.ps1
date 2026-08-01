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
trap {
    $diagnosticsDirectory = Join-Path ([IO.Path]::GetFullPath($DataDirectory)) "..\diagnostics"
    try {
        New-Item -ItemType Directory -Force -Path $diagnosticsDirectory | Out-Null
        Add-Content -LiteralPath (Join-Path $diagnosticsDirectory "install.log") -Value "$(Get-Date -Format o) MLLminal install failed: $($_.Exception.Message)"
    } catch {
        # Preserve the original failure when diagnostics storage is unavailable.
    }
    Write-Error "MLLminal install failed: $($_.Exception.Message)"
    exit 1
}
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

function Stop-OwnedProcesses {
    $ownedRoot = $InstallRoot.TrimEnd("\") + "\"
    $ownedIds = @()
    foreach ($processName in @("mllminald", "mllminal", "mllminal-ui")) {
        Get-Process -Name $processName -ErrorAction SilentlyContinue | ForEach-Object {
            try {
                $processPath = $_.Path
                if ($processPath -and $processPath.StartsWith($ownedRoot, [StringComparison]::OrdinalIgnoreCase)) {
                    $ownedIds += [int]$_.Id
                }
            } catch {
                Write-Output "Could not inspect existing MLLminal process $($_.Id); continuing safely."
            }
        }
    }
    foreach ($processId in @($ownedIds | Select-Object -Unique)) {
        Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
        $deadline = [DateTime]::UtcNow.AddSeconds(10)
        while ((Get-Process -Id $processId -ErrorAction SilentlyContinue) -and [DateTime]::UtcNow -lt $deadline) {
            Start-Sleep -Milliseconds 100
        }
        if (Get-Process -Id $processId -ErrorAction SilentlyContinue) {
            throw "Owned MLLminal process $processId did not exit before repair or update."
        }
    }
}

Stop-OwnedProcesses

& $python -m pip install --disable-pip-version-check --no-index --no-deps --upgrade $wheel.FullName
if ($LASTEXITCODE -ne 0) { throw "The packaged MLLminal wheel could not be installed into the bundled runtime." }

function Add-UserPathEntry([string]$Entry) {
    $current = [Environment]::GetEnvironmentVariable("Path", "User")
    $entries = @($current -split ";" | Where-Object { $_ -and $_.Trim() })
    $normalized = [IO.Path]::GetFullPath($Entry).TrimEnd("\")
    $alreadyPresent = $entries | Where-Object {
        try { [IO.Path]::GetFullPath($_).TrimEnd("\") -ieq $normalized } catch { $false }
    }
    if ($alreadyPresent) {
        return $false
    }
    [Environment]::SetEnvironmentVariable("Path", (($entries + $Entry) -join ";"), "User")
    return $true
}

$scriptDirectory = Split-Path $python -Parent

$pathAdded = Add-UserPathEntry $scriptDirectory
$pathRegistered = $true
$env:MLLMINAL_DATA_DIR = $DataDirectory
$packageVersion = & $python -c "import importlib.metadata; print(importlib.metadata.version('mllminal'))"
if ($LASTEXITCODE -ne 0) { throw "The packaged MLLminal version could not be read." }
$packageVersion = [string]($packageVersion | Select-Object -Last 1)
$packageVersion = $packageVersion.Trim()
if ($packageVersion -notmatch "^\d+(\.\d+)+$") { throw "The packaged MLLminal version is invalid: $packageVersion" }
$installProjection = & $python -c "import json; from pathlib import Path; from mllminal.config import Settings; from mllminal.install_lifecycle import InstallLifecycle; lifecycle=InstallLifecycle(Settings(), app_root=Path(r'$InstallRoot')); mode=lifecycle.install_mode('$packageVersion'); prepared=lifecycle.prepare_update('$packageVersion'); repaired=lifecycle.repair(); print(json.dumps({'mode': mode, 'prepared': prepared, 'repaired': repaired}))"
if ($LASTEXITCODE -ne 0) { throw "Database repair or migration failed. Existing data was backed up before migration." }
Write-Output $installProjection

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
    version = $packageVersion
    app_root = $InstallRoot
    data_root = $DataDirectory
    backup_root = $BackupDirectory
    runtime_root = $runtimeRoot
    path_registered = $pathRegistered
    path_added = [bool]$pathAdded
    startup_enabled = [bool]$EnableStartup
    repaired = [bool]$Repair
    retained_existing_data = [bool]$RetainExistingData
    installed_at = [DateTime]::UtcNow.ToString("o")
}
$manifestPath = Join-Path $DataDirectory "install-manifest.json"
if (Test-Path -LiteralPath $manifestPath) {
    try {
        $existingManifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
        foreach ($property in $existingManifest.PSObject.Properties) {
            if (-not $manifest.Contains($property.Name)) {
                $manifest[$property.Name] = $property.Value
            }
        }
    } catch {
        Write-Output "Existing MLLminal install metadata could not be read; rebuilding the manifest."
    }
}
$manifest | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $manifestPath -Encoding utf8

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

$daemonExecutable = Join-Path $scriptDirectory "mllminald.exe"
if (-not (Test-Path -LiteralPath $daemonExecutable)) {
    throw "The packaged daemon entry point is missing: $daemonExecutable"
}
Write-Output "MLLminal runtime is ready. The daemon starts automatically when Mil, the TUI, or a CLI command opens."
Write-Output "MLLminal installed for the current user. Open MLLminal or Mil from the Start Menu."
