@echo off
REM Copyright 2026 Xuebin Feng
REM Author affiliation: University of Toronto
REM
REM Licensed under the Apache License, Version 2.0 (the "License");
REM you may not use this file except in compliance with the License.
REM You may obtain a copy of the License at
REM
REM     http://www.apache.org/licenses/LICENSE-2.0
REM
REM Unless required by applicable law or agreed to in writing, software
REM distributed under the License is distributed on an "AS IS" BASIS,
REM WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
REM See the License for the specific language governing permissions and
REM limitations under the License.
REM
REM Visible desktop startup terminal for the EMAP-SSN VR Configuration GUI.
REM
REM The VR counterpart of the parent's src\bin\EMAPSSN_Desktop_Launcher.bat. The terminal
REM stays visible only while there is something to report - dependency setup, or a
REM startup failure - and closes itself as soon as the Qt window signals that it is
REM on screen, so a healthy launch leaves no console behind.
REM
REM The "EMAP-SSN VR" shortcut starts "EMAP-SSN.exe vr" instead (install_vr.bat), which
REM shows the start-up splash through Desktop_Launcher_VR.py and opens no console at all.
REM This file is its console path: the shortcut of an installation that could not build
REM EMAP-SSN.exe, the first start (it creates the environment, which needs a console to
REM show what it does), "EMAP-SSN.exe vr --console", and a launcher that failed before
REM it showed anything. It does everything the splash does, in this console.
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

:: The GUI is still useful without a headset - choosing caches, generating
:: layouts - so an unsupported result is reported and then launched past,
:: rather than refused. The pause is what makes it readable: this terminal
:: closes itself the moment the Qt window is up.
echo Checking VR hardware...
call "!PORTABLE_LAUNCHER!" --check-hardware
if !ERRORLEVEL! neq 0 (
    echo.
    echo !APP_LABEL! will still open, but a headset may not work on this machine.
    pause
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
"!VENV_PYTHON!" -u "!LAUNCH_MONITOR!" --launch-and-wait vr "!STATE_DIR!"
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
