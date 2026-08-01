param(
    [switch]$DeleteData,
    [switch]$PromptForData,
    [switch]$Silent,
    [string]$InstallRoot = "$env:LOCALAPPDATA\Programs\MLLminal",
    [string]$DataDirectory = "$env:LOCALAPPDATA\MLLminal\data",
    [string]$BackupDirectory = "$env:LOCALAPPDATA\MLLminal\backups"
)

$ErrorActionPreference = "Stop"
$InstallRoot = [IO.Path]::GetFullPath($InstallRoot)
$DataDirectory = [IO.Path]::GetFullPath($DataDirectory)
$BackupDirectory = [IO.Path]::GetFullPath($BackupDirectory)
$diagnosticsDirectory = Join-Path (Split-Path $DataDirectory -Parent) "diagnostics"
New-Item -ItemType Directory -Force -Path $diagnosticsDirectory | Out-Null
$diagnosticsPath = Join-Path $diagnosticsDirectory "uninstall.log"

function Write-Diagnostic([string]$Message) {
    Add-Content -LiteralPath $diagnosticsPath -Value "$(Get-Date -Format o) $Message"
}

$deleteOwnedData = [bool]$DeleteData
if ($PromptForData -and -not $Silent) {
    try {
        Add-Type -AssemblyName System.Windows.Forms
        Add-Type -AssemblyName System.Drawing
        $form = New-Object System.Windows.Forms.Form
        $form.Text = "Remove MLLminal?"
        $form.Width = 430
        $form.Height = 170
        $form.StartPosition = "CenterScreen"
        $label = New-Object System.Windows.Forms.Label
        $label.Text = "Choose whether to keep MLLminal local data."
        $label.AutoSize = $true
        $label.Left = 18
        $label.Top = 18
        $check = New-Object System.Windows.Forms.CheckBox
        $check.Text = "Also delete MLLminal local data"
        $check.AutoSize = $true
        $check.Left = 18
        $check.Top = 48
        $remove = New-Object System.Windows.Forms.Button
        $remove.Text = "Remove"
        $remove.DialogResult = [System.Windows.Forms.DialogResult]::OK
        $remove.Left = 225
        $remove.Top = 88
        $cancel = New-Object System.Windows.Forms.Button
        $cancel.Text = "Cancel"
        $cancel.DialogResult = [System.Windows.Forms.DialogResult]::Cancel
        $cancel.Left = 310
        $cancel.Top = 88
        $form.AcceptButton = $remove
        $form.CancelButton = $cancel
        $form.Controls.AddRange(@($label, $check, $remove, $cancel))
        $result = $form.ShowDialog()
        if ($result -ne [System.Windows.Forms.DialogResult]::OK) { throw "uninstall cancelled" }
        $deleteOwnedData = [bool]$check.Checked
    } catch [System.Management.Automation.PipelineStoppedException] {
        throw
    } catch {
        if ($_.Exception.Message -eq "uninstall cancelled") { throw }
        Write-Diagnostic "Could not show data-retention choice; retaining local data. $($_.Exception.Message)"
        $deleteOwnedData = $false
    }
}

$ownedRoot = $InstallRoot.TrimEnd("\") + "\"
$ownedProcessIds = New-Object System.Collections.Generic.List[int]
$lockPath = Join-Path $DataDirectory "daemon.lock"
if (Test-Path -LiteralPath $lockPath) {
    try {
        $lock = Get-Content -LiteralPath $lockPath -Raw | ConvertFrom-Json
        if ($lock.pid) { $ownedProcessIds.Add([int]$lock.pid) }
    } catch { Write-Diagnostic "Could not read daemon ownership lock: $($_.Exception.Message)" }
}
foreach ($processName in @("mllminald", "mllminal", "mllminal-ui")) {
    Get-Process -Name $processName -ErrorAction SilentlyContinue | ForEach-Object {
        try {
            $processPath = $_.Path
            if ($processPath -and $processPath.StartsWith($ownedRoot, [StringComparison]::OrdinalIgnoreCase)) {
                $ownedProcessIds.Add([int]$_.Id)
            }
        } catch { Write-Diagnostic "Could not inspect process $($_.Id): $($_.Exception.Message)" }
    }
}
foreach ($processId in @($ownedProcessIds | Select-Object -Unique)) {
    Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
}
Start-Sleep -Milliseconds 500

$scriptDirectory = Join-Path $InstallRoot "runtime\Scripts"
$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
if ($null -ne $userPath) {
    $normalizedScriptDirectory = [IO.Path]::GetFullPath($scriptDirectory).TrimEnd("\")
    $keptPath = @(
        $userPath -split ";" | Where-Object {
            if (-not $_ -or -not $_.Trim()) { return $false }
            try { [IO.Path]::GetFullPath($_).TrimEnd("\") -ine $normalizedScriptDirectory } catch { $true }
        }
    )
    [Environment]::SetEnvironmentVariable("Path", ($keptPath -join ";"), "User")
}

$programsRoot = [Environment]::GetFolderPath("Programs")
$startMenuRoot = Join-Path $programsRoot "MLLminal"
foreach ($shortcutName in @("MLLminal.lnk", "Mil.lnk", "MLLminal Terminal.lnk", "MLLminal Diagnostics.lnk", "Uninstall MLLminal.lnk")) {
    $shortcutPath = Join-Path $startMenuRoot $shortcutName
    if (Test-Path -LiteralPath $shortcutPath) { Remove-Item -LiteralPath $shortcutPath -Force }
}
if (Test-Path -LiteralPath $startMenuRoot) { Remove-Item -LiteralPath $startMenuRoot -Recurse -Force }
$desktopShortcut = Join-Path ([Environment]::GetFolderPath("Desktop")) "MLLminal.lnk"
if (Test-Path -LiteralPath $desktopShortcut) { Remove-Item -LiteralPath $desktopShortcut -Force }
$startupShortcut = Join-Path ([Environment]::GetFolderPath("Startup")) "MLLminal daemon.lnk"
if (Test-Path -LiteralPath $startupShortcut) { Remove-Item -LiteralPath $startupShortcut -Force }

$browserHostKeys = @(
    "HKCU:\Software\Google\Chrome\NativeMessagingHosts\com.mllminal.bridge",
    "HKCU:\Software\Microsoft\Edge\NativeMessagingHosts\com.mllminal.bridge",
    "HKCU:\Software\Mozilla\NativeMessagingHosts\com.mllminal.bridge"
)
foreach ($key in $browserHostKeys) {
    if (Test-Path -LiteralPath $key) { Remove-Item -LiteralPath $key -Recurse -Force }
}

if (Test-Path -LiteralPath $InstallRoot) {
    Remove-Item -LiteralPath $InstallRoot -Recurse -Force -ErrorAction SilentlyContinue
    if (Test-Path -LiteralPath $InstallRoot) {
        $cleanupArgs = "/c timeout /t 2 /nobreak >nul & rmdir /s /q `"$InstallRoot`""
        Start-Process -FilePath $env:ComSpec -ArgumentList $cleanupArgs -WindowStyle Hidden
    }
}
if ($deleteOwnedData) {
    if ((Split-Path $DataDirectory -Leaf) -ine "data" -or (Split-Path $BackupDirectory -Leaf) -ine "backups") {
        throw "Refusing to delete an unscoped data directory."
    }
    if (Test-Path -LiteralPath $DataDirectory) { Remove-Item -LiteralPath $DataDirectory -Recurse -Force }
    if (Test-Path -LiteralPath $BackupDirectory) { Remove-Item -LiteralPath $BackupDirectory -Recurse -Force }
    Write-Diagnostic "MLLminal application and owned local data removed; user outputs were not touched."
    Write-Output "MLLminal application and MLLminal-owned local data were deleted. User outputs were not touched. User-created outputs were not deleted."
} else {
    Write-Diagnostic "MLLminal application removed; local data retained."
    Write-Output "MLLminal application was removed. Local data was retained; run mllminal install purge-data to delete it explicitly."
}
exit 0
