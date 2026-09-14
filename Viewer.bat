@echo off
REM =========================================================================
REM Startup script for the EMAP-SSN VR viewer (opt_vr).
REM
REM This launches the 3D viewer only. It does NOT generate layouts: opt_vr
REM consumes a layout cache published by the main EMAP-SSN program. Create one
REM with src\Layout_Cache_Generator.py using LAYOUT_DIMENSIONS = 3, then point
REM TARGET_CACHE_PATH in viewer_settings.json (or %SSN_TARGET_CACHE%) at it.
REM =========================================================================

REM Move to the directory containing this batch script
cd /d "%~dp0"

REM opt_vr is a submodule of EMAP-SSN, so the parent venv is one level up.
if not exist "..\.venv" (
    echo Error: EMAP-SSN virtual environment '..\.venv' not found.
    echo opt_vr must sit inside an EMAP-SSN checkout. Run the main installer
    echo in the parent directory first to set up dependencies.
    pause
    exit /b 1
)

set "PYTHON_EXE=..\.venv\Scripts\python.exe"
set "SCRIPT_NAME=SSN_VR_Viewer.py"

echo Starting EMAP-SSN VR viewer...
"%PYTHON_EXE%" "%SCRIPT_NAME%"

REM Keeps the command window open so you can see any error messages
pause
