param(
    [string]$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")),
    [string]$DistributionDirectory = (Join-Path $PSScriptRoot "dist"),
    [switch]$SkipWheelBuild,
    [switch]$SkipRuntimeBuild
)

$ErrorActionPreference = "Stop"
$ProjectRoot = [IO.Path]::GetFullPath($ProjectRoot)
$DistributionDirectory = [IO.Path]::GetFullPath($DistributionDirectory)
New-Item -ItemType Directory -Force -Path $DistributionDirectory | Out-Null
$existingSetup = Get-Item -LiteralPath (Join-Path $DistributionDirectory "MLLminal-Setup.exe") -ErrorAction SilentlyContinue
$beforeSetupBytes = if ($existingSetup) { [int64]$existingSetup.Length } else { [int64]0 }

$uv = Get-Command uv -ErrorAction SilentlyContinue
if (-not $SkipWheelBuild) {
    if (-not $uv) { throw "uv is required only while building the installer. Install uv or pass -SkipWheelBuild with a prepared wheel." }
    Push-Location $ProjectRoot
    try {
        & $uv.Source build --wheel --out-dir $DistributionDirectory
        if ($LASTEXITCODE -ne 0) { throw "uv could not build the MLLminal wheel." }
    } finally {
        Pop-Location
    }
}

if (-not $SkipRuntimeBuild) {
    & (Join-Path $PSScriptRoot "build-runtime.ps1") -WheelDirectory $DistributionDirectory
    if ($LASTEXITCODE -ne 0) { throw "The bundled runtime could not be staged." }
}
$wheel = Get-ChildItem -LiteralPath $DistributionDirectory -Filter "mllminal-*.whl" -File | Sort-Object LastWriteTime -Descending | Select-Object -First 1
if (-not $wheel) { throw "A packaged MLLminal wheel is required to determine the installer version." }
if ($wheel.BaseName -notmatch '^mllminal-(?<version>\d+(?:\.\d+)+)-') { throw "The MLLminal wheel filename does not contain a supported numeric version: $($wheel.Name)" }
$packageVersion = $Matches.version

$isccPath = $null
$isccCommand = Get-Command iscc -ErrorAction SilentlyContinue
if ($isccCommand) {
    $isccPath = $isccCommand.Source
    if (-not $isccPath) { $isccPath = $isccCommand.Path }
}
if (-not $isccPath) {
    $knownPaths = @(
        "${env:LOCALAPPDATA}\Programs\Inno Setup 6\ISCC.exe",
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
    ) | Where-Object { $_ -and (Test-Path -LiteralPath $_) }
    $isccPath = $knownPaths | Select-Object -First 1
}
if (-not $isccPath) {
    throw "Inno Setup 6 (ISCC.exe) is required to compile the Windows setup executable."
}

& $isccPath "/DMyAppVersion=$packageVersion" (Join-Path $PSScriptRoot "MLLminal.iss")
if ($LASTEXITCODE -ne 0) { throw "Inno Setup could not compile the MLLminal installer." }
$auditPath = Join-Path $PSScriptRoot "package-audit.ps1"
$reportPath = Join-Path $DistributionDirectory "MLLminal-package-audit.json"
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File $auditPath `
    -DistributionDirectory $DistributionDirectory `
    -RuntimeDirectory (Join-Path $PSScriptRoot "runtime") `
    -ReportPath $reportPath `
    -BeforeSetupBytes $beforeSetupBytes
if ($LASTEXITCODE -ne 0) { throw "The installer package audit could not be generated." }
Write-Output (Join-Path $DistributionDirectory "MLLminal-Setup.exe")