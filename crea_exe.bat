@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title NOVA - creazione EXE e installer
echo.
echo  ==========================================
echo    NOVA - creazione NOVA.exe + installer
echo  ==========================================
echo.

if not exist ".venv\Scripts\python.exe" (
    echo Prima installo l'ambiente con setup.bat...
    call setup.bat
)
if not exist ".venv\Scripts\python.exe" ( echo ERRORE: ambiente mancante & pause & exit /b 1 )
set "PY=.venv\Scripts\python.exe"

echo [1/5] Componenti nativi: ultime versioni di mpv, ffmpeg, aria2, yt-dlp...
"%PY%" setup_deps.py --latest
if errorlevel 1 ( pause & exit /b 1 )

echo [2/5] Librerie e PyInstaller...
"%PY%" -m pip install --upgrade -r requirements.txt --quiet
"%PY%" -m pip install --upgrade pyinstaller --quiet
if errorlevel 1 ( echo ERRORE installazione PyInstaller & pause & exit /b 1 )

echo [3/5] Icona...
if not exist "assets\nova.ico" "%PY%" -c "import setup_deps; setup_deps.make_icon()"

echo [4/5] Compilazione NOVA.exe (qualche minuto)...
if exist "build" rmdir /s /q build
if exist "dist\NOVA" rmdir /s /q "dist\NOVA"
"%PY%" -m PyInstaller --noconfirm --clean --windowed --name NOVA --icon "assets\nova.ico" ^
  --paths . --collect-submodules app --hidden-import mpv --hidden-import libtorrent --hidden-import qrcode ^
  --exclude-module tkinter --exclude-module numpy --exclude-module PySide6.QtWebEngineCore --exclude-module PySide6.QtWebEngineWidgets ^
  --exclude-module PySide6.Qt3DCore --exclude-module PySide6.QtQuick --exclude-module PySide6.QtQml ^
  --exclude-module PySide6.QtMultimedia --exclude-module PySide6.QtCharts --exclude-module PySide6.QtDataVisualization ^
  --exclude-module PySide6.QtPdf --exclude-module PySide6.QtBluetooth --exclude-module PySide6.QtSql ^
  main.py
if errorlevel 1 ( echo ERRORE compilazione & pause & exit /b 1 )
xcopy /e /i /y /q bin "dist\NOVA\bin" >nul
xcopy /e /i /y /q assets "dist\NOVA\assets" >nul
echo     OK: dist\NOVA\NOVA.exe

echo [5/5] Installer NOVA-Setup.exe...
set "ISCC="
for %%P in ("%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" "%ProgramFiles%\Inno Setup 6\ISCC.exe") do if exist %%P set "ISCC=%%~P"
if not defined ISCC (
    echo     Installo Inno Setup con winget...
    winget install -e --id JRSoftware.InnoSetup --scope user --accept-package-agreements --accept-source-agreements
    for %%P in ("%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" "%ProgramFiles%\Inno Setup 6\ISCC.exe") do if exist %%P set "ISCC=%%~P"
)
if not defined ISCC (
    echo     Inno Setup non disponibile: l'installer non e' stato creato.
    echo     NOVA.exe funziona comunque: dist\NOVA\NOVA.exe
    pause
    exit /b 0
)
"%ISCC%" /Q "build_tools\NOVA.iss"
if errorlevel 1 ( echo ERRORE installer & pause & exit /b 1 )

echo.
echo  Fatto!
echo    App:        dist\NOVA\NOVA.exe
echo    Installer:  dist\NOVA-Setup.exe   (questo puoi copiarlo e installarlo ovunque)
echo.
explorer dist
pause
