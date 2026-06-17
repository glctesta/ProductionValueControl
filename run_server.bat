@echo off
REM Wrapper per avviare il server ProductionValue dal CWD corretto
cd /d "%~dp0"
.venv\Scripts\python.exe app.py
