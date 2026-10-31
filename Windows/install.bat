@echo off
setlocal EnableDelayedExpansion

REM Directory where this batch script is located
set "SCRIPT_DIR=%~dp0"
set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"

REM Resolve project root (parent if located in Windows/)
if exist "%SCRIPT_DIR%\requirements.txt" (
    set "PROJECT_ROOT=%SCRIPT_DIR%"
) else (
    for %%I in ("%SCRIPT_DIR%\..") do set "PROJECT_ROOT=%%~fI"
)

REM Virtual environment and executable paths
set "VENV=%PROJECT_ROOT%\.venv"
set "PYTHON_EXE=%VENV%\Scripts\python.exe"

if exist "%PROJECT_ROOT%\embedded_notebook2.py" (
    set "TARGET_SCRIPT=%PROJECT_ROOT%\embedded_notebook2.py"
) else (
    set "TARGET_SCRIPT=%PROJECT_ROOT%\scripts\main.py"
)

set "ICON_PATH=%SCRIPT_DIR%\embeddednotebook.ico"
if not exist "%ICON_PATH%" set "ICON_PATH=%PROJECT_ROOT%\Windows\embeddednotebook.ico"
if not exist "%ICON_PATH%" set "ICON_PATH=%PROJECT_ROOT%\embeddednotebook.ico"

REM Path to Windows runner script
set "RUN_BAT=%SCRIPT_DIR%\run.bat"

echo ============================================================
echo   Embedded Notebook - Windows Setup
echo ============================================================
echo Project root: %PROJECT_ROOT%
echo.

REM Create .venv if it doesn't exist
if not exist "%PYTHON_EXE%" (
    echo .venv not found. Creating virtual environment...
    python -m venv "%VENV%"

    if errorlevel 1 (
        echo.
        echo ERROR: Failed to create virtual environment. Make sure Python 3 is installed.
        pause
        exit /b 1
    )
)

REM Install/update requirements
echo Installing/updating Python requirements...
"%PYTHON_EXE%" -m pip install -r "%PROJECT_ROOT%\requirements.txt"

if errorlevel 1 (
    echo.
    echo ERROR: Failed to install requirements.
    pause
    exit /b 1
)

REM Create Desktop shortcut with Embedded Notebook icon (cleaning any legacy Desktop bat/folder)
echo.
echo Creating Desktop shortcut...

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$desk = [System.Environment]::GetFolderPath('Desktop'); " ^
    "if (-not $desk -or -not (Test-Path $desk)) { $desk = Join-Path $env:USERPROFILE 'Desktop'; } " ^
    "$oldBat = Join-Path $desk 'Embedded Notebook.bat'; " ^
    "if (Test-Path $oldBat) { Remove-Item -Path $oldBat -Force; } " ^
    "$oldFolder = Join-Path $desk 'Embedded Notebook'; " ^
    "if (Test-Path $oldFolder) { Remove-Item -Path $oldFolder -Recurse -Force; } " ^
    "$ws = New-Object -ComObject WScript.Shell; " ^
    "$lnk = $ws.CreateShortcut((Join-Path $desk 'Embedded Notebook.lnk')); " ^
    "$lnk.TargetPath = '%RUN_BAT%'; " ^
    "$lnk.WorkingDirectory = '%PROJECT_ROOT%'; " ^
    "$lnk.Description = 'Embedded Notebook - Arduino-style C/C++ Notebook Environment'; " ^
    "$lnk.WindowStyle = 1; " ^
    "if (Test-Path '%ICON_PATH%') { $lnk.IconLocation = '%ICON_PATH%'; } " ^
    "$lnk.Save();"

if errorlevel 1 (
    echo WARNING: Failed to create shortcut via PowerShell, attempting VBScript fallback...
    set "VBS_FILE=%TEMP%\create_shortcut_%RANDOM%.vbs"
    (
        echo Set WshShell = CreateObject^("WScript.Shell"^)
        echo strDesktop = WshShell.SpecialFolders^("Desktop"^)
        echo If strDesktop = "" Then strDesktop = WshShell.ExpandEnvironmentStrings^("%%USERPROFILE%%\Desktop"^)
        echo Set oLink = WshShell.CreateShortcut^(strDesktop ^& "\Embedded Notebook.lnk"^)
        echo oLink.TargetPath = "%RUN_BAT%"
        echo oLink.WorkingDirectory = "%PROJECT_ROOT%"
        echo oLink.Description = "Embedded Notebook"
        echo oLink.WindowStyle = 1
        echo If CreateObject^("Scripting.FileSystemObject"^).FileExists^("%ICON_PATH%"^) Then
        echo     oLink.IconLocation = "%ICON_PATH%"
        echo End If
        echo oLink.Save
    ) > "%VBS_FILE%"
    cscript //nologo "%VBS_FILE%"
    del /f /q "%VBS_FILE%" 2>nul
)

echo.
echo ============================================================
echo Setup completed successfully!
echo.
echo Created 'Embedded Notebook' shortcut with icon on your Desktop.
echo Launcher is located at:
echo   %RUN_BAT%
echo.
echo No batch files or subfolders were added to your Desktop.
echo.
echo You can launch Embedded Notebook anytime via:
echo   - The Desktop shortcut
echo   - Running 'Windows\run.bat'
echo ============================================================
echo.
pause
