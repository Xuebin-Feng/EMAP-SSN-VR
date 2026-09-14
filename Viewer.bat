@echo off
REM =========================================================================
REM Startup script for the EMAP-SSN VR viewer (opt_vr).
REM
REM This opens the VR Configuration GUI, where the dataset, network, threshold
REM and layout cache are chosen. Its Save & Run button launches the VR viewer.
REM
REM The VR viewer always solves three dimensional layouts, so there is no 2D/3D
REM option: dimensionality follows from which viewer you opened. Settings are
REM written to opt_vr\vr_settings.json and every directory resolves inside this
REM submodule, so the desktop program's configuration is never touched.
REM
REM To skip the GUI and open the viewer directly against the saved settings,
REM run Viewer.py instead.
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
set "CONFIG_GUI=Config.py"

echo Opening EMAP-SSN VR Configuration...
"%PYTHON_EXE%" "%CONFIG_GUI%"

REM Keeps the command window open so you can see any error messages
pause
