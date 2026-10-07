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

set "FORCE=0"
if /i "%~1"=="/y" set "FORCE=1"
if /i "%~1"=="-y" set "FORCE=1"
if /i "%~1"=="/yes" set "FORCE=1"
if /i "%~1"=="--yes" set "FORCE=1"
if /i "%~1"=="/f" set "FORCE=1"
if /i "%~1"=="--force" set "FORCE=1"

if "%FORCE%"=="0" (
    echo ============================================================
    echo WARNING: This will permanently uninstall Embedded Notebook:
    echo   - User configuration in %%APPDATA%%\EmbeddedNotebook
    echo   - ALL files and subdirectories in: %PROJECT_ROOT%
    echo     (including .embedded toolchains and .venv)
    echo ============================================================
    echo.
    set /p "CONFIRM=Are you sure you want to permanently delete everything? [y/N]: "
    if /i not "%CONFIRM%"=="y" if /i not "%CONFIRM%"=="yes" (
        echo Uninstallation aborted.
        exit /b 0
    )
)

echo.
echo Uninstalling Embedded Notebook...

REM 1. Remove user settings
if exist "%APPDATA%\EmbeddedNotebook" (
    echo Removing user settings...
    rd /s /q "%APPDATA%\EmbeddedNotebook" 2>nul
)

REM 2. Remove project directory safely from TEMP
echo Removing project directory: %PROJECT_ROOT%
cd /d "%TEMP%"
start "" /b cmd /c ping 127.0.0.1 -n 2 ^>nul ^& rd /s /q "%PROJECT_ROOT%"

echo.
echo Uninstallation complete! All files will be removed.
exit /b 0
