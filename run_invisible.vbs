Set WshShell = CreateObject("WScript.Shell")
WshShell.Run chr(34) & "C:\Users\User\PythonProjetcs\Python\ProductionValue\run_server.bat" & chr(34), 0, True
Set WshShell = Nothing
