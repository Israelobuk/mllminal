param(
    [string]$RuntimeDirectory = (Join-Path $PSScriptRoot "runtime"),
    [string]$WheelDirectory = (Join-Path $PSScriptRoot "dist")
)

$ErrorActionPreference = "Stop"
$wheel = Get-ChildItem -LiteralPath $WheelDirectory -Filter "mllminal-*.whl" | Sort-Object LastWriteTime -Descending | Select-Object -First 1
if (-not $wheel) { throw "No MLLminal wheel found under $WheelDirectory. Run uv build first." }

New-Item -ItemType Directory -Force -Path $RuntimeDirectory | Out-Null
$python = Join-Path $RuntimeDirectory "Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    $launcher = Get-Command py -ErrorAction SilentlyContinue
    if (-not $launcher) { throw "Python 3.12 launcher 'py' is required only while building the release runtime." }
    & $launcher.Source -3.12 -m venv $RuntimeDirectory
    if ($LASTEXITCODE -ne 0) { throw "Unable to create the bundled Python runtime." }
}
if (-not (Test-Path -LiteralPath $python)) { throw "Bundled runtime creation did not produce runtime\Scripts\python.exe." }

& $python -m pip install --disable-pip-version-check --upgrade $wheel.FullName
if ($LASTEXITCODE -ne 0) { throw "Unable to install MLLminal and its dependencies into the release runtime." }

$required = @(
    "python.exe",
    "mllminal.exe",
    "mllminald.exe",
    "mllminal-ui.exe"
)
foreach ($name in $required) {
    if (-not (Test-Path -LiteralPath (Join-Path (Split-Path $python -Parent) $name))) {
        throw "Bundled runtime is missing entry point $name."
    }
}
Write-Output "Bundled runtime ready at $RuntimeDirectory"