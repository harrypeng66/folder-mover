Set shell = CreateObject("WScript.Shell")
If CreateObject("Scripting.FileSystemObject").FileExists("folder_mover.exe") Then
  shell.Run "folder_mover.exe", 0, True
Else
  shell.Run "cmd /c py -3 folder_mover.py", 0, True
End If
