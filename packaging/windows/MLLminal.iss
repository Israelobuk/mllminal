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
Name: "advanced\retain-data"; Description: "Retain existing MLLminal data during reinstall"; Flags: unchecked

[Icons]
Name: "{group}\MLLminal"; Filename: "{app}\runtime\Scripts\mllminal.exe"; Parameters: "tui"; WorkingDir: "{app}"
Name: "{group}\Mil"; Filename: "{app}\runtime\Scripts\mllminal.exe"; Parameters: "mil"; WorkingDir: "{app}"
Name: "{group}\MLLminal Terminal"; Filename: "{app}\runtime\Scripts\mllminal.exe"; Parameters: "mil"; WorkingDir: "{app}"
Name: "{group}\MLLminal Diagnostics"; Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -NoExit -Command ""& '{app}\runtime\Scripts\mllminal.exe' doctor"""; WorkingDir: "{app}"
Name: "{group}\Uninstall MLLminal"; Filename: "{uninstallexe}"
Name: "{userdesktop}\MLLminal"; Filename: "{app}\runtime\Scripts\mllminal.exe"; Parameters: "tui"; WorkingDir: "{app}"; Tasks: "advanced\desktop"

[Run]
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\install.ps1"" -InstallRoot ""{app}"" -DataDirectory ""{localappdata}\MLLminal\data"" -BackupDirectory ""{localappdata}\MLLminal\backups"" -Repair -Lightweight:$false -InstallOptionalProviders:$false -EnableStartup:{code:StartupArg} -CreateDesktopShortcut:{code:DesktopArg} -RetainExistingData:{code:RetainDataArg}"; Flags: waituntilterminated
Filename: "{app}\runtime\Scripts\mllminal.exe"; Parameters: "install status --json"; Flags: postinstall

[UninstallRun]
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\uninstall.ps1"" -InstallRoot ""{app}"" -DataDirectory ""{localappdata}\MLLminal\data"" -BackupDirectory ""{localappdata}\MLLminal\backups"" -DeleteData:{code:DeleteDataArg}"; Flags: waituntilterminated

[Code]
function StartupArg(Param: String): String;
begin
  if WizardIsTaskSelected('advanced\startup') then Result := '$true' else Result := '$false';
end;

function DesktopArg(Param: String): String;
begin
  if WizardIsTaskSelected('advanced\desktop') then Result := '$true' else Result := '$false';
end;

function RetainDataArg(Param: String): String;
begin
  if WizardIsTaskSelected('advanced\retain-data') then Result := '$true' else Result := '$false';
end;

function DeleteDataArg(Param: String): String;
begin
  if MsgBox('Delete MLLminal-owned local data and history? User-created outputs are never deleted.', mbConfirmation, MB_YESNO) = idYes then Result := '$true' else Result := '$false';
end;