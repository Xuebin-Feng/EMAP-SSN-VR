# Copyright 2026 Xuebin Feng
# Author affiliation: University of Toronto
# SPDX-License-Identifier: Apache-2.0

"""Launcher probe for activating an existing VR Configuration window.

The VR counterpart of ``src/desktop/Single_Instance_Probe.py``. Upstream's probe
only knows the ``viewer`` and ``tools`` application ids; this one knows the VR
key, which is deliberately distinct so the VR window and the desktop Config
window can be open at the same time instead of one raising the other.

Exit status is the launcher contract: 0 means a window was found and asked to
come forward, so the caller should stop; non-zero means nothing is running and
the caller should start the GUI.
"""

from __future__ import annotations

from pathlib import Path
import sys

VR_SRC_DIR = Path(__file__).resolve().parents[1]
if str(VR_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(VR_SRC_DIR))

import _bootstrap_vr  # noqa: E402,F401  (puts the parent src tree on sys.path)

from PySide6.QtCore import QCoreApplication  # noqa: E402

from desktop.Desktop_App import notify_existing_instance  # noqa: E402


#: Must match the key EMAPSSN_Config_VR.py hands to SingleInstanceController.
VR_CONFIG_APPLICATION_ID = "SSN_VR_Config"


def main(argv: list[str] | None = None) -> int:
    QCoreApplication.instance() or QCoreApplication([])
    return 0 if notify_existing_instance(VR_CONFIG_APPLICATION_ID) else 1


if __name__ == "__main__":
    raise SystemExit(main())
