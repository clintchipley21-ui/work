@echo off
setlocal
cd /d "%~dp0"
set "LNTP_BUILD_PY=%LOCALAPPDATA%\LNTP Schedule Updater\Python\python.exe"
if exist "%LNTP_BUILD_PY%" (
    "%LNTP_BUILD_PY%" -m venv .build-venv
    goto checkvenv
)
where py >nul 2>nul
if not errorlevel 1 (
    py -3 -m venv .build-venv
) else (
    python -m venv .build-venv
)
:checkvenv
if errorlevel 1 goto failed
".build-venv\Scripts\python.exe" -m pip install "pyinstaller==6.22.3"
if errorlevel 1 goto failed
".build-venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean --onefile --windowed --name "LNTP Schedule Updater" --add-data "activity_id_mapping.csv;." schedule_gui.py
if errorlevel 1 goto failed
echo.
echo Finished. The standalone program is in the dist folder.
echo You can copy "dist\LNTP Schedule Updater.exe" to a computer without Python.
pause
exit /b 0
:failed
echo Build failed. See the error above. Python 3.10 or newer is required.
pause
exit /b 1
