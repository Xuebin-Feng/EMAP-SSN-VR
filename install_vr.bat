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
REM Installation and Shortcut Generation Script for EMAP-SSN VR (opt_vr)
REM =========================================================================
REM The VR counterpart of the main program's install.bat. It generates one
REM shortcut, "EMAP-SSN VR.lnk", pointing at the visible-startup desktop
REM launcher, and optionally copies it to the Desktop.
REM
REM There is no install.sh counterpart, by design: unity/ holds a Windows
REM Unity build, so the VR front end is Windows-only. Run the parent
REM project's installer for the cross-platform desktop program.
REM
REM This installer never writes into the parent checkout, and it does not
REM create the Python environment - the generated shortcut does that on its
REM first run, through the main program's own launcher.
REM =========================================================================
setlocal EnableDelayedExpansion

:: Move to the directory containing this batch script (the submodule root),
:: then locate the parent checkout one level above it.
cd /d "%~dp0"
set "OPT_VR_ROOT=%CD%"
cd /d "%OPT_VR_ROOT%\.."
set "PROJECT_ROOT=%CD%"
cd /d "%OPT_VR_ROOT%"

echo Setting up the shortcut for EMAP-SSN VR...
echo Submodule root:  !OPT_VR_ROOT!
echo Parent checkout: !PROJECT_ROOT!

:: 1. opt_vr cannot run standalone: EMAPSSN_Config_VR.py and EMAPSSN_Viewer_VR.py import the main
::    program's src tree for everything scientific.
if not exist "!PROJECT_ROOT!\src\bin\EMAPSSN.bat" (
    echo.
    echo Error: this is not an EMAP-SSN checkout. Expected to find:
    echo     !PROJECT_ROOT!\src\bin\EMAPSSN.bat
    echo.
    echo opt_vr is a submodule of EMAP-SSN. Clone the parent repository and
    echo initialise it from there:
    echo     git clone https://github.com/Xuebin-Feng/EMAP-SSN.git
    echo     git -C EMAP-SSN submodule update --init opt_vr
    pause
    exit /b 1
)

:: 2. opt_vr ships no logo assets of its own, so the shortcut borrows the
::    parent's viewer icon. The main installer is what generates those .ico
::    files from .png; this one only reads them.
set "VR_ICON=!PROJECT_ROOT!\src\bin\logos\viewer_logo_large.ico"
if not exist "!VR_ICON!" (
    echo [INFO] !VR_ICON! is missing, so the shortcut will use the default icon.
    echo        Run install.bat in !PROJECT_ROOT! once to generate it.
    set "VR_ICON="
)

:: 3. Create a visible-startup Windows shortcut for the VR Configuration GUI.
::    The launcher's terminal closes itself once the Qt window is on screen.
echo Creating shortcut for EMAP-SSN VR...
powershell -ExecutionPolicy Bypass -Command "$q = [char]34; $WshShell = New-Object -ComObject WScript.Shell; $Shortcut = $WshShell.CreateShortcut($env:OPT_VR_ROOT + '\EMAP-SSN VR.lnk'); $Shortcut.TargetPath = $env:WINDIR + '\System32\cmd.exe'; $Shortcut.Arguments = '/d /c ' + $q + $q + $env:OPT_VR_ROOT + '\src\bin\EMAPSSN_Desktop_Launcher_VR.bat' + $q + $q; $Shortcut.WorkingDirectory = $env:OPT_VR_ROOT; $Shortcut.Description = 'EMAP-SSN VR Configuration'; if ($env:VR_ICON) { $Shortcut.IconLocation = $env:VR_ICON }; $Shortcut.Save();"
if exist "EMAP-SSN VR.lnk" (
    echo [OK] Created "EMAP-SSN VR.lnk" in !OPT_VR_ROOT!.
) else (
    echo [ERROR] The shortcut could not be created.
    pause
    exit /b 1
)

:: 4. Optional: Copy the shortcut to the Desktop
echo.
choice /M "Would you like to copy this shortcut to your Desktop"
if %ERRORLEVEL% equ 1 (
    for /f "usebackq tokens=*" %%i in (`powershell -NoProfile -Command "[Environment]::GetFolderPath('CommonDesktopDirectory')"`) do set "COMMON_DESKTOP=%%i"
    for /f "usebackq tokens=*" %%i in (`powershell -NoProfile -Command "[Environment]::GetFolderPath('Desktop')"`) do set "USER_DESKTOP=%%i"

    echo Copying the shortcut to the Public Desktop at !COMMON_DESKTOP!...
    copy "!OPT_VR_ROOT!\EMAP-SSN VR.lnk" "!COMMON_DESKTOP!\EMAP-SSN VR.lnk" /Y >nul 2>nul

    if !ERRORLEVEL! neq 0 (
        echo [INFO] Writing to the Public Desktop requires Administrator privileges - Access Denied.
        echo Falling back: copying the shortcut to your personal Desktop at !USER_DESKTOP!...
        copy "!OPT_VR_ROOT!\EMAP-SSN VR.lnk" "!USER_DESKTOP!\EMAP-SSN VR.lnk" /Y >nul
        echo [OK] Shortcut copied to your personal Desktop.
    ) else (
        echo [OK] Shortcut copied to the Public Desktop.
    )
)

echo.
echo Setup complete. Open EMAP-SSN VR with the "EMAP-SSN VR" shortcut.
echo The first launch creates and validates the parent project's managed
echo Python environment, so it takes noticeably longer than later ones.
pause
