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

$iscc = Get-Command iscc -ErrorAction SilentlyContinue
if (-not $iscc) {
    $knownPaths = @(
        "$env:ProgramFiles(x86)\Inno Setup 6\ISCC.exe",
        "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
    ) | Where-Object { $_ -and (Test-Path -LiteralPath $_) }
    if ($knownPaths) { $iscc = Get-Item -LiteralPath $knownPaths[0] }
}
if (-not $iscc) {
    throw "Inno Setup 6 (ISCC.exe) is required to compile the Windows setup executable."
}

& $iscc.Source (Join-Path $PSScriptRoot "MLLminal.iss")
if ($LASTEXITCODE -ne 0) { throw "Inno Setup could not compile the MLLminal installer." }
Write-Output (Join-Path $DistributionDirectory "MLLminal-Setup.exe")