# Copyright 2026 Xuebin Feng
# Author affiliation: University of Toronto
# SPDX-License-Identifier: Apache-2.0

"""Detached monitor for the VR Configuration GUI started by the desktop launcher.

This is the VR counterpart of ``src/desktop/Desktop_Launcher_Monitor.py`` and
implements the same startup contract, so a VR shortcut behaves exactly like the
EMAP-SSN and EMAP-SSN Tools shortcuts:

1. the visible startup terminal runs ``--launch-and-wait``, which detaches this
   module with ``CREATE_NO_WINDOW`` and blocks;
2. the detached copy starts ``EMAPSSN_Config_VR.py`` with ``SSN_GUI_READY_FILE`` set and
   its output redirected to ``application.log``;
3. ``show_window_in_front`` inside the GUI writes ``gui.ready`` once the Qt
   window is actually on screen;
4. the terminal sees the ready file, writes ``terminal.dismissed`` and closes,
   leaving the GUI running with no console behind it.

Only the app script differs from upstream, so the policy - environment
sanitising, the atomic ready/exit files, the dismissal handshake, the error
terminal - is imported from the upstream module rather than copied. Reaching
for its underscore-prefixed helpers is deliberate: opt_vr reuses the main
program verbatim wherever it can, because vendoring copies is what let the
previous fork drift. The upstream test suite reaches for the same helpers.

A separate module is needed because upstream's ``APP_SCRIPTS`` maps launcher
kinds to scripts under ``src``, and the detached child re-enters *this* file by
path. Teaching the main program about ``opt_vr/EMAPSSN_Config_VR.py`` would make it name a
file that is absent whenever the submodule is not checked out.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys

VR_SRC_DIR = Path(__file__).resolve().parents[1]
if str(VR_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(VR_SRC_DIR))

import _bootstrap_vr  # noqa: E402  (puts the parent src tree on sys.path)

from desktop import Desktop_Launcher_Monitor as upstream  # noqa: E402

#: The submodule root. The GUI runs with this as its working directory
#: because every relative directory a VR setting names resolves there.
OPT_VR_DIR = Path(_bootstrap_vr.OPT_VR_DIR)

try:
    from utilities.Terminal_Launcher import TerminalUnavailableError  # noqa: E402
except ModuleNotFoundError:  # pragma: no cover - mirrors the upstream fallback
    from Terminal_Launcher import TerminalUnavailableError  # type: ignore[no-redef]


#: The GUI this monitor supervises.
VR_CONFIG_SCRIPT = VR_SRC_DIR / "EMAPSSN_Config_VR.py"
VR_CONFIG_LABEL = "EMAP-SSN VR Configuration"

#: Re-exported so the launcher's exit-code table reads the same as upstream's.
STARTUP_READY = upstream.STARTUP_READY
STARTUP_APPLICATION_EXITED = upstream.STARTUP_APPLICATION_EXITED
STARTUP_TIMEOUT = upstream.STARTUP_TIMEOUT
STARTUP_LAUNCH_FAILED = upstream.STARTUP_LAUNCH_FAILED

wait_for_startup_state = upstream.wait_for_startup_state


def _detachment_flags(platform_name: str) -> dict[str, object]:
    """Keep a child process off the startup console."""
    if platform_name == "win32":
        return {
            "creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        }
    # Unreachable in a supported installation - the entry point refuses to run
    # off Windows - but it keeps the module importable for tests on any host.
    return {"start_new_session": True}


def launch_detached_monitor(
    state_dir: Path,
    *,
    platform_name: str | None = None,
) -> subprocess.Popen:
    """Start the long-lived monitor without inheriting the startup terminal."""
    state_dir = Path(state_dir).resolve()
    state_dir.mkdir(parents=True, exist_ok=True)
    platform_name = platform_name or sys.platform
    command = [sys.executable, "-u", str(Path(__file__).resolve()), str(state_dir)]
    popen_kwargs: dict[str, object] = {
        # opt_vr, not the parent root: EMAPSSN_Config_VR.py resolves every relative
        # directory inside the submodule.
        "cwd": str(OPT_VR_DIR),
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
    }
    popen_kwargs.update(_detachment_flags(platform_name))
    return subprocess.Popen(command, **popen_kwargs)


def launch_and_wait(state_dir: Path) -> int:
    """Detach the monitor, then keep the startup terminal until Qt is ready."""
    try:
        monitor_process = launch_detached_monitor(state_dir)
    except OSError as error:
        print(
            f"Failed to launch the detached VR desktop monitor: {error}",
            file=sys.stderr,
        )
        return STARTUP_LAUNCH_FAILED

    state = wait_for_startup_state(Path(state_dir), monitor_process)
    if state == "ready":
        return STARTUP_READY
    if state == "application_exited":
        return STARTUP_APPLICATION_EXITED
    if state == "timeout":
        return STARTUP_TIMEOUT

    print(
        "The detached VR desktop monitor exited before reporting GUI readiness.",
        file=sys.stderr,
    )
    return STARTUP_LAUNCH_FAILED


def run_monitor(state_dir: Path) -> int:
    """Supervise the GUI process and publish its startup state."""
    state_dir = Path(state_dir).resolve()
    ready_path = state_dir / "gui.ready"
    dismissed_path = state_dir / "terminal.dismissed"
    exit_path = state_dir / "application.exit"
    log_path = state_dir / "application.log"
    state_dir.mkdir(parents=True, exist_ok=True)

    # No Wayland/XWayland policy here: upstream needs it because the desktop
    # program also starts from Linux .desktop entries, which VR never does.
    env = upstream._sanitize_managed_environment(os.environ.copy())
    env["SSN_GUI_READY_FILE"] = str(ready_path)

    return_code = 1
    try:
        with log_path.open("w", encoding="utf-8", newline="\n") as log_handle:
            process = subprocess.Popen(
                [upstream._console_python(), "-u", str(VR_CONFIG_SCRIPT)],
                cwd=str(OPT_VR_DIR),
                env=env,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                **_detachment_flags(sys.platform),
            )
            upstream._atomic_write(state_dir / "application.pid", f"{process.pid}\n")
            return_code = int(process.wait())
    except Exception as error:
        with log_path.open("a", encoding="utf-8", newline="\n") as log_handle:
            print(f"VR desktop launcher monitor failed: {error}", file=log_handle)

    ready_seen = ready_path.exists()
    upstream._atomic_write(exit_path, f"{return_code}\n")

    if return_code == 0:
        upstream._wait_for_dismissal(dismissed_path)
        upstream._cleanup_success(state_dir)
        return 0

    # The startup terminal has already closed by the time a ready GUI fails, so
    # that failure needs a terminal of its own to be seen at all.
    if ready_seen and upstream._wait_for_dismissal(dismissed_path):
        try:
            upstream._open_error_terminal(log_path)
        except (OSError, TerminalUnavailableError) as error:
            upstream._report_terminal_failure(log_path, error)
    return return_code


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--launch-and-wait",
        action="store_true",
        help="detach the monitor and wait for GUI startup state",
    )
    parser.add_argument("state_dir", type=Path)
    args = parser.parse_args(argv)

    _bootstrap_vr.require_windows("The EMAP-SSN VR desktop launcher")

    if args.launch_and_wait:
        return launch_and_wait(args.state_dir)
    return run_monitor(args.state_dir)


if __name__ == "__main__":
    raise SystemExit(main())
