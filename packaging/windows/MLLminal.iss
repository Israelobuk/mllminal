#define MyAppName "MLLminal"
#define MyAppVersion "0.1.0"
#define MyAppPublisher "MLLminal"
#define MyAppExeName "mllminal.exe"

[Setup]
AppId={{C2EA8B9D-0E48-47AF-86C5-0A1B2C3D4E5F}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\MLLminal\app
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
Name: "lightweight"; Description: "Use lightweight mode (skip optional portable providers)"
Name: "portableprovider"; Description: "Allow optional portable spreadsheet provider (~350 MB; needed for local PDF rendering)"
Name: "startup"; Description: "Launch the MLLminal daemon at login"

[Icons]
Name: "{group}\Mil"; Filename: "{app}\runtime\Scripts\mllminal.exe"; Parameters: "mil"; WorkingDir: "{app}"
Name: "{group}\MLLminal TUI"; Filename: "{app}\runtime\Scripts\mllminal.exe"; Parameters: "tui"; WorkingDir: "{app}"
Name: "{group}\MLLminal daemon"; Filename: "{app}\runtime\Scripts\mllminald.exe"; WorkingDir: "{app}"

[Run]
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File \"{app}\install.ps1\" -InstallRoot \"{app}\" -DataDirectory \"{localappdata}\MLLminal\data\" -BackupDirectory \"{localappdata}\MLLminal\backups\" -Repair -Lightweight:{code:LightweightArg} -InstallOptionalProviders:{code:PortableProviderArg} -EnableStartup:{code:StartupArg}"; Flags: waituntilterminated
Filename: "{app}\runtime\Scripts\mllminal.exe"; Parameters: "install status --json"; Flags: postinstall skipifsilent

[UninstallRun]
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File \"{app}\uninstall.ps1\" -InstallRoot \"{app}\" -DataDirectory \"{localappdata}\MLLminal\data\" -BackupDirectory \"{localappdata}\MLLminal\backups\" -DeleteData:{code:DeleteDataArg}"; Flags: waituntilterminated

[Code]
function LightweightArg(Param: String): String;
begin
  if WizardIsTaskSelected('lightweight') then Result := '$true' else Result := '$false';
end;

function PortableProviderArg(Param: String): String;
begin
  if WizardIsTaskSelected('portableprovider') then Result := '$true' else Result := '$false';
end;

function StartupArg(Param: String): String;
begin
  if WizardIsTaskSelected('startup') then Result := '$true' else Result := '$false';
end;

function DeleteDataArg(Param: String): String;
begin
  if MsgBox('Delete MLLminal-owned local data and history? User-created outputs are never deleted.', mbConfirmation, MB_YESNO) = idYes then Result := '$true' else Result := '$false';
end;