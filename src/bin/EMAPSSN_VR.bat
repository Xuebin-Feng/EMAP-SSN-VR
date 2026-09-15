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

REM =========================================================================
REM Portable Startup Script for the EMAP-SSN VR Configuration GUI (EMAPSSN_Config_VR.py)
REM =========================================================================
REM Mirrors the parent's src\bin\EMAPSSN.bat, with one difference: opt_vr owns no virtual
REM environment. It is a submodule of EMAP-SSN and imports the main program's
REM src tree for everything scientific, so it runs in the parent's managed
REM .venv. Creating, repairing and validating that environment - the uv
REM bootstrap, uv venv --python 3.12, Install_Dependencies.py and the
REM cross-process setup lock - is delegated to the parent launcher, so there
REM is one implementation and one lock instead of two that can drift apart.
REM
REM There is no .sh counterpart, by design. VR_App holds a Windows Unity
REM build, so the VR front end is Windows-only; the main program stays
REM cross-platform.
REM
REM Modes:
REM   (none)         validate the environment, then open the VR Config GUI
REM   --check-only   exit 0 when the managed environment is ready, else 10
REM   --setup-only   create or repair the managed environment, then exit
REM   --run-only     open the GUI, assuming the environment is already valid
REM =========================================================================
setlocal EnableDelayedExpansion
set "LAUNCH_MODE=%~1"
call :SANITIZE_MANAGED_ENVIRONMENT

:: Move to the submodule root (two levels up from src\bin\), then locate
:: the parent checkout one level above that.
cd /d "%~dp0..\.."
set "OPT_VR_ROOT=%CD%"
cd /d "%OPT_VR_ROOT%\.."
set "PROJECT_ROOT=%CD%"
cd /d "%OPT_VR_ROOT%"

set "PARENT_LAUNCHER=%PROJECT_ROOT%\src\bin\EMAPSSN.bat"
set "VENV_PYTHON=%PROJECT_ROOT%\.venv\Scripts\python.exe"
set "CONFIG_GUI=%OPT_VR_ROOT%\src\EMAPSSN_Config_VR.py"
set "INSTANCE_PROBE=%OPT_VR_ROOT%\src\bin\Single_Instance_Probe_VR.py"

if not exist "!PARENT_LAUNCHER!" (
    echo Error: the EMAP-SSN launcher was not found at:
    echo     !PARENT_LAUNCHER!
    echo.
    echo opt_vr must sit inside an EMAP-SSN checkout. Clone the parent
    echo repository and initialise this submodule:
    echo     git clone https://github.com/Xuebin-Feng/EMAP-SSN.git
    echo     git -C EMAP-SSN submodule update --init opt_vr
    if /I not "%LAUNCH_MODE%"=="--check-only" pause
    exit /b 1
)

:: An already-open VR window is raised instead of starting a second one.
if "%LAUNCH_MODE%"=="" call :ACTIVATE_EXISTING_INSTANCE
if "%LAUNCH_MODE%"=="" if !ERRORLEVEL! equ 0 exit /b 0
if /I "%LAUNCH_MODE%"=="--run-only" call :ACTIVATE_EXISTING_INSTANCE
if /I "%LAUNCH_MODE%"=="--run-only" if !ERRORLEVEL! equ 0 exit /b 0

:: 1. Read-only validation of the parent's managed environment.
if /I "%LAUNCH_MODE%"=="--check-only" (
    call "!PARENT_LAUNCHER!" --check-only
    exit /b !ERRORLEVEL!
)

:: 2. Creation or repair, serialized by the parent launcher's setup lock.
if /I "%LAUNCH_MODE%"=="--setup-only" (
    call "!PARENT_LAUNCHER!" --setup-only
    exit /b !ERRORLEVEL!
)

if /I "%LAUNCH_MODE%"=="--run-only" (
    if not exist "!VENV_PYTHON!" exit /b 10
    goto RUN_APPLICATION
)

:: Default: validate, repair only if validation failed, then run.
call "!PARENT_LAUNCHER!" --check-only
if !ERRORLEVEL! neq 0 (
    echo Setup or repair of the EMAP-SSN environment is required...
    call "!PARENT_LAUNCHER!" --setup-only
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
    exit /b 10
)

:: 3. Run the VR configuration tool.
:RUN_APPLICATION
call :ACTIVATE_EXISTING_INSTANCE
if !ERRORLEVEL! equ 0 exit /b 0
echo Starting EMAP-SSN VR Configuration...
"!VENV_PYTHON!" "!CONFIG_GUI!"
set "APP_EXIT=!ERRORLEVEL!"

:: Keep window open on error or exit
if !APP_EXIT! neq 0 (
    echo Application exited with code !APP_EXIT!.
    pause
)
exit /b !APP_EXIT!

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
