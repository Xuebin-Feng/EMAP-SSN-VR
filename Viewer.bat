@echo off
REM =========================================================================
REM Startup script for the EMAP-SSN VR viewer (opt_vr).
REM
REM This opens the main program's Config GUI, which is where the dataset,
REM network, threshold and layout cache are chosen - opt_vr has no settings UI
REM of its own. The GUI's Launch button then starts the VR viewer instead of
REM the desktop viewer. Set LAYOUT_DIMENSIONS to 3 there for a true 3D layout.
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
set "CONFIG_GUI=..\src\EMAPSSN_Config.py"

REM The submodule locates the GUI, not the other way round: the main
REM program knows nothing about opt_vr and is simply told which viewer to
REM start via --viewer.
if not exist "%CONFIG_GUI%" (
    echo Error: the EMAP-SSN Config GUI was not found at "%CONFIG_GUI%".
    echo opt_vr is a submodule and expects to sit inside an EMAP-SSN checkout.
    pause
    exit /b 1
)

echo Opening EMAP-SSN Config (Launch starts the VR viewer)...
"%PYTHON_EXE%" "%CONFIG_GUI%" --viewer "%~dp0Viewer.py"

REM Keeps the command window open so you can see any error messages
pause
