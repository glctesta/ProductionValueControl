@echo off
REM Wrapper per avviare il server ProductionValue dal CWD corretto con auto-restart e auto-reload
cd /d "%~dp0"

.venv\Scripts\python.exe -m pip show hupper >nul 2>&1
if %errorlevel% neq 0 (
    .venv\Scripts\python.exe -m pip install hupper --quiet
)

if exist .venv\Scripts\hupper.exe (
    set RUN_CMD=.venv\Scripts\hupper.exe -m app
) else (
    set RUN_CMD=.venv\Scripts\python.exe app.py
)

:loop
%RUN_CMD%
echo Server exited with code %errorlevel%. Restarting in 5 seconds...
timeout /t 5
goto loop
