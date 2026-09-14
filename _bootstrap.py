# Copyright 2026 Xuebin Feng
# Author affiliation: University of Toronto
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Make the parent EMAP-SSN ``src`` tree importable from ``opt_vr``.

``opt_vr`` is a submodule of EMAP-SSN and deliberately owns no part of the
calculation pipeline. Sequence sanitization, embeddings, alignment, network
construction and layout generation are all the main program's responsibility;
this package only consumes the layout cache the main program publishes and
bridges it to the Unity client.

Two things are set up here:

1. ``<project>/src`` and ``<project>/src/utilities`` go on ``sys.path``, so
   upstream modules import exactly as they do for the desktop viewer.
2. ``install_settings_alias`` registers the Qt-free VR settings module under
   the name upstream expects (``EMAPSSN_Config``). Several upstream modules -
   ``Alignment_Manager`` among them - do ``import EMAPSSN_Config as cfg``,
   which would otherwise drag PySide6 into a process that must stay
   headless. Registering the stand-in first means those modules can be reused
   verbatim instead of forked, which is what caused the previous drift.
"""

from __future__ import annotations

import os
import sys


if sys.stdout is not None and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if sys.stderr is not None and hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


OPT_VR_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(OPT_VR_DIR)
SRC_DIR = os.path.join(PROJECT_ROOT, "src")
UTILITIES_DIR = os.path.join(SRC_DIR, "utilities")


def _require_parent_checkout() -> None:
    if not os.path.isdir(SRC_DIR):
        raise ImportError(
            "opt_vr expects to sit inside an EMAP-SSN checkout, but "
            f"{SRC_DIR!r} does not exist. Clone the parent repository and "
            "initialise this submodule with:\n"
            "    git clone https://github.com/Xuebin-Feng/EMAP-SSN.git\n"
            "    git -C EMAP-SSN submodule update --init opt_vr"
        )


_require_parent_checkout()

# Order matters: opt_vr MUST precede src, or `import commands` resolves to the
# main program's package and every local override is silently ignored. Entries
# are removed first so a caller that already put one of these on sys.path
# cannot invert the precedence.
for _path in (SRC_DIR, UTILITIES_DIR, OPT_VR_DIR):
    while _path in sys.path:
        sys.path.remove(_path)
    sys.path.insert(0, _path)


def apply_settings_argument(argv) -> str | None:
    """Honour ``--settings PATH [--delete-settings]`` from the command line.

    The Config GUI writes one private settings snapshot per launch and passes
    it to the viewer this way; it is the same contract the desktop viewer
    implements, which is what lets ``EMAPSSN_Config --viewer`` drive either
    front end without special-casing one of them.

    This lives in the bootstrap rather than in ``Viewer`` because ``Settings``
    reads its file at import time. Doing it here means any import order works:
    ``Settings`` imports this module before it looks the path up.

    Returns the snapshot to delete once it has been read, or ``None``.
    """
    path = None
    for index, token in enumerate(argv):
        if token == "--settings" and index + 1 < len(argv):
            path = argv[index + 1]
        elif token.startswith("--settings="):
            path = token.split("=", 1)[1]
    if path:
        os.environ["SSN_VIEWER_SETTINGS_PATH"] = path
    if "--delete-settings" not in argv:
        return None
    return os.environ.get("SSN_VIEWER_SETTINGS_PATH")


#: Snapshot the Config GUI asked the viewer to remove after reading it.
SETTINGS_SNAPSHOT_TO_DELETE = apply_settings_argument(sys.argv)


def install_settings_alias(module) -> None:
    """Publish ``module`` under the config names upstream modules import.

    Uses ``setdefault`` so a caller that has genuinely imported the real
    ``EMAPSSN_Config`` (for example a GUI process that also drives the VR
    bridge) keeps the module it already loaded.
    """
    for name in ("EMAPSSN_Config", "SSN_VR_Config"):
        sys.modules.setdefault(name, module)
