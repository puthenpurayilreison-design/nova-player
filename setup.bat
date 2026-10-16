@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title NOVA - installazione
echo.
echo  ==========================================
echo    NOVA - installazione (Windows 11)
echo  ==========================================
echo.

set "PY="
py -3.12 -c "import sys" >nul 2>&1 && set "PY=py -3.12"
if not defined PY (
    echo [1/5] Python 3.12 non trovato: lo installo con winget...
    winget install -e --id Python.Python.3.12 --scope user --accept-package-agreements --accept-source-agreements
    py -3.12 -c "import sys" >nul 2>&1 && set "PY=py -3.12"
)
if not defined PY if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set "PY="%LOCALAPPDATA%\Programs\Python\Python312\python.exe""
if not defined PY (
    echo.
    echo ERRORE: Python 3.12 non disponibile.
    echo Installalo da https://www.python.org/downloads/release/python-3128/ ^(spunta "Add to PATH"^) e rilancia setup.bat
    pause
    exit /b 1
)
echo [1/5] Python OK

if not exist "%SystemRoot%\System32\msvcp140.dll" (
    echo [2/5] Installo Microsoft Visual C++ Runtime...
    winget install -e --id Microsoft.VCRedist.2015+.x64 --accept-package-agreements --accept-source-agreements
) else (
    echo [2/5] Visual C++ Runtime OK
)

echo [3/5] Ambiente Python e librerie...
if not exist ".venv\Scripts\python.exe" %PY% -m venv .venv
if errorlevel 1 ( echo ERRORE creazione ambiente & pause & exit /b 1 )
".venv\Scripts\python.exe" -m pip install --upgrade pip --quiet
".venv\Scripts\python.exe" -m pip install -r requirements.txt --upgrade
if errorlevel 1 ( echo ERRORE installazione librerie & pause & exit /b 1 )

echo [4/5] Componenti nativi (mpv, aria2, ffmpeg)...
".venv\Scripts\python.exe" setup_deps.py
if errorlevel 1 ( pause & exit /b 1 )

echo [5/5] Collegamenti...
".venv\Scripts\python.exe" setup_deps.py --shortcut

echo.
echo  Fatto! Apri NOVA dal Desktop oppure con avvia.bat
echo.
pause
