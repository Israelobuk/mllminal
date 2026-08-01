#define MyAppName "MLLminal"
#define MyAppVersion "0.1.0"
#define MyAppPublisher "MLLminal"
#define MyAppExeName "mllminal.exe"

[Setup]
AppId={{C2EA8B9D-0E48-47AF-86C5-0A1B2C3D4E5F}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\MLLminal
DefaultGroupName=MLLminal
OutputDir=dist
OutputBaseFilename=MLLminal-Setup
Compression=lzma2
SolidCompression=yes
PrivilegesRequired=lowest
ArchitecturesInstallIn64BitMode=x64compatible
ChangesEnvironment=yes
; Inno Setup supports /VERYSILENT and /NORESTART for safe unattended install and uninstall.

[Files]
Source: "dist\mllminal-*.whl"; DestDir: "{app}\dist"; Flags: ignoreversion
Source: "runtime\*"; DestDir: "{app}\runtime"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "install.ps1"; DestDir: "{app}"; Flags: ignoreversion
Source: "uninstall.ps1"; DestDir: "{app}"; Flags: ignoreversion
Source: "export-diagnostics.ps1"; DestDir: "{app}"; Flags: ignoreversion
Source: "doctor.ps1"; DestDir: "{app}"; Flags: ignoreversion
Source: "README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\browser-extension\*"; DestDir: "{app}\browser-extension"; Flags: ignoreversion recursesubdirs createallsubdirs

[Tasks]
Name: "advanced"; Description: "Advanced options"; Flags: unchecked
Name: "advanced\startup"; Description: "Launch the MLLminal daemon at login"; Flags: unchecked
Name: "advanced\desktop"; Description: "Create a desktop shortcut"; Flags: unchecked
Name: "advanced\retain_data"; Description: "Retain existing MLLminal data during reinstall"; Flags: unchecked

[Icons]
Name: "{group}\MLLminal"; Filename: "{app}\runtime\Scripts\mllminal.exe"; Parameters: "tui"; WorkingDir: "{app}"
Name: "{group}\Mil"; Filename: "{app}\runtime\Scripts\mllminal.exe"; Parameters: "mil"; WorkingDir: "{app}"
Name: "{group}\MLLminal Terminal"; Filename: "{app}\runtime\Scripts\mllminal.exe"; Parameters: "mil"; WorkingDir: "{app}"
Name: "{group}\MLLminal Diagnostics"; Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -NoExit -Command ""& '{app}\runtime\Scripts\mllminal.exe' doctor"""; WorkingDir: "{app}"
Name: "{group}\Uninstall MLLminal"; Filename: "{uninstallexe}"
Name: "{userdesktop}\MLLminal"; Filename: "{app}\runtime\Scripts\mllminal.exe"; Parameters: "tui"; WorkingDir: "{app}"; Tasks: "advanced\desktop"

[Run]
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\install.ps1"" -InstallRoot ""{app}"" -DataDirectory ""{code:DataDirectoryArg}"" -BackupDirectory ""{code:BackupDirectoryArg}"" -Repair {code:StartupArg} {code:DesktopArg} {code:RetainDataArg}"; Flags: waituntilterminated
Filename: "{app}\runtime\Scripts\mllminal.exe"; Parameters: "install status --json"; Flags: postinstall
Filename: "{app}\runtime\Scripts\mllminal.exe"; Parameters: "mil"; Description: "Launch Mil"; Flags: postinstall nowait skipifsilent

[UninstallRun]
; Normal uninstall presents a checkbox labeled: Also delete MLLminal local data
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\uninstall.ps1"" -InstallRoot ""{app}"" -DataDirectory ""{code:DataDirectoryArg}"" -BackupDirectory ""{code:BackupDirectoryArg}"" {code:PromptForDataArg} {code:SilentArg}"; Flags: waituntilterminated; RunOnceId: "MLLminalUninstall"

[Code]
function DataDirectoryArg(Param: String): String;
begin
  if (GetEnv('MLLMINAL_WINDOWS_ACCEPTANCE') = '1') and (GetEnv('MLLMINAL_ACCEPTANCE_DATA_DIR') <> '') then
    Result := GetEnv('MLLMINAL_ACCEPTANCE_DATA_DIR')
  else
    Result := ExpandConstant('{localappdata}\MLLminal\data');
end;

function BackupDirectoryArg(Param: String): String;
begin
  if (GetEnv('MLLMINAL_WINDOWS_ACCEPTANCE') = '1') and (GetEnv('MLLMINAL_ACCEPTANCE_BACKUP_DIR') <> '') then
    Result := GetEnv('MLLMINAL_ACCEPTANCE_BACKUP_DIR')
  else
    Result := ExpandConstant('{localappdata}\MLLminal\backups');
end;

function StartupArg(Param: String): String;
begin
  if WizardIsTaskSelected('advanced\startup') then Result := '-EnableStartup' else Result := '';
end;

function DesktopArg(Param: String): String;
begin
  if WizardIsTaskSelected('advanced\desktop') then Result := '-CreateDesktopShortcut' else Result := '';
end;

function RetainDataArg(Param: String): String;
begin
  if WizardIsTaskSelected('advanced\retain_data') then Result := '-RetainExistingData' else Result := '';
end;

function PromptForDataArg(Param: String): String;
begin
  if WizardSilent then Result := '' else Result := '-PromptForData';
end;

function SilentArg(Param: String): String;
begin
  if WizardSilent then Result := '-Silent' else Result := '';
end;
