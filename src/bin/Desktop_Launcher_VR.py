# Copyright 2026 Xuebin Feng
# Author affiliation: University of Toronto
# SPDX-License-Identifier: Apache-2.0

"""The first stage of a Windows launch of VR Configuration: the splash, the checks, and the hand-off to the monitor.

    python -u opt_vr\\src\\bin\\Desktop_Launcher_VR.py vr [--console]

EMAP-SSN.exe (src/bin/Launcher.cs in the main program, built by install.bat or install_vr.bat) starts it
for ``EMAP-SSN.exe vr``, the target of the "EMAP-SSN VR" shortcut, with a hidden console. It is the main
program's launcher (desktop/Desktop_Launcher.py) with one kind of window added, so it shows the same splash
and does the same things in the same order:

1. brings the VR window forward and ends if one is already open (the probe of
   ``Single_Instance_Probe_VR.py``, as the batch file's, finds the same window by the same key);
2. shows the splash, with VR Configuration's name and art, in the theme colour the window has saved
   (VR_CONFIG_THEME_SETTING; purple where there is none);
3. checks the managed environment (the main program's), and hands over to the visible console
   (``EMAPSSN_Desktop_Launcher_VR.bat``) if it needs setup or repair;
4. checks the VR hardware (``Detect_GPU_VR.py``) as a step of its own. The Configuration window is useful
   without a headset, so a machine that cannot drive one gets a warning, not a refusal: the splash opens its
   details by itself with what the check printed, in the warning colour, the start goes on, and the splash,
   open, stays at Ready until Close is pressed. That replaces the pause of the batch file;
5. starts ``Desktop_Launcher_Monitor_VR.py`` detached, which runs ``EMAPSSN_Config_VR.py`` and
   follows what it reports, and closes the splash when the window is ready.

Everything VR-specific is declared here, in opt_vr; the main program's launcher, splash and monitor name
none of it (EMAP-SSN.exe names only this script and the batch file). Run with --console, or whenever
the launcher fails before it shows anything, the stub opens the batch file in a console instead.
"""

from __future__ import annotations

from pathlib import Path
import sys

BIN_DIR = Path(__file__).resolve().parent
VR_SRC_DIR = BIN_DIR.parent
for _path in (str(VR_SRC_DIR), str(BIN_DIR)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import _bootstrap_vr  # noqa: E402  (puts the parent src tree on sys.path)

import Desktop_Launcher_Monitor_VR  # noqa: E402
from desktop import Desktop_Launcher, Splash  # noqa: E402
from utilities import Startup_Status as Status  # noqa: E402

# The launcher kind of this window, as EMAP-SSN.exe and the batch file name it.
KIND = Desktop_Launcher_Monitor_VR.KIND

# The key of VR Config's single-instance channel: what EMAPSSN_Config_VR.py hands to
# SingleInstanceController and Single_Instance_Probe_VR.py asks for. It differs from the desktop
# Config's, so the two windows can be open at the same time. (The launcher does not import the probe,
# which loads the window's whole toolkit; tests keep the two in step.)
VR_CONFIG_APPLICATION_ID = "SSN_VR_Config"

# The taskbar identity of the VR window and of its shortcut (install_vr.bat gives the shortcut the same,
# and desktop.Desktop_App.APP_USER_MODEL_IDS["vr_config"] is what the window sets), so Windows groups the
# launcher's and the window's windows under the "EMAP-SSN VR" shortcut, not under Config's.
VR_CONFIG_APP_USER_MODEL_ID = "ca.utoronto.emapssn.vrconfig"

# The app_settings.json setting that holds VR Configuration's theme colour (what the window reads with
# desktop.Desktop_App.VR_CONFIG_THEME_SETTING; the launcher does not import Desktop_App, which loads the window's toolkit,
# and tests keep the two in step). The splash takes its accents in that colour: the main program's launcher reads the
# setting a kind names and passes the colour on, and names none itself.
VR_CONFIG_THEME_SETTING = "VR_CONFIG_THEME_COLOR"

# The 512 px copy of the VR logo the splash draws (the shipped one decodes to 75 MB).
SPLASH_LOGO = BIN_DIR / "logos" / "splash_logo_vr_512.png"

# The visible-console launch: the first start (it sets the environment up), --console, and a launcher failure.
BATCH_FILE = BIN_DIR / "EMAPSSN_Desktop_Launcher_VR.bat"

# Whether this machine can drive a headset: reported, never enforced. Exit 0 is ready; 10, 11 and 12 say
# why not (see Detect_GPU_VR.EXIT_CODES), and all three are a warning here.
HARDWARE_CHECK = VR_SRC_DIR / "Detect_GPU_VR.py"

# VR's own texts are in opt_vr's catalog, with the "Splash" context the splash looks them up in.
CATALOGS = ((VR_SRC_DIR / "resources" / "languages", "emapssn_vr"),)

SUBTITLE = Status.QT_TRANSLATE_NOOP("Splash", "VR Configuration")
CHECKING_HARDWARE = Status.QT_TRANSLATE_NOOP("Splash", "Checking VR hardware…")
HARDWARE_WARNING = Status.QT_TRANSLATE_NOOP(
    "Splash", "EMAP-SSN VR Configuration will still open, but a headset may not work on this machine."
)


def hardware_command(root, python):
    """The hardware check, as EMAPSSN_VR.bat --check-hardware runs it (-u, so its lines are not held back)."""
    return [str(python), "-u", str(HARDWARE_CHECK)]


HARDWARE_STEP = Desktop_Launcher.LaunchStep(CHECKING_HARDWARE, hardware_command, HARDWARE_WARNING)

VR_KIND = Desktop_Launcher.LaunchKind(
    name=KIND,
    splash_kind=KIND,
    application_id=VR_CONFIG_APPLICATION_ID,
    batch_file=BATCH_FILE,
    steps=(HARDWARE_STEP,),
    app_user_model_id=VR_CONFIG_APP_USER_MODEL_ID,
    catalogs=CATALOGS,
    theme_setting=VR_CONFIG_THEME_SETTING,
)


def register():
    """Add VR Configuration to the main program's launcher, splash and monitor; returns its launcher kind."""
    Desktop_Launcher_Monitor_VR.register()
    Splash.register_kind(KIND, SUBTITLE, SPLASH_LOGO)
    return Desktop_Launcher.register_kind(VR_KIND)


def main(argv=None):
    _bootstrap_vr.require_windows("The EMAP-SSN VR desktop launcher")
    register()
    return Desktop_Launcher.entry(argv)


if __name__ == "__main__":
    raise SystemExit(main())
