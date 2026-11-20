Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
d = fso.GetParentFolderName(WScript.ScriptFullName)
sh.CurrentDirectory = d
sh.Run "pythonw.exe """ & d & "\main.py""", 0, False
If Err.Number <> 0 Then
  Err.Clear
  sh.Run "pyw.exe """ & d & "\main.py""", 0, False
End If
