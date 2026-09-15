@echo off
REM Visible desktop startup terminal for the EMAP-SSN VR Configuration GUI.
REM
REM The VR counterpart of the parent's src\bin\EMAPSSN_Desktop_Launcher.bat, and the target
REM of the "EMAP-SSN VR" shortcut. The terminal stays visible only while there
REM is something to report - dependency setup, or a startup failure - and
REM closes itself as soon as the Qt window signals that it is on screen, so a
REM healthy launch leaves no console behind.
setlocal EnableDelayedExpansion
call :SANITIZE_MANAGED_ENVIRONMENT

:: Move to the submodule root (two levels up from src\bin\), then locate
:: the parent checkout one level above that.
cd /d "%~dp0..\.."
set "OPT_VR_ROOT=%CD%"
cd /d "%OPT_VR_ROOT%\.."
set "PROJECT_ROOT=%CD%"
cd /d "%OPT_VR_ROOT%"

set "APP_LABEL=EMAP-SSN VR Configuration"
set "PORTABLE_LAUNCHER=%OPT_VR_ROOT%\src\bin\EMAPSSN_VR.bat"
set "LAUNCH_MONITOR=%OPT_VR_ROOT%\src\bin\Desktop_Launcher_Monitor_VR.py"
set "INSTANCE_PROBE=%OPT_VR_ROOT%\src\bin\Single_Instance_Probe_VR.py"
set "VENV_PYTHON=%PROJECT_ROOT%\.venv\Scripts\python.exe"

if not exist "!PORTABLE_LAUNCHER!" (
    echo Could not find !PORTABLE_LAUNCHER!.
    pause
    exit /b 1
)

call :ACTIVATE_EXISTING_INSTANCE
if !ERRORLEVEL! equ 0 exit /b 0

echo Starting !APP_LABEL!...
echo Detecting hardware and validating dependencies...
call "!PORTABLE_LAUNCHER!" --check-only
if !ERRORLEVEL! neq 0 (
    echo.
    echo Setup or repair is required. The terminal will remain visible.
    call "!PORTABLE_LAUNCHER!" --setup-only
    if !ERRORLEVEL! neq 0 (
        echo.
        echo EMAP-SSN setup failed. Review the errors above.
        pause
        exit /b 1
    )
)

if not exist "!VENV_PYTHON!" (
    echo Expected !VENV_PYTHON! after setup, but it was not found.
    pause
    exit /b 1
)

call :ACTIVATE_EXISTING_INSTANCE
if !ERRORLEVEL! equ 0 exit /b 0

for /f %%I in ('powershell -NoProfile -Command "[guid]::NewGuid().ToString('N')"') do set "LAUNCH_TOKEN=%%I"
set "STATE_DIR=%OPT_VR_ROOT%\temp\vr_!LAUNCH_TOKEN!"
mkdir "!STATE_DIR!" >nul 2>nul
if not exist "!STATE_DIR!" (
    echo Could not create launcher state directory: !STATE_DIR!
    pause
    exit /b 1
)

echo Launching the Qt window...
"!VENV_PYTHON!" -u "!LAUNCH_MONITOR!" --launch-and-wait "!STATE_DIR!"
set "LAUNCH_RESULT=!ERRORLEVEL!"
if !LAUNCH_RESULT! equ 0 goto GUI_READY
if !LAUNCH_RESULT! equ 20 goto GUI_EXITED
if !LAUNCH_RESULT! equ 21 goto GUI_TIMEOUT
echo.
if exist "!STATE_DIR!\application.log" type "!STATE_DIR!\application.log"
echo Failed to start the detached !APP_LABEL! monitor.
echo Launcher state retained at: !STATE_DIR!
pause
exit /b !LAUNCH_RESULT!

:GUI_READY
>"!STATE_DIR!\terminal.dismissed" echo dismissed
echo !APP_LABEL! is ready.
exit /b 0

:GUI_EXITED
set "APP_EXIT=1"
set /p APP_EXIT=<"!STATE_DIR!\application.exit"
if "!APP_EXIT!"=="0" (
    >"!STATE_DIR!\terminal.dismissed" echo dismissed
    exit /b 0
)
echo.
if exist "!STATE_DIR!\application.log" type "!STATE_DIR!\application.log"
echo.
echo !APP_LABEL! failed before its window became ready.
echo Log retained at: !STATE_DIR!\application.log
pause
exit /b !APP_EXIT!

:GUI_TIMEOUT
echo.
echo !APP_LABEL! did not report a ready window within 10 minutes.
echo The terminal will remain open. Diagnostic log:
echo !STATE_DIR!\application.log
pause
exit /b 1

:ACTIVATE_EXISTING_INSTANCE
if not exist "!VENV_PYTHON!" exit /b 1
"!VENV_PYTHON!" "!INSTANCE_PROBE!" >nul 2>nul
exit /b !ERRORLEVEL!

:SANITIZE_MANAGED_ENVIRONMENT
set "PYTHONHOME="
set "PYTHONPATH="
set "QT_PLUGIN_PATH="
set "QT_QPA_PLATFORM_PLUGIN_PATH="
set "QML_IMPORT_PATH="
set "QML2_IMPORT_PATH="
exit /b 0
