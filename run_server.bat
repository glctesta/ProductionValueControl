@echo off
REM Wrapper per avviare il server ProductionValue dal CWD corretto
cd /d "%~dp0"
powershell -Command "Get-CimInstance Win32_Process -Filter \"Name = 'python.exe' AND CommandLine LIKE '%%app.py%%'\" | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"
.venv\Scripts\python.exe app.py
