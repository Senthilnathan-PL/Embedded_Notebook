@echo off
setlocal

REM Directory where this batch script is located
set "WORK_DIR=%~dp0"

REM Remove trailing backslash
set "WORK_DIR=%WORK_DIR:~0,-1%"

REM Virtual environment path
set "VENV=%WORK_DIR%\.venv"

echo Working directory: %WORK_DIR%
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
"%VENV%\Scripts\python.exe" -m pip install -r "%WORK_DIR%\requirements.txt"

if errorlevel 1 (
    echo.
    echo ERROR: Failed to install requirements.
    pause
    exit /b 1
)

REM Run the Python script
echo.
echo Running Python script...
echo.

"%VENV%\Scripts\python.exe" "%WORK_DIR%\embedded_notebook2.py"

if errorlevel 1 (
    echo.
    echo Python program exited with an error.
)

pause
