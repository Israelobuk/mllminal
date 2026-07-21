#define MyAppName "MLLminal"
#define MyAppVersion "0.1.0"
#define MyAppPublisher "MLLminal"
#define MyAppURL "https://github.com/Israelobuk/mllminal"

[Setup]
AppId={{C2EA8B9D-0E48-47AF-86C5-0A1B2C3D4E5F}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\MLLminal
DefaultGroupName=MLLminal
OutputDir=dist
OutputBaseFilename=MLLminal-Setup
Compression=lzma
SolidCompression=yes
PrivilegesRequired=lowest
ArchitecturesInstallIn64BitMode=x64compatible

[Files]
Source: "dist\mllminal-*.whl"; DestDir: "{app}\dist"; Flags: ignoreversion
Source: "install.ps1"; DestDir: "{app}"; Flags: ignoreversion
Source: "uninstall.ps1"; DestDir: "{app}"; Flags: ignoreversion
Source: "export-diagnostics.ps1"; DestDir: "{app}"; Flags: ignoreversion
Source: "README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\browser-extension\*"; DestDir: "{app}\browser-extension"; Flags: ignoreversion recursesubdirs createallsubdirs

[Tasks]
Name: "lightweight"; Description: "Use lightweight mode (skip optional portable providers)"
Name: "portableprovider"; Description: "Allow optional portable spreadsheet provider (~350 MB; needed for local PDF rendering)"

[Run]
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File \"{app}\install.ps1\" -InstallRoot \"{app}\" -Lightweight:{code:LightweightArg} -InstallOptionalProviders:{code:PortableProviderArg}"; Flags: waituntilterminated
Filename: "notepad.exe"; Parameters: "\"{app}\README.md\""; Flags: postinstall skipifsilent

[UninstallRun]
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File \"{app}\uninstall.ps1\" -InstallRoot \"{app}\""; Flags: waituntilterminated

[Code]
function LightweightArg(Param: String): String;
begin
  if WizardIsTaskSelected('lightweight') then Result := '$true' else Result := '$false';
end;

function PortableProviderArg(Param: String): String;
begin
  if WizardIsTaskSelected('portableprovider') then Result := '$true' else Result := '$false';
end;
