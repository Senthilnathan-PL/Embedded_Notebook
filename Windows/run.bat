@echo off
setlocal

REM Set command prompt console title
title Embedded Notebook - Console Log

REM Resolve project root (parent if located in Windows/)
set "SCRIPT_DIR=%~dp0"
set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"

if exist "%SCRIPT_DIR%\requirements.txt" (
    set "PROJECT_ROOT=%SCRIPT_DIR%"
) else (
    for %%I in ("%SCRIPT_DIR%\..") do set "PROJECT_ROOT=%%~fI"
)

cd /d "%PROJECT_ROOT%"

REM Virtual environment and Python executable paths
set "VENV=%PROJECT_ROOT%\.venv"
set "PYTHON_EXE=%VENV%\Scripts\python.exe"

REM Application target script
if exist "%PROJECT_ROOT%\embedded_notebook2.py" (
    set "TARGET_SCRIPT=%PROJECT_ROOT%\embedded_notebook2.py"
) else (
    set "TARGET_SCRIPT=%PROJECT_ROOT%\scripts\main.py"
)

echo ============================================================
echo   Embedded Notebook - Console Logger
echo   Running from: %PROJECT_ROOT%
echo ============================================================
echo.

REM Check if the virtual environment exists; if not, initialize setup
if not exist "%PYTHON_EXE%" (
    echo Virtual environment was not found.
    echo Running Windows\install.bat to set up Embedded Notebook...
    echo.
    if exist "%PROJECT_ROOT%\Windows\install.bat" (
        call "%PROJECT_ROOT%\Windows\install.bat"
    ) else (
        echo ERROR: Virtual environment not found and Windows\install.bat was not located.
        pause
        exit /b 1
    )
)

if not exist "%PYTHON_EXE%" (
    echo ERROR: Python executable not found at: %PYTHON_EXE%
    pause
    exit /b 1
)

echo Starting Embedded Notebook...
"%PYTHON_EXE%" "%TARGET_SCRIPT%" %*

set "EXIT_CODE=%ERRORLEVEL%"
if not "%EXIT_CODE%"=="0" (
    echo.
    echo ============================================================
    echo Process exited with code %EXIT_CODE%.
    echo ============================================================
    pause
)

exit /b %EXIT_CODE%
