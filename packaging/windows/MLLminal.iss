#define MyAppName "MLLminal"
#ifndef MyAppVersion
#define MyAppVersion "0.1.0"
#endif
#define MyAppPublisher "MLLminal"
#define MyAppExeName "mllminal.exe"

[Setup]
AppId={{C2EA8B9D-0E48-47AF-86C5-0A1B2C3D4E5F}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\MLLminal
DefaultGroupName=MLLminal
DisableWelcomePage=no
DisableDirPage=no
DisableProgramGroupPage=yes
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


[Icons]
Name: "{group}\MLLminal"; Filename: "{app}\runtime\Scripts\mllminal.exe"; Parameters: "tui"; WorkingDir: "{app}"
Name: "{group}\Mil"; Filename: "{app}\runtime\Scripts\mllminal.exe"; Parameters: "mil"; WorkingDir: "{app}"
Name: "{group}\MLLminal Terminal"; Filename: "{app}\runtime\Scripts\mllminal.exe"; Parameters: "mil"; WorkingDir: "{app}"
Name: "{group}\MLLminal Diagnostics"; Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -NoExit -Command ""& '{app}\runtime\Scripts\mllminal.exe' doctor"""; WorkingDir: "{app}"
Name: "{group}\Uninstall MLLminal"; Filename: "{uninstallexe}"
Name: "{userdesktop}\MLLminal"; Filename: "{app}\runtime\Scripts\mllminal.exe"; Parameters: "tui"; WorkingDir: "{app}"; Check: DesktopShortcutSelected

; The bootstrapper performs daemon readiness before the Ready page. No interactive
; client is auto-launched here; users choose Mil or the TUI from Start Menu.


[UninstallRun]
; Normal uninstall presents a checkbox labeled: Also delete MLLminal local data
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\uninstall.ps1"" -InstallRoot ""{app}"" -DataDirectory ""{code:DataDirectoryArg}"" -BackupDirectory ""{code:BackupDirectoryArg}"" {code:PromptForDataArg} {code:SilentArg}"; Flags: waituntilterminated; RunOnceId: "MLLminalUninstall"

[Code]

var
  AdvancedPage: TWizardPage;
  AdvancedToggle: TNewCheckBox;
  StartupCheck: TNewCheckBox;
  DesktopCheck: TNewCheckBox;
  RetainCheck: TNewCheckBox;

procedure InitializeWizard;
begin
  AdvancedPage := CreateCustomPage(wpWelcome, 'Advanced options', 'Safe defaults are suitable for most users. Enable only the options you need.');
  StartupCheck := TNewCheckBox.Create(WizardForm);
  StartupCheck.Parent := AdvancedPage.Surface;
  StartupCheck.Caption := 'Launch the MLLminal daemon at login';
  StartupCheck.Left := ScaleX(0);
  StartupCheck.Top := ScaleY(10);
  StartupCheck.Width := ScaleX(440);
  StartupCheck.Checked := False;
  DesktopCheck := TNewCheckBox.Create(WizardForm);
  DesktopCheck.Parent := AdvancedPage.Surface;
  DesktopCheck.Caption := 'Create a desktop shortcut';
  DesktopCheck.Left := ScaleX(0);
  DesktopCheck.Top := ScaleY(42);
  DesktopCheck.Width := ScaleX(440);
  DesktopCheck.Checked := False;
  RetainCheck := TNewCheckBox.Create(WizardForm);
  RetainCheck.Parent := AdvancedPage.Surface;
  RetainCheck.Caption := 'Retain existing MLLminal data during reinstall';
  RetainCheck.Left := ScaleX(0);
  RetainCheck.Top := ScaleY(74);
  RetainCheck.Width := ScaleX(440);
  RetainCheck.Checked := True;
  AdvancedToggle := TNewCheckBox.Create(WizardForm);
  AdvancedToggle.Parent := WizardForm.WelcomePage;
  AdvancedToggle.Caption := 'Show advanced options before installing';
  AdvancedToggle.Left := ScaleX(0);
  AdvancedToggle.Top := ScaleY(220);
  AdvancedToggle.Width := ScaleX(440);
  AdvancedToggle.Checked := False;
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  Result := ((PageID = AdvancedPage.ID) and (not AdvancedToggle.Checked)) or
    ((PageID = wpSelectDir) and (not AdvancedToggle.Checked));
end;
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

function DesktopShortcutSelected(): Boolean;
begin
  Result := DesktopCheck.Checked;
end;

function StartupArg(Param: String): String;
begin
  if StartupCheck.Checked then Result := '-EnableStartup' else Result := '';
end;

function DesktopArg(Param: String): String;
begin
  if DesktopCheck.Checked then Result := '-CreateDesktopShortcut' else Result := '';
end;

function RetainDataArg(Param: String): String;
begin
  if RetainCheck.Checked then Result := '-RetainExistingData' else Result := '';
end;

function PromptForDataArg(Param: String): String;
begin
  if WizardSilent then Result := '' else Result := '-PromptForData';
end;

function SilentArg(Param: String): String;
begin
  if WizardSilent then Result := '-Silent' else Result := '';
end;

function RunInstallBootstrapper(): Boolean;
var
  ResultCode: Integer;
  Parameters: String;
begin
  Parameters := '-NoProfile -ExecutionPolicy Bypass -File "' +
    ExpandConstant('{app}\install.ps1') + '"' +
    ' -InstallRoot "' + ExpandConstant('{app}') + '"' +
    ' -DataDirectory "' + DataDirectoryArg('') + '"' +
    ' -BackupDirectory "' + BackupDirectoryArg('') + '"' +
    ' -Repair ' + StartupArg('') + ' ' + DesktopArg('') + ' ' + RetainDataArg('');
  Result := Exec(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'),
    Parameters, '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  if (not Result) or (ResultCode <> 0) then begin
    if WizardSilent then
      Log('MLLminal bootstrapper failed with exit code ' + IntToStr(ResultCode))
    else
      MsgBox('MLLminal could not complete setup. Open MLLminal Diagnostics for details.', mbError, MB_OK);
    Result := False;
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
    if not RunInstallBootstrapper() then
      Abort;
end;
