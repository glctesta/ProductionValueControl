@echo off
REM Wrapper per avviare il server ProductionValue dal CWD corretto con auto-restart
cd /d "%~dp0"

:loop
.venv\Scripts\python.exe app.py
echo Server exited with code %errorlevel%. Restarting in 5 seconds...
ping 127.0.0.1 -n 6 >nul
goto loop
