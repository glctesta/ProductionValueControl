@echo off
REM Wrapper per avviare il server ProductionValue dal CWD corretto con auto-restart
cd /d "%~dp0"

:loop
.venv\Scripts\python.exe app.py
echo Server exited with code %errorlevel%. Restarting in 5 seconds...
timeout /t 5
goto loop
