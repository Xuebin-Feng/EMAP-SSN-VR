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

"""Tests for VR installation, environment validation and desktop launching.

The VR front end reaches the user the same way the main program does: an
installer writes a shortcut, the shortcut opens a visible terminal that
validates the managed environment, and that terminal closes itself once the Qt
window reports it is on screen. These tests pin the three things that are easy
to break silently:

* the launchers reuse the parent's environment and locking rather than carrying
  a second copy of it,
* the startup handshake uses the same file names and exit codes as upstream, so
  a change there is caught here instead of at a user's desktop, and
* every VR entry point refuses to run off Windows.

They are file- and API-level checks. The end-to-end launch needs a real Qt
window and a real desktop session, so it is not asserted here.
"""

import io
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

#: The submodule root; VR_SRC is its module tree.
OPT_VR = Path(__file__).resolve().parents[1]
VR_SRC = OPT_VR / "src"
if str(VR_SRC) not in sys.path:
    sys.path.insert(0, str(VR_SRC))

import _bootstrap_vr  # noqa: E402

PROJECT_ROOT = Path(_bootstrap_vr.PROJECT_ROOT)
BIN_DIR = VR_SRC / "bin"
INSTALLER = OPT_VR / "install_vr.bat"
PORTABLE_LAUNCHER = BIN_DIR / "EMAPSSN_VR.bat"
DESKTOP_LAUNCHER = BIN_DIR / "EMAPSSN_Desktop_Launcher_VR.bat"
UPSTREAM_LAUNCHER = PROJECT_ROOT / "src" / "bin" / "EMAPSSN.bat"


def read(path):
    return path.read_text(encoding="utf-8", errors="replace")


def batch_commands(path):
    """Return a batch script with its REM and :: comment lines removed.

    The launchers document what they delegate, so a plain text search finds the
    delegated command named in a comment and not run anywhere.
    """
    lines = [
        line
        for line in read(path).splitlines()
        if not line.strip().upper().startswith("REM ")
        and not line.strip().startswith("::")
    ]
    return "\n".join(lines)


class WindowsOnlyTests(unittest.TestCase):
    """VR is Windows-only; the main program stays cross-platform."""

    def test_platform_check_accepts_only_windows(self):
        self.assertTrue(_bootstrap_vr.is_windows("win32"))
        for platform_name in ("linux", "darwin", "cygwin", "win64"):
            self.assertFalse(_bootstrap_vr.is_windows(platform_name))

    def test_require_windows_is_a_no_op_on_windows(self):
        self.assertIsNone(_bootstrap_vr.require_windows(platform_name="win32"))

    def test_require_windows_exits_with_an_explanation_elsewhere(self):
        stream = io.StringIO()
        with self.assertRaises(SystemExit) as raised:
            _bootstrap_vr.require_windows(
                "The EMAP-SSN VR Viewer", platform_name="linux", stream=stream
            )
        self.assertEqual(raised.exception.code, 1)
        message = stream.getvalue()
        self.assertIn("The EMAP-SSN VR Viewer runs on Windows only.", message)
        self.assertIn("linux", message)
        # A refusal that does not say what to do instead is a dead end.
        self.assertIn("EMAPSSN_Config.py", message)

    def test_every_entry_point_guards_its_platform(self):
        entry_points = {
            VR_SRC / "EMAPSSN_Config_VR.py": "The EMAP-SSN VR Configuration GUI",
            VR_SRC / "EMAPSSN_Viewer_VR.py": "The EMAP-SSN VR Viewer",
            BIN_DIR / "Desktop_Launcher_Monitor_VR.py": "The EMAP-SSN VR desktop launcher",
        }
        for path, component in entry_points.items():
            with self.subTest(entry_point=path.name):
                source = read(path)
                self.assertIn(f'_bootstrap_vr.require_windows("{component}")', source)

    def test_no_posix_launcher_is_shipped(self):
        # The main program ships .sh and .command launchers beside its .bat
        # ones. opt_vr deliberately ships none: VR_App is a Windows build.
        for pattern in ("*.sh", "*.command"):
            stray = [
                path.name
                for path in OPT_VR.rglob(pattern)
                if ".git" not in path.parts
            ]
            with self.subTest(pattern=pattern):
                self.assertEqual(stray, [], f"unexpected POSIX launcher: {stray}")

    def test_batch_files_keep_crlf_endings(self):
        # cmd.exe mis-parses multi-line batch files that use LF.
        for path in sorted(OPT_VR.rglob("*.bat")):
            if ".git" in path.parts:
                continue
            with self.subTest(script=path.name):
                data = path.read_bytes()
                self.assertNotIn(
                    data.replace(b"\r\n", b""),
                    (b"",),
                    "unexpected empty batch file",
                )
                self.assertEqual(
                    data.count(b"\n"),
                    data.count(b"\r\n"),
                    "batch files must use CRLF endings",
                )


class EnvironmentValidationTests(unittest.TestCase):
    """The parent's managed .venv is validated, never duplicated."""

    def test_launchers_delegate_setup_to_the_parent_project(self):
        # opt_vr must not carry a second uv bootstrap, venv creation or setup
        # lock: two implementations of that is exactly how they drift.
        source = read(PORTABLE_LAUNCHER)
        self.assertIn("EMAPSSN.bat", source)
        for mode in ("--check-only", "--setup-only"):
            self.assertIn(f'call "!PARENT_LAUNCHER!" {mode}', source)
        commands = batch_commands(PORTABLE_LAUNCHER)
        upstream = read(UPSTREAM_LAUNCHER)
        for duplicated in (
            "astral.sh/uv",
            "venv --clear --python",
            "Install_Dependencies.py",
            ":ACQUIRE_SETUP_LOCK",
        ):
            with self.subTest(duplicated=duplicated):
                self.assertIn(
                    duplicated,
                    upstream,
                    f"{duplicated!r} is no longer what the parent launcher does",
                )
                self.assertNotIn(
                    duplicated,
                    commands,
                    f"{duplicated!r} is the parent launcher's job, not opt_vr's",
                )

    def test_launchers_use_the_parent_virtual_environment(self):
        for script in (PORTABLE_LAUNCHER, DESKTOP_LAUNCHER):
            with self.subTest(script=script.name):
                source = read(script)
                self.assertIn(
                    'set "VENV_PYTHON=%PROJECT_ROOT%\\.venv\\Scripts\\python.exe"',
                    source,
                )

    def test_desktop_launcher_validates_before_it_launches(self):
        source = read(DESKTOP_LAUNCHER)
        check = source.index('call "!PORTABLE_LAUNCHER!" --check-only')
        setup = source.index('call "!PORTABLE_LAUNCHER!" --setup-only')
        launch = source.index("--launch-and-wait")
        self.assertLess(check, setup, "repair must only follow a failed check")
        self.assertLess(setup, launch, "the GUI must start after validation")

    def test_launchers_sanitize_the_managed_environment(self):
        # Same overrides the upstream launchers clear, for the same reason: an
        # inherited PYTHONHOME or QT_PLUGIN_PATH redirects the managed stack.
        upstream = read(UPSTREAM_LAUNCHER)
        for script in (PORTABLE_LAUNCHER, DESKTOP_LAUNCHER):
            with self.subTest(script=script.name):
                source = read(script)
                self.assertIn(":SANITIZE_MANAGED_ENVIRONMENT", source)
                for name in (
                    "PYTHONHOME",
                    "PYTHONPATH",
                    "QT_PLUGIN_PATH",
                    "QT_QPA_PLATFORM_PLUGIN_PATH",
                    "QML_IMPORT_PATH",
                    "QML2_IMPORT_PATH",
                ):
                    self.assertIn(f'set "{name}="', upstream)
                    self.assertIn(f'set "{name}="', source)

    def test_installer_never_writes_into_the_parent_checkout(self):
        source = read(INSTALLER)
        self.assertIn("EMAP-SSN VR.lnk", source)
        self.assertIn("$env:OPT_VR_ROOT", source)
        # The parent's logos are read for the icon, never generated here.
        self.assertIn("viewer_logo_large.ico", source)
        self.assertNotIn("QPixmap", source)


class LauncherMonitorTests(unittest.TestCase):
    """The startup handshake matches the upstream desktop launcher's."""

    @classmethod
    def setUpClass(cls):
        if str(BIN_DIR) not in sys.path:
            sys.path.insert(0, str(BIN_DIR))
        import Desktop_Launcher_Monitor_VR

        cls.monitor = Desktop_Launcher_Monitor_VR
        from desktop import Desktop_Launcher_Monitor

        cls.upstream = Desktop_Launcher_Monitor

    def test_startup_codes_are_the_upstream_codes(self):
        # The .bat branches on these numbers, so a silent divergence would
        # send a healthy launch down the failure path.
        for name in (
            "STARTUP_READY",
            "STARTUP_APPLICATION_EXITED",
            "STARTUP_TIMEOUT",
            "STARTUP_LAUNCH_FAILED",
        ):
            with self.subTest(code=name):
                self.assertEqual(
                    getattr(self.monitor, name), getattr(self.upstream, name)
                )

    def test_desktop_launcher_branches_on_those_codes(self):
        source = read(DESKTOP_LAUNCHER)
        self.assertIn(
            f"if !LAUNCH_RESULT! equ {self.monitor.STARTUP_READY} goto GUI_READY",
            source,
        )
        self.assertIn(
            "if !LAUNCH_RESULT! equ "
            f"{self.monitor.STARTUP_APPLICATION_EXITED} goto GUI_EXITED",
            source,
        )
        self.assertIn(
            f"if !LAUNCH_RESULT! equ {self.monitor.STARTUP_TIMEOUT} goto GUI_TIMEOUT",
            source,
        )

    def test_monitor_supervises_the_vr_config_gui(self):
        self.assertEqual(self.monitor.VR_CONFIG_SCRIPT, VR_SRC / "EMAPSSN_Config_VR.py")
        self.assertTrue(self.monitor.VR_CONFIG_SCRIPT.is_file())

    def test_policy_is_imported_from_upstream_not_copied(self):
        # Every shared helper is the upstream object, so a fix there reaches
        # the VR launcher without anyone remembering to port it.
        self.assertIs(
            self.monitor.wait_for_startup_state, self.upstream.wait_for_startup_state
        )
        source = read(BIN_DIR / "Desktop_Launcher_Monitor_VR.py")
        for helper in (
            "_sanitize_managed_environment",
            "_console_python",
            "_atomic_write",
            "_wait_for_dismissal",
            "_cleanup_success",
            "_open_error_terminal",
            "_report_terminal_failure",
        ):
            with self.subTest(helper=helper):
                self.assertIn(f"upstream.{helper}", source)

    def test_gui_child_runs_detached_from_the_startup_terminal(self):
        recorded = {}

        class FakePopen:
            def __init__(self, command, **kwargs):
                recorded["command"] = command
                recorded["kwargs"] = kwargs

        with tempfile.TemporaryDirectory() as state_root:
            state_dir = Path(state_root) / "vr_state"
            with mock.patch.object(subprocess, "Popen", FakePopen):
                self.monitor.launch_detached_monitor(
                    state_dir, platform_name="win32"
                )

        self.assertEqual(
            recorded["command"][2],
            str((BIN_DIR / "Desktop_Launcher_Monitor_VR.py").resolve()),
            "the detached child must re-enter this module, not upstream's",
        )
        kwargs = recorded["kwargs"]
        self.assertEqual(
            kwargs["creationflags"],
            getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000),
        )
        self.assertEqual(kwargs["stdout"], subprocess.DEVNULL)
        self.assertEqual(kwargs["stderr"], subprocess.DEVNULL)
        # EMAPSSN_Config_VR.py resolves relative directories against opt_vr, not the
        # parent root the upstream monitor uses.
        self.assertEqual(kwargs["cwd"], str(OPT_VR))

    def test_ready_file_is_handed_to_the_gui(self):
        source = read(BIN_DIR / "Desktop_Launcher_Monitor_VR.py")
        self.assertIn('env["SSN_GUI_READY_FILE"] = str(ready_path)', source)
        # The name is upstream's contract: Desktop_App pops this variable when
        # the window becomes visible.
        self.assertIn(
            "SSN_GUI_READY_FILE",
            read(PROJECT_ROOT / "src" / "desktop" / "Desktop_App.py"),
        )

    def test_state_file_names_match_upstream(self):
        vr_source = read(BIN_DIR / "Desktop_Launcher_Monitor_VR.py")
        upstream_source = read(
            PROJECT_ROOT / "src" / "desktop" / "Desktop_Launcher_Monitor.py"
        )
        launcher_source = read(DESKTOP_LAUNCHER)
        for name in (
            "gui.ready",
            "terminal.dismissed",
            "application.exit",
            "application.log",
        ):
            with self.subTest(state_file=name):
                self.assertIn(name, vr_source)
                self.assertIn(name, upstream_source)
        for name in ("terminal.dismissed", "application.exit", "application.log"):
            self.assertIn(name, launcher_source)


class SingleInstanceTests(unittest.TestCase):
    """One VR window at a time, without disturbing the desktop Config window."""

    def test_probe_uses_the_key_the_gui_registers(self):
        source = read(BIN_DIR / "Single_Instance_Probe_VR.py")
        self.assertIn('VR_CONFIG_APPLICATION_ID = "SSN_VR_Config"', source)
        self.assertIn(
            'SingleInstanceController("SSN_VR_Config", app)',
            read(VR_SRC / "EMAPSSN_Config_VR.py"),
        )

    def test_vr_key_differs_from_the_desktop_program_keys(self):
        upstream_probe = read(
            PROJECT_ROOT / "src" / "desktop" / "Single_Instance_Probe.py"
        )
        self.assertIn('"SSN_Config"', upstream_probe)
        self.assertNotIn("SSN_VR_Config", upstream_probe)

    def test_launchers_probe_before_starting_anything(self):
        for script in (PORTABLE_LAUNCHER, DESKTOP_LAUNCHER):
            with self.subTest(script=script.name):
                source = read(script)
                self.assertIn(":ACTIVATE_EXISTING_INSTANCE", source)
                self.assertIn("Single_Instance_Probe_VR.py", source)


if __name__ == "__main__":
    unittest.main()
