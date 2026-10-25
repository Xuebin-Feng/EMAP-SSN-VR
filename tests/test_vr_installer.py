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

"""install_vr.bat: the "EMAP-SSN VR" shortcut starts EMAP-SSN.exe vr (no console, a splash), with VR's large icon and
no taskbar identity (VR Config sets its own, with the small icon); the launcher is built, with the script the main installer uses, when it is missing
or older than its source (one built before "vr" was a window would open the wrong one); and a machine that cannot
build it keeps the shortcut that runs the VR batch file in a console. The run tests use a scratch copy of the files
the installer needs, a stand-in for the client download and no Desktop copy, and open no window."""

import os
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

OPT_VR = Path(__file__).resolve().parents[1]
VR_SRC = OPT_VR / "src"
if str(VR_SRC) not in sys.path:
    sys.path.insert(0, str(VR_SRC))

import _bootstrap_vr  # noqa: E402

PROJECT_ROOT = Path(_bootstrap_vr.PROJECT_ROOT)
BIN_DIR = VR_SRC / "bin"
INSTALLER = OPT_VR / "install_vr.bat"
MAIN_BIN = PROJECT_ROOT / "src" / "bin"
CREATE_NO_WINDOW = 0x08000000


def find_csc():
    windir = os.environ.get("WINDIR")
    if sys.platform != "win32" or not windir:
        return None
    for folder in ("Framework64", "Framework"):
        path = Path(windir) / "Microsoft.NET" / folder / "v4.0.30319" / "csc.exe"
        if path.is_file():
            return path
    return None


CSC = find_csc()


class InstallerTextTests(unittest.TestCase):
    """What install_vr.bat says, which needs no compiler."""

    def setUp(self):
        self.text = INSTALLER.read_bytes().decode("utf-8")

    def test_the_shortcut_starts_the_parents_launcher_for_vr_with_the_batch_file_as_the_fallback(self):
        self.assertIn("$Shortcut.TargetPath = $env:LAUNCHER_EXE; $Shortcut.Arguments = 'vr'", self.text)
        self.assertIn('set "LAUNCHER_EXE=!PROJECT_ROOT!\\EMAP-SSN.exe"', self.text)
        self.assertIn("if ($env:USE_LAUNCHER_EXE)", self.text)
        self.assertIn("System32\\cmd.exe", self.text)
        self.assertIn("src\\bin\\EMAPSSN_Desktop_Launcher_VR.bat", self.text)
        self.assertIn("The shortcut will open the launcher in a console window instead.", self.text)

    def test_the_launcher_is_built_when_missing_or_old_by_the_script_the_main_installer_uses_too(self):
        self.assertIn('call "!PROJECT_ROOT!\\src\\bin\\Build_Launcher.bat" --if-needed', self.text)
        self.assertIn('if exist "!PROJECT_ROOT!\\src\\bin\\Build_Launcher.bat"', self.text)  # an older main has none
        self.assertNotIn("csc.exe", self.text)  # not a second copy of the build
        self.assertNotIn("/target:winexe", self.text)
        self.assertTrue((MAIN_BIN / "Build_Launcher.bat").is_file())
        self.assertIn('call "src\\bin\\Build_Launcher.bat"', (PROJECT_ROOT / "install.bat").read_text(encoding="utf-8"))
        # It runs before the shortcut that needs to know whether it worked.
        self.assertLess(self.text.index("Build_Launcher.bat"), self.text.index("$Shortcut.TargetPath"))

    def test_the_shortcut_carries_no_taskbar_identity_because_the_window_would_get_its_large_icon(self):
        import re

        from desktop.Desktop_App import APP_USER_MODEL_IDS

        self.assertNotIn("-AppId", self.text)
        self.assertNotIn("Set_Shortcut_AppId", self.text)
        window_id = re.search(r'^VR_CONFIG_APP_USER_MODEL_ID = "([^"]+)"', (VR_SRC / "EMAPSSN_Config_VR.py").read_text(encoding="utf-8"), re.M).group(1)
        self.assertNotIn(window_id, self.text)
        for app_id in APP_USER_MODEL_IDS.values():
            self.assertNotIn(app_id, self.text)
        self.assertIn("vr_logo_large.ico", self.text)  # the shortcut keeps the large icon, for the desktop

    def test_the_shortcut_is_still_named_and_iconed_as_before(self):
        self.assertIn("'\\EMAP-SSN VR.lnk'", self.text)
        self.assertIn("$Shortcut.IconLocation = $env:VR_ICON", self.text)
        self.assertIn("$Shortcut.WorkingDirectory = $env:OPT_VR_ROOT", self.text)

    def test_line_endings_are_what_cmd_needs(self):
        data = INSTALLER.read_bytes()
        self.assertEqual(data.count(b"\n"), data.count(b"\r\n"))
        self.assertNotIn(b"\r\r", data)


@unittest.skipUnless(CSC is not None, "the .NET Framework C# compiler is not installed")
class InstallerRunTests(unittest.TestCase):
    """install_vr.bat run in a scratch copy of the files it needs: nothing is made outside it, and no window opens."""

    def tree(self):
        folder = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(folder.cleanup)
        root = Path(folder.name) / "project root"
        main_bin = root / "src" / "bin"
        (main_bin / "logos").mkdir(parents=True)
        for name in ("Launcher.cs", "Build_Launcher.bat"):
            shutil.copyfile(MAIN_BIN / name, main_bin / name)
        (main_bin / "EMAPSSN.bat").write_text("@echo off\r\n", encoding="utf-8")  # only its presence is checked
        shutil.copyfile(MAIN_BIN / "logos" / "viewer_logo_large.ico", main_bin / "logos" / "viewer_logo_large.ico")
        opt_vr = root / "opt_vr"
        (opt_vr / "src" / "bin" / "logos").mkdir(parents=True)
        shutil.copyfile(INSTALLER, opt_vr / "install_vr.bat")
        shutil.copyfile(BIN_DIR / "logos" / "vr_logo_large.ico", opt_vr / "src" / "bin" / "logos" / "vr_logo_large.ico")
        # The client download is the one step that would reach the network: a stand-in that says it is installed.
        (opt_vr / "src" / "bin" / "Install_Client_VR.ps1").write_text(
            "param([string]$OptVr, [switch]$Force)\nexit 0\n", encoding="utf-8")
        return root

    @staticmethod
    def install(root, windir=None):
        environment = dict(os.environ)
        if windir is not None:
            environment["WINDIR"] = windir
        # One string, so cmd gets the quotes as they are; "N" declines the copy to the Desktop.
        return subprocess.run(
            'cmd.exe /d /c "echo N| call .\\install_vr.bat"', cwd=str(root / "opt_vr"), env=environment,
            capture_output=True, text=True, timeout=240, creationflags=CREATE_NO_WINDOW,
        )

    @staticmethod
    def shortcut(path):
        script = (
            "$s = (New-Object -ComObject WScript.Shell).CreateShortcut($env:LNK); "
            "$i = (New-Object -ComObject Shell.Application).NameSpace((Split-Path $env:LNK)).ParseName((Split-Path $env:LNK -Leaf)); "
            "'TARGET=' + $s.TargetPath; 'ARGS=' + $s.Arguments; 'CWD=' + $s.WorkingDirectory; 'ICON=' + $s.IconLocation; "
            "'AUMID=' + $i.ExtendedProperty('System.AppUserModel.ID')"
        )
        done = subprocess.run(["powershell", "-NoProfile", "-Command", script], capture_output=True, text=True,
                              env=dict(os.environ, LNK=str(path)), timeout=60, creationflags=CREATE_NO_WINDOW)
        return dict(line.split("=", 1) for line in done.stdout.splitlines() if "=" in line)

    @staticmethod
    def subsystem(path):
        data = path.read_bytes()
        header = struct.unpack_from("<I", data, 0x3C)[0]
        return struct.unpack_from("<H", data, header + 24 + 68)[0]

    def test_it_builds_the_launcher_and_points_the_shortcut_at_it_for_vr_with_the_vr_icon_and_no_id(self):
        root = self.tree()
        done = self.install(root)
        self.assertIn("Built EMAP-SSN.exe", done.stdout, done.stdout + done.stderr)
        exe = root / "EMAP-SSN.exe"
        self.assertTrue(exe.is_file())  # in the parent project, where the main installer builds it too
        self.assertEqual(self.subsystem(exe), 2)  # no console window of its own
        found = self.shortcut(root / "opt_vr" / "EMAP-SSN VR.lnk")
        self.assertEqual(Path(found["TARGET"]), exe)
        self.assertEqual(found["ARGS"], "vr")
        self.assertEqual(Path(found["CWD"]), root / "opt_vr")
        self.assertTrue(found["ICON"].lower().endswith("vr_logo_large.ico,0"), found["ICON"])
        self.assertEqual(found["AUMID"], "")  # a window whose ID it carried would get its large icon in the taskbar
        # Nothing else was made in the parent, and the Desktop copy was declined.
        self.assertEqual(sorted(path.name for path in root.iterdir()), ["EMAP-SSN.exe", "opt_vr", "src"])
        self.assertEqual(sorted(path.name for path in (root / "opt_vr").iterdir()),
                         ["EMAP-SSN VR.lnk", "install_vr.bat", "src"])

    def test_a_launcher_that_is_there_and_current_is_left_alone(self):
        root = self.tree()
        self.install(root)
        before = (root / "EMAP-SSN.exe").stat().st_mtime_ns
        done = self.install(root)
        self.assertIn("up to date", done.stdout, done.stdout + done.stderr)
        self.assertEqual((root / "EMAP-SSN.exe").stat().st_mtime_ns, before)
        self.assertEqual(Path(self.shortcut(root / "opt_vr" / "EMAP-SSN VR.lnk")["TARGET"]), root / "EMAP-SSN.exe")

    def test_one_built_before_vr_was_a_window_would_open_the_wrong_one_so_it_is_built_again(self):
        root = self.tree()
        self.install(root)
        old = (root / "src" / "bin" / "Launcher.cs").stat().st_mtime - 3600
        os.utime(root / "EMAP-SSN.exe", (old, old))
        done = self.install(root)
        self.assertIn("Built EMAP-SSN.exe", done.stdout, done.stdout + done.stderr)
        self.assertGreater((root / "EMAP-SSN.exe").stat().st_mtime, old + 60)
        self.assertEqual(self.shortcut(root / "opt_vr" / "EMAP-SSN VR.lnk")["ARGS"], "vr")

    def test_without_the_compiler_the_shortcut_runs_the_vr_batch_file_in_a_console_as_before(self):
        root = self.tree()
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as empty:
            (Path(empty) / "System32").mkdir()
            done = self.install(root, windir=empty)
        self.assertIn("Could not build EMAP-SSN.exe", done.stdout, done.stdout + done.stderr)
        self.assertIn("The shortcut will open the launcher in a console window instead.", done.stdout)
        self.assertFalse((root / "EMAP-SSN.exe").exists())
        found = self.shortcut(root / "opt_vr" / "EMAP-SSN VR.lnk")
        self.assertTrue(found["TARGET"].lower().endswith("cmd.exe"), found["TARGET"])
        self.assertIn("EMAPSSN_Desktop_Launcher_VR.bat", found["ARGS"])
        self.assertTrue(found["ARGS"].startswith("/d /c "), found["ARGS"])
        self.assertEqual(found["AUMID"], "")

    def test_a_stale_launcher_that_cannot_be_replaced_does_not_become_the_shortcuts_target(self):
        root = self.tree()
        self.install(root)
        old = (root / "src" / "bin" / "Launcher.cs").stat().st_mtime - 3600
        os.utime(root / "EMAP-SSN.exe", (old, old))
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as empty:
            (Path(empty) / "System32").mkdir()
            self.install(root, windir=empty)
        found = self.shortcut(root / "opt_vr" / "EMAP-SSN VR.lnk")
        self.assertTrue(found["TARGET"].lower().endswith("cmd.exe"), found["TARGET"])  # it would open Config

    def test_an_older_main_program_without_the_build_script_keeps_the_batch_file_shortcut(self):
        root = self.tree()
        (root / "src" / "bin" / "Build_Launcher.bat").unlink()
        done = self.install(root)
        self.assertIn("older than this installer", done.stdout, done.stdout + done.stderr)
        self.assertFalse((root / "EMAP-SSN.exe").exists())
        self.assertIn("EMAPSSN_Desktop_Launcher_VR.bat", self.shortcut(root / "opt_vr" / "EMAP-SSN VR.lnk")["ARGS"])


if __name__ == "__main__":
    unittest.main()
