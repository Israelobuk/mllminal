Option Explicit

Dim shell
Dim fileSystem
Dim scriptDirectory
Dim executable
Dim diagnosticsRoot
Dim diagnosticsDirectory
Dim logPath
Dim command
Dim exitCode

Set shell = CreateObject("WScript.Shell")
Set fileSystem = CreateObject("Scripting.FileSystemObject")
scriptDirectory = fileSystem.GetParentFolderName(WScript.ScriptFullName)
executable = fileSystem.BuildPath(scriptDirectory, "runtime\Scripts\mllminal.exe")
diagnosticsRoot = fileSystem.BuildPath(shell.ExpandEnvironmentStrings("%LOCALAPPDATA%"), "MLLminal")
diagnosticsDirectory = fileSystem.BuildPath(diagnosticsRoot, "diagnostics")
logPath = fileSystem.BuildPath(diagnosticsDirectory, "doctor-shortcut.json")

If Not fileSystem.FolderExists(diagnosticsRoot) Then
    fileSystem.CreateFolder diagnosticsRoot
End If
If Not fileSystem.FolderExists(diagnosticsDirectory) Then
    fileSystem.CreateFolder diagnosticsDirectory
End If

' Run the diagnostics command without creating a console window and retain its JSON output.
command = shell.ExpandEnvironmentStrings("%ComSpec%") & " /c " & _
    Chr(34) & Chr(34) & executable & Chr(34) & " doctor --json > " & Chr(34) & logPath & Chr(34) & " 2>&1" & Chr(34)
exitCode = shell.Run(command, 0, True)
WScript.Quit exitCode
