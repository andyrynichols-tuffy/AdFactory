' Starts the Ad Factory editor quietly in the background (no window, no browser).
' Windows runs this at sign-in via a shortcut in the Startup folder, so the inbox
' keeps pre-cutting new videos. Open the editor with start-ad-editor.bat or
' http://127.0.0.1:8770. Log: %USERPROFILE%\MemeSupercutData\ads\editor.log
Set sh = CreateObject("WScript.Shell")
Set fs = CreateObject("Scripting.FileSystemObject")
root = fs.GetParentFolderName(WScript.ScriptFullName)
sh.CurrentDirectory = root
logDir = sh.ExpandEnvironmentStrings("%USERPROFILE%") & "\MemeSupercutData\ads"
If Not fs.FolderExists(logDir) Then fs.CreateFolder(logDir)
q = Chr(34)
py = root & "\.venv\Scripts\python.exe"
cmd = "cmd /c " & q & q & py & q & " -m adcut serve >> " & q & logDir & "\editor.log" & q & " 2>&1" & q
sh.Run cmd, 0, False
