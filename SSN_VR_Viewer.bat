@echo off
REM =========================================================================
REM Startup Script for SSN_VR_Config.py (3D VR SSN Config & Server)
REM =========================================================================

REM Move to the directory containing this batch script
cd /d "%~dp0"

REM Check if the root .venv directory exists
if not exist "..\.venv" (
    echo Error: Root virtual environment '.venv' not found.
    echo Please run the main SSN_Viewer.bat in the root directory first to set up dependencies.
    pause
    exit /b 1
)

set "PYTHON_EXE=..\.venv\Scripts\python.exe"
set "SCRIPT_NAME=SSN_VR_Config.py"

echo Starting VR SSN Config...
"%PYTHON_EXE%" "%SCRIPT_NAME%"

REM Keeps the command window open so you can see any error messages
pause
