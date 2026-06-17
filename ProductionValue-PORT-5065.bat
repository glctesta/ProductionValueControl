@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [setup] Creo venv...
    py -3 -m venv .venv
    call .venv\Scripts\activate.bat
    python -m pip install --upgrade pip
) else (
    call .venv\Scripts\activate.bat
)

echo [setup] Verifica/installazione dipendenze da requirements.txt...
python -m pip install -q -r requirements.txt
if errorlevel 1 (
    echo [setup] Errore nell'installazione dei pacchetti. Interrompo.
    pause
    exit /b 1
)

echo [run] Avvio ProductionValue su http://localhost:5065 ...
python app.py
endlocal
