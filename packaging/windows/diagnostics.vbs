Option Explicit

Dim shell
Dim fileSystem
Dim scriptDirectory
Dim executable
Dim exitCode

Set shell = CreateObject("WScript.Shell")
Set fileSystem = CreateObject("Scripting.FileSystemObject")
scriptDirectory = fileSystem.GetParentFolderName(WScript.ScriptFullName)
executable = fileSystem.BuildPath(scriptDirectory, "runtime\Scripts\mllminal.exe")

' Run the diagnostics command without creating a console window.
exitCode = shell.Run(Chr(34) & executable & Chr(34) & " doctor --json", 0, True)
WScript.Quit exitCode