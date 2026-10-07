@echo off
setlocal

REM Directory where this batch script is located
set "SCRIPT_DIR=%~dp0"
set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"

REM Resolve project root (parent if located in Windows/)
if exist "%SCRIPT_DIR%\requirements.txt" (
    set "PROJECT_ROOT=%SCRIPT_DIR%"
) else (
    for %%I in ("%SCRIPT_DIR%\..") do set "PROJECT_ROOT=%%~fI"
)

REM Virtual environment path
set "VENV=%PROJECT_ROOT%\.venv"

echo Project root: %PROJECT_ROOT%
echo.

REM Create .venv if it doesn't exist
if not exist "%VENV%\Scripts\python.exe" (
    echo .venv not found. Creating virtual environment...
    python -m venv "%VENV%"

    if errorlevel 1 (
        echo.
        echo ERROR: Failed to create virtual environment.
        pause
        exit /b 1
    )
)

REM Install/update requirements
echo Installing/updating Python requirements...
"%VENV%\Scripts\python.exe" -m pip install -r "%PROJECT_ROOT%\requirements.txt"

if errorlevel 1 (
    echo.
    echo ERROR: Failed to install requirements.
    pause
    exit /b 1
)

REM Run the application
echo.
echo Launching Embedded Notebook...
echo.

if exist "%PROJECT_ROOT%\embedded_notebook2.py" (
    "%VENV%\Scripts\python.exe" "%PROJECT_ROOT%\embedded_notebook2.py"
) else (
    "%VENV%\Scripts\python.exe" "%PROJECT_ROOT%\scripts\main.py"
)

if errorlevel 1 (
    echo.
    echo Python program exited with an error.
)

pause
