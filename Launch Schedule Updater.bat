@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if not errorlevel 1 (
    py -3 -c "import sys, tkinter; assert sys.version_info >= (3, 10)" >nul 2>nul
    if not errorlevel 1 (
        py -3 "%~dp0schedule_gui.py"
        if errorlevel 1 goto failed
        exit /b 0
    )
)
where python >nul 2>nul
if not errorlevel 1 (
    python -c "import sys, tkinter; assert sys.version_info >= (3, 10)" >nul 2>nul
    if not errorlevel 1 (
        python "%~dp0schedule_gui.py"
        if errorlevel 1 goto failed
        exit /b 0
    )
)
echo Python 3.10 or newer with Tcl/Tk is required.
echo Install Python from https://www.python.org/downloads/windows/
echo Include Tcl/Tk and select "Add Python to PATH" during installation.
echo Then double-click this launcher again.
pause
exit /b 1
:failed
echo The application could not start. See the error above.
pause
exit /b 1
