# Copyright 2026 Xuebin Feng
# Author affiliation: University of Toronto
# SPDX-License-Identifier: Apache-2.0

"""Detached monitor for the VR Configuration GUI started by the desktop launcher.

This is the VR counterpart of ``src/desktop/Desktop_Launcher_Monitor.py``, and it is that monitor with
one window added: ``register_application`` tells it which script is the VR Configuration GUI, which
folder to run it in, and which file to start for it, and ``main`` is upstream's. So the whole startup
contract is upstream's, and a VR launch behaves exactly like an EMAP-SSN or EMAP-SSN Tools launch:

1. the launcher (``Desktop_Launcher_VR.py``, which the Windows shortcut starts through EMAP-SSN.exe, or
   the visible startup terminal ``EMAPSSN_Desktop_Launcher_VR.bat``) detaches this module with
   ``CREATE_NO_WINDOW``;
2. the detached copy starts ``EMAPSSN_Config_VR.py`` with ``SSN_GUI_READY_FILE`` and
   ``SSN_STARTUP_STATUS_FILE`` set and its output redirected to ``application.log``;
3. ``show_window_in_front`` inside the GUI writes ``gui.ready`` once the Qt window is actually on
   screen, and the GUI reports its progress to the splash through ``startup.status``;
4. the launcher sees the ready file, writes ``terminal.dismissed`` and closes its splash or terminal,
   leaving the GUI running with no console behind it.

The command line is upstream's, with the kind first (the batch file passes ``vr``):

    python -u Desktop_Launcher_Monitor_VR.py [--launch-and-wait] [--failure-report terminal|dialog] vr STATE_DIR

The policy - environment sanitising, the atomic ready/exit files, the dismissal handshake, the crash
report - is imported from the upstream module rather than copied, because vendoring copies is what let
the previous fork drift.

A separate script is needed because the detached child re-enters the file the application names by
path. Teaching the main program about ``opt_vr/EMAPSSN_Config_VR.py`` would make it name a file that is
absent whenever the submodule is not checked out.
"""

from __future__ import annotations

from pathlib import Path
import sys

VR_SRC_DIR = Path(__file__).resolve().parents[1]
if str(VR_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(VR_SRC_DIR))

import _bootstrap_vr  # noqa: E402  (puts the parent src tree on sys.path)

from desktop import Desktop_Launcher_Monitor as upstream  # noqa: E402

#: The submodule root. The GUI runs with this as its working directory
#: because every relative directory a VR setting names resolves there.
OPT_VR_DIR = Path(_bootstrap_vr.OPT_VR_DIR)

#: The launcher kind of this window, as the batch file, EMAP-SSN.exe and the launcher name it.
KIND = "vr"

#: The GUI this monitor supervises.
VR_CONFIG_SCRIPT = VR_SRC_DIR / "EMAPSSN_Config_VR.py"
VR_CONFIG_LABEL = "EMAP-SSN VR Configuration"

#: Re-exported so the launcher's exit-code table reads the same as upstream's.
STARTUP_READY = upstream.STARTUP_READY
STARTUP_APPLICATION_EXITED = upstream.STARTUP_APPLICATION_EXITED
STARTUP_TIMEOUT = upstream.STARTUP_TIMEOUT
STARTUP_LAUNCH_FAILED = upstream.STARTUP_LAUNCH_FAILED

wait_for_startup_state = upstream.wait_for_startup_state


def register():
    """Add the VR Configuration GUI to the upstream monitor, in whichever process is about to use it.

    The detached monitor makes this call to run the GUI, and the launcher makes it to start the
    detached monitor (the file named here is what it starts).
    """
    upstream.register_application(
        KIND, VR_CONFIG_SCRIPT, OPT_VR_DIR, monitor=Path(__file__).resolve()
    )


def main(argv: list[str] | None = None) -> int:
    _bootstrap_vr.require_windows("The EMAP-SSN VR desktop launcher")
    register()
    return upstream.main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
