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
set "PYTHONW_EXE=%VENV%\Scripts\pythonw.exe"

REM Choose windowless pythonw.exe if available so no extra console pops up when launched from shortcut
set "LAUNCH_PYTHON=%PYTHONW_EXE%"
if not exist "%LAUNCH_PYTHON%" set "LAUNCH_PYTHON=%PYTHON_EXE%"

if exist "%PROJECT_ROOT%\embedded_notebook2.py" (
    set "TARGET_SCRIPT=%PROJECT_ROOT%\embedded_notebook2.py"
) else (
    set "TARGET_SCRIPT=%PROJECT_ROOT%\scripts\main.py"
)

set "ICON_PATH=%SCRIPT_DIR%\arduino.ico"
if not exist "%ICON_PATH%" (
    if exist "%PROJECT_ROOT%\Windows\arduino.ico" set "ICON_PATH=%PROJECT_ROOT%\Windows\arduino.ico"
    if exist "%PROJECT_ROOT%\arduino.ico" set "ICON_PATH=%PROJECT_ROOT%\arduino.ico"
)

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

REM Create Desktop Shortcut to run on the .venv
echo.
echo Creating Desktop shortcut...

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$ws = New-Object -ComObject WScript.Shell; " ^
    "$desk = [System.Environment]::GetFolderPath('Desktop'); " ^
    "$sc = $ws.CreateShortcut((Join-Path $desk 'Embedded Notebook.lnk')); " ^
    "$sc.TargetPath = '%LAUNCH_PYTHON%'; " ^
    "$sc.Arguments = '\"%TARGET_SCRIPT%\"'; " ^
    "$sc.WorkingDirectory = '%PROJECT_ROOT%'; " ^
    "$sc.Description = 'Embedded Notebook - Arduino-style C/C++ Notebook Environment'; " ^
    "if (Test-Path '%ICON_PATH%') { $sc.IconLocation = '%ICON_PATH%'; } " ^
    "$sc.Save();"

if errorlevel 1 (
    echo WARNING: Failed to create shortcut via PowerShell, attempting VBScript fallback...
    set "VBS_FILE=%TEMP%\create_shortcut_%RANDOM%.vbs"
    (
        echo Set WshShell = CreateObject^("WScript.Shell"^)
        echo strDesktop = WshShell.SpecialFolders^("Desktop"^)
        echo Set oLink = WshShell.CreateShortcut^(strDesktop ^& "\Embedded Notebook.lnk"^)
        echo oLink.TargetPath = "%LAUNCH_PYTHON%"
        echo oLink.Arguments = """%TARGET_SCRIPT%"""
        echo oLink.WorkingDirectory = "%PROJECT_ROOT%"
        echo oLink.Description = "Embedded Notebook"
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
echo Shortcut 'Embedded Notebook' has been created on your Desktop.
echo You can launch the application anytime from your Desktop.
echo ============================================================
echo.
pause
