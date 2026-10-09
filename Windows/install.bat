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

REM Create Desktop BAT launcher and configure its icon
echo.
echo Creating Desktop BAT launcher with arduino.ico...

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$desk = [System.Environment]::GetFolderPath('Desktop'); " ^
    "$batFolder = Join-Path $desk 'Embedded Notebook'; " ^
    "if (-not (Test-Path $batFolder)) { New-Item -ItemType Directory -Path $batFolder -Force | Out-Null; } " ^
    "$batFile = Join-Path $batFolder 'Embedded Notebook.bat'; " ^
    "$content = \"@echo off`r`ncd /d `\"%PROJECT_ROOT%`\"`r`nstart `\"`\" `\"%PYTHON_EXE%`\" `\"%TARGET_SCRIPT%`\"`r`nexit`r`n\"; " ^
    "[System.IO.File]::WriteAllText($batFile, $content); " ^
    "if (Test-Path '%ICON_PATH%') { " ^
    "    $iconDest = Join-Path $batFolder 'arduino.ico'; " ^
    "    Copy-Item -Path '%ICON_PATH%' -Destination $iconDest -Force; " ^
    "    $iniPath = Join-Path $batFolder 'desktop.ini'; " ^
    "    if (Test-Path $iniPath) { attrib -h -s $iniPath; } " ^
    "    $ini = \"[.ShellClassInfo]`r`nIconResource=arduino.ico,0`r`n[ViewState]`r`nMode=`r`nVid=`r`nFolderType=Generic`r`n\"; " ^
    "    [System.IO.File]::WriteAllText($iniPath, $ini); " ^
    "    attrib +h +s $iniPath; " ^
    "    attrib +r $batFolder; " ^
    "} " ^
    "$directBat = Join-Path $desk 'Embedded Notebook.bat'; " ^
    "[System.IO.File]::WriteAllText($directBat, $content); " ^
    "$ws = New-Object -ComObject WScript.Shell; " ^
    "$lnk = $ws.CreateShortcut((Join-Path $desk 'Embedded Notebook.lnk')); " ^
    "$lnk.TargetPath = $directBat; " ^
    "$lnk.WorkingDirectory = '%PROJECT_ROOT%'; " ^
    "$lnk.Description = 'Run Embedded Notebook in .venv'; " ^
    "if (Test-Path '%ICON_PATH%') { $lnk.IconLocation = '%ICON_PATH%'; } " ^
    "$lnk.Save();"

echo.
echo ============================================================
echo Setup completed successfully!
echo Created 'Embedded Notebook.bat' on your Desktop.
echo Double-clicking it runs the application inside .venv.
echo ============================================================
echo.
pause
