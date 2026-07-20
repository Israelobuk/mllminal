param(
    [switch]$EnableStartup,
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
    installed_at = [DateTime]::UtcNow.ToString("o")
} | ConvertTo-Json
$firstRun | Set-Content -LiteralPath (Join-Path $DataDirectory "first-run.json") -Encoding utf8

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
