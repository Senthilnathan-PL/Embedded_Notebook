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

REM Determine Python executable (use pythonw.exe to run without a background console window)
set "PYTHON_EXEC=%VENV%\Scripts\pythonw.exe"
if not exist "%PYTHON_EXEC%" (
    set "PYTHON_EXEC=%VENV%\Scripts\python.exe"
)

set "TARGET_SCRIPT=%WORK_DIR%\embedded_notebook2.py"
set "ICON_FILE=%WORK_DIR%\arduino.ico"
set "SHORTCUT_NAME=Embedded Notebook.lnk"

REM Create desktop shortcut
echo.
echo Creating desktop shortcut...

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$ws = New-Object -ComObject WScript.Shell; " ^
    "$desktop = [Environment]::GetFolderPath('Desktop'); " ^
    "$shortcutPath = Join-Path $desktop $env:SHORTCUT_NAME; " ^
    "$s = $ws.CreateShortcut($shortcutPath); " ^
    "$s.TargetPath = $env:PYTHON_EXEC; " ^
    "$s.Arguments = '\""' + $env:TARGET_SCRIPT + '\""'; " ^
    "$s.WorkingDirectory = $env:WORK_DIR; " ^
    "$s.Description = 'Embedded Notebook'; " ^
    "if (Test-Path $env:ICON_FILE) { $s.IconLocation = $env:ICON_FILE; } " ^
    "$s.Save(); " ^
    "Write-Host ('Desktop shortcut created: ' + $shortcutPath)"

if errorlevel 1 (
    echo.
    echo ERROR: Failed to create desktop shortcut.
    pause
    exit /b 1
)

echo.
echo Setup completed successfully!
echo You can now launch Embedded Notebook from the desktop shortcut.
echo.
pause

