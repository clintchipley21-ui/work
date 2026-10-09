@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0install_for_user.ps1"
if errorlevel 1 (
    echo.
    echo Installation stopped. See the explanation above.
    pause
    exit /b 1
)
echo.
echo Installed for your Windows account. Use the LNTP Schedule Updater shortcut.
pause
