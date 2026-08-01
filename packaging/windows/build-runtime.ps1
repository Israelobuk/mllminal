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
& $python -m pip install --disable-pip-version-check --no-deps --force-reinstall $wheel.FullName
if ($LASTEXITCODE -ne 0) { throw "Unable to refresh the MLLminal package in the release runtime." }

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

# Remove only known development debris. Keep installed package data and entry points intact.
$debrisDirectories = Get-ChildItem -LiteralPath $RuntimeDirectory -Directory -Recurse -Force |
    Where-Object { $_.Name -in @("__pycache__", ".pytest_cache", "tests") } |
    Sort-Object FullName -Descending
foreach ($directory in $debrisDirectories) {
    Remove-Item -LiteralPath $directory.FullName -Recurse -Force
}
$debrisFiles = Get-ChildItem -LiteralPath $RuntimeDirectory -File -Recurse -Force |
    Where-Object { $_.Name -like "*.pyc" -or $_.Name -like "*.pyo" -or $_.Name -like "*.map" }
foreach ($file in $debrisFiles) {
    Remove-Item -LiteralPath $file.FullName -Force
}
# Remove package-only trees that are not imported by local inference. Keep the top-level
# torch license file and all executable/runtime modules; these source trees otherwise
# dominate package size and exceed classic Windows installer path limits.
$sitePackages = Join-Path $RuntimeDirectory "Lib\site-packages"
$packageOnlyDirectories = @(
    (Join-Path $sitePackages "torch\include"),
    (Get-ChildItem -LiteralPath $sitePackages -Directory -Filter "torch-*.dist-info" -ErrorAction SilentlyContinue |
        ForEach-Object { Join-Path $_.FullName "licenses\third_party" })
)
foreach ($directoryPath in $packageOnlyDirectories) {
    if (Test-Path -LiteralPath $directoryPath) {
        Remove-Item -LiteralPath $directoryPath -Recurse -Force
    }
}
Write-Output "Runtime cleanup complete: removed known development debris and package-only trees."
Write-Output "Bundled runtime ready at $RuntimeDirectory"