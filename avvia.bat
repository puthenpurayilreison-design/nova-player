@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
    echo NOVA non e' installato: avvio setup.bat...
    call setup.bat
)
start "" ".venv\Scripts\pythonw.exe" "%~dp0main.py" %*
