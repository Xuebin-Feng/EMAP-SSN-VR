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

Three things are set up here:

1. ``<project>/src`` and ``<project>/src/utilities`` go on ``sys.path``, so
   upstream modules import exactly as they do for the desktop viewer, and
   ``opt_vr/src`` goes on ahead of them.
2. The ``commands`` package is resolved immediately, while that ordering is
   known to hold, so no later edit to ``sys.path`` can silently swap the VR
   command overrides for the main program's.
3. ``install_settings_alias`` registers the Qt-free VR settings module under
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


#: ``opt_vr/src`` - this file's own directory, and the VR module tree.
VR_SRC_DIR = os.path.dirname(os.path.abspath(__file__))
#: The submodule root. Every relative directory a VR setting names - the
#: cache folder, the Unity build - resolves against this, not against
#: ``VR_SRC_DIR``, so the layout mirrors the main program's.
OPT_VR_DIR = os.path.dirname(VR_SRC_DIR)
#: The parent EMAP-SSN checkout, and its module tree.
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

# Order matters: opt_vr/src MUST precede the parent's src, or `import commands`
# resolves to the main program's package and every local override is silently
# ignored - as would `import Command_Engine` and `import Viewer_Command_Portal`,
# which upstream commands issue by those exact names. Entries are removed first
# so a caller that already put one of these on sys.path cannot invert the
# precedence.
for _path in (SRC_DIR, UTILITIES_DIR, VR_SRC_DIR):
    while _path in sys.path:
        sys.path.remove(_path)
    sys.path.insert(0, _path)


def _lock_command_package():
    """Resolve ``commands`` now, while opt_vr is known to win the path race.

    The loop above orders sys.path correctly, but sys.path is global and
    mutable, and ``commands`` is not imported until the user types their first
    command - a long way from here. Anything that ran in between and put the
    parent's ``src`` back in front would make ``import commands`` bind the main
    program's package, whose ``__init__`` never extends ``__path__``. All
    eleven local overrides would vanish with no error at all: ``zoom`` would
    reach for a VisPy canvas this process does not have, ``agent`` and
    ``esmfold`` would raise AttributeError deep inside a web backend instead of
    explaining themselves, and ``color`` would quietly answer to the desktop
    grammar. A silent wrong answer is the worst failure this module can
    produce, so the window is closed rather than documented.

    Importing here binds the package in sys.modules for the life of the
    process, where no later path edit can reach it. The cost is one trivial
    ``__init__`` that does nothing but join two paths.

    ``commands`` is also the honest canary for the other names upstream
    commands import by bare name - ``Command_Engine``, ``Viewer_Command_Portal``
    - because all of them depend on the single precondition this verifies:
    VR_SRC_DIR precedes SRC_DIR. Those two are left to import lazily, since
    pulling numpy and the upstream engine into every process that merely
    touches this bootstrap would cost far more than it protects.
    """
    local_package = os.path.join(VR_SRC_DIR, "commands")

    cached = sys.modules.get("commands")
    if cached is not None and not _is_local_package(cached, local_package):
        raise ImportError(
            "The main program's 'commands' package was imported before "
            "opt_vr's bootstrap ran, so every VR command override is already "
            "shadowed. Import _bootstrap_vr before any project module."
        )

    import commands

    if not _is_local_package(commands, local_package):
        raise ImportError(
            "'commands' resolved to "
            f"{getattr(commands, '__file__', '<unknown>')!r} instead of "
            f"{local_package!r}. Something reordered sys.path so the parent "
            "checkout precedes opt_vr/src; every VR command override would be "
            "silently ignored."
        )
    return commands


def _is_local_package(module, local_package) -> bool:
    """True when ``module`` is the package rooted at ``local_package``."""
    search_path = getattr(module, "__path__", None)
    if not search_path:
        return False
    return os.path.abspath(search_path[0]) == os.path.abspath(local_package)


_lock_command_package()


def apply_settings_argument(argv) -> str | None:
    """Honour ``--settings PATH [--delete-settings]`` from the command line.

    The Config GUI writes one private settings snapshot per launch and passes
    it to the viewer this way; it is the same contract the desktop viewer
    implements, which is what lets ``EMAPSSN_Config --viewer`` drive either
    front end without special-casing one of them.

    This lives in the bootstrap rather than in ``Viewer`` because ``Settings_VR``
    reads its file at import time. Doing it here means any import order works:
    ``Settings_VR`` imports this module before it looks the path up.

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


# ---------------------------------------------------------------------------
# Platform policy
# ---------------------------------------------------------------------------
# The main program is cross-platform: it ships .bat, .sh and .app launchers and
# an installer for each host. This submodule deliberately is not. ``unity/``
# holds a built Windows Unity player which ``EMAPSSN_Viewer_VR.py`` launches directly, and
# the headset runtimes it talks to are Windows-only, so there is nothing for a
# macOS or Linux user to run. Refusing at the entry point states that plainly
# instead of failing later on a missing ``.exe``.
#
# This is a function rather than a module-level guard on purpose: the settings,
# command and cache layers are ordinary Python and their tests must stay
# runnable anywhere. Only the entry points that reach the Unity build or the
# Windows desktop launchers call it.

WINDOWS_ONLY_PLATFORM = "win32"

#: Default subject for the refusal message, overridden per entry point.
VR_COMPONENT_NAME = "The EMAP-SSN VR front end"


def is_windows(platform_name: str | None = None) -> bool:
    """Report whether this host can run the VR front end."""
    return (platform_name or sys.platform) == WINDOWS_ONLY_PLATFORM


def windows_only_message(
    component: str = VR_COMPONENT_NAME,
    *,
    platform_name: str | None = None,
) -> str:
    """Explain why ``component`` refuses to start on this host."""
    reported = platform_name or sys.platform
    return "\n".join((
        f"{component} runs on Windows only.",
        f"This host reports sys.platform={reported!r}.",
        "",
        "opt_vr drives the built Unity player in unity/, which is a Windows",
        "build, so there is no VR runtime to start here. The main EMAP-SSN",
        "program is cross-platform, and its desktop viewer opens the same",
        "layout caches in 2D:",
        "    python src/EMAPSSN_Config.py",
    ))


def require_windows(
    component: str = VR_COMPONENT_NAME,
    *,
    platform_name: str | None = None,
    stream=None,
) -> None:
    """Exit with a clear explanation when a VR entry point is not on Windows."""
    if is_windows(platform_name):
        return
    print(
        windows_only_message(component, platform_name=platform_name),
        file=stream if stream is not None else sys.stderr,
    )
    raise SystemExit(1)
