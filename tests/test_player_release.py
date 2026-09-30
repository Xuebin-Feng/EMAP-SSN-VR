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

"""Tests for how the VR client reaches a user: the pin, the installer, the notices.

The client is not in git. ``player_release.json`` names one GitHub release
asset and its SHA-256, and ``install_vr.bat`` (through
``src/bin/Install_Client_VR.ps1``) downloads it, checks it and unpacks it into
``player/``. What matters most is what happens when something is wrong: a bad
archive must never be unpacked, and a failed install must leave the previous
client usable.

The installer runs against a throwaway opt_vr and a fabricated archive, so no
network and no real player are needed.
"""

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile

OPT_VR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VR_SRC = os.path.join(OPT_VR, "src")
if VR_SRC not in sys.path:
    sys.path.insert(0, VR_SRC)

import Player_Build_VR as build  # noqa: E402

PIN = os.path.join(OPT_VR, "player_release.json")
INSTALLER = os.path.join(OPT_VR, "install_vr.bat")
CLIENT_INSTALLER = os.path.join(VR_SRC, "bin", "Install_Client_VR.ps1")
NOTICES = os.path.join(OPT_VR, "THIRD_PARTY_NOTICES.md")
INSTALLED_PLAYER = os.path.join(OPT_VR, "player")

WINDOWS_ONLY = unittest.skipUnless(sys.platform == "win32", "the installer is Windows PowerShell")


def write_json(path, document):
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(document, handle)


class PinTests(unittest.TestCase):
    """The committed pin, and the reader that decides whether a pin is usable."""

    def test_the_committed_pin_is_complete(self):
        pin = build.read_release_pin(PIN)
        self.assertIsNotNone(pin, "player_release.json is missing, incomplete or implausible")
        self.assertEqual(pin["tag"], f"vr-client-v{pin['version']}")
        self.assertEqual(pin["asset"], f"EMAP-SSN-VR-Client-{pin['version']}-win64.zip")

    def test_incomplete_or_implausible_pins_are_refused(self):
        good = {"version": "1.0.0", "tag": "vr-client-v1.0.0",
                "asset": "EMAP-SSN-VR-Client-1.0.0-win64.zip", "sha256": "ab" * 32}
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, ignore_errors=True)
        path = os.path.join(folder, "player_release.json")
        write_json(path, good)
        self.assertEqual(build.read_release_pin(path), good)
        cases = {
            "missing version": {k: v for k, v in good.items() if k != "version"},
            "empty tag": {**good, "tag": ""},
            "numeric version": {**good, "version": 1},
            "short sha": {**good, "sha256": "ab" * 31},
            "upper-case sha": {**good, "sha256": "AB" * 32},
            "not an object": [good],
        }
        for name, document in cases.items():
            with self.subTest(case=name):
                write_json(path, document)
                self.assertIsNone(build.read_release_pin(path))
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("{not json")
        self.assertIsNone(build.read_release_pin(path))
        self.assertIsNone(build.read_release_pin(os.path.join(folder, "absent.json")))


class ClientDirMigrationTests(unittest.TestCase):
    """VR_APP_DIR saved for the Unity client points at the installed client."""

    def test_unity_era_defaults_move_to_player(self):
        for saved in ("unity", "unity/", "unity\\", " VR_App "):
            with self.subTest(saved=saved):
                self.assertEqual(build.migrate_client_dir(saved), "player")

    def test_chosen_folders_and_other_values_are_left_alone(self):
        for saved in ("player", "E:/builds/unity", "my_client", "", None, 5):
            with self.subTest(saved=saved):
                self.assertEqual(build.migrate_client_dir(saved), saved)

    def test_the_viewer_settings_apply_the_migration(self):
        saved_env = os.environ.get("SSN_VIEWER_SETTINGS_PATH")
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, ignore_errors=True)
        path = os.path.join(folder, "settings.json")
        write_json(path, {"VR_APP_DIR": "unity"})
        os.environ["SSN_VIEWER_SETTINGS_PATH"] = path
        try:
            import Settings_VR

            values = Settings_VR.load_settings()
        finally:
            if saved_env is None:
                os.environ.pop("SSN_VIEWER_SETTINGS_PATH", None)
            else:
                os.environ["SSN_VIEWER_SETTINGS_PATH"] = saved_env
        self.assertEqual(os.path.normpath(values["VR_APP_DIR"]),
                         os.path.normpath(os.path.join(OPT_VR, "player")))


class InstallerSourceTests(unittest.TestCase):
    """What the scripts must do, checked where running them cannot show it."""

    def read(self, path):
        with open(path, encoding="utf-8") as handle:
            return handle.read()

    def test_install_vr_bat_installs_the_client_before_the_shortcut(self):
        source = self.read(INSTALLER)
        install = source.index("Install_Client_VR.ps1")
        self.assertIn('-OptVr "!OPT_VR_ROOT!"', source)
        self.assertLess(install, source.index("CreateShortcut"))
        self.assertIn('if /i "%~1"=="--reinstall" set "CLIENT_FORCE=-Force"', source)
        self.assertIn("exit /b !CLIENT_STATUS!", source)

    def test_the_checksum_is_checked_before_anything_is_unpacked(self):
        source = self.read(CLIENT_INSTALLER)
        self.assertLess(source.index("$actual = Get-Sha256 $archive"),
                        source.index("ZipFile]::ExtractToDirectory"))

    def test_removing_the_previous_client_cannot_fail_an_install(self):
        """Once the new client is in place, cleanup is housekeeping, not an error."""
        source = self.read(CLIENT_INSTALLER)
        failure = source.index("exit 5")
        cleanup = source.index("could not be removed")
        self.assertLess(failure, cleanup, "the cleanup must sit after the failing block")
        self.assertLess(cleanup, source.index("[OK] Installed VR client"))
        tail = source[failure:source.index("[OK] Installed VR client")]
        self.assertIn("Remove-Item -Recurse -Force $Previous", tail)
        self.assertIn("catch", tail)

    def test_no_module_cmdlets_are_needed(self):
        # From a PowerShell 7 terminal, Windows PowerShell inherits a module
        # path that hides its own module cmdlets; .NET calls are unaffected.
        source = self.read(CLIENT_INSTALLER)
        body = source[source.index("#>"):]
        for cmdlet in ("Get-FileHash", "Expand-Archive", "Invoke-WebRequest"):
            with self.subTest(cmdlet=cmdlet):
                self.assertNotIn(cmdlet, body)
        self.assertIn('set "PSModulePath="', self.read(INSTALLER))

    def test_the_installer_script_is_ascii(self):
        # Windows PowerShell 5.1 reads a script without a BOM in the ANSI code
        # page, so anything outside ASCII would be misread.
        with open(CLIENT_INSTALLER, "rb") as handle:
            data = handle.read()
        self.assertTrue(all(byte < 128 for byte in data))

    def test_the_download_comes_from_this_repository(self):
        self.assertIn('$Repository = "Xuebin-Feng/EMAP-SSN-VR"', self.read(CLIENT_INSTALLER))


@WINDOWS_ONLY
class InstallerRunTests(unittest.TestCase):
    """Install_Client_VR.ps1 against a throwaway opt_vr and a fabricated archive."""

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        os.makedirs(os.path.join(self.root, "src"))
        # The script refuses a folder that is not an opt_vr checkout.
        open(os.path.join(self.root, "src", "EMAPSSN_Viewer_VR.py"), "w").close()
        self.player = os.path.join(self.root, "player")

    def archive(self, name, version="9.9.9", with_player=True):
        """A client zip holding a stand-in player, and its SHA-256."""
        path = os.path.join(self.root, name)
        with zipfile.ZipFile(path, "w") as archive:
            if with_player:
                archive.writestr("EMAP-SSN-VR.exe", b"MZ stand-in")
            archive.writestr("vr_client.json", json.dumps({"version": version}))
            archive.writestr("source/README.md", "source")
        with open(path, "rb") as handle:
            return path, hashlib.sha256(handle.read()).hexdigest()

    def pin(self, sha256, version="9.9.9"):
        write_json(os.path.join(self.root, "player_release.json"), {
            "version": version, "tag": f"vr-client-v{version}",
            "asset": f"EMAP-SSN-VR-Client-{version}-win64.zip", "sha256": sha256})

    def install(self, archive, *extra):
        result = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", CLIENT_INSTALLER,
             "-OptVr", self.root, "-Zip", archive, *extra],
            capture_output=True, text=True, timeout=120)
        return result.returncode, result.stdout + result.stderr

    def installed_version(self):
        with open(os.path.join(self.player, "vr_client.json"), encoding="utf-8") as handle:
            return json.load(handle)["version"]

    def assert_no_staging_left(self):
        for leftover in ("player.partial", "player.previous"):
            self.assertFalse(os.path.exists(os.path.join(self.root, leftover)), leftover)

    def test_a_matching_archive_is_installed_once(self):
        archive, sha256 = self.archive("client.zip")
        self.pin(sha256)
        code, output = self.install(archive)
        self.assertEqual(code, 0, output)
        self.assertEqual(self.installed_version(), "9.9.9")
        self.assertTrue(os.path.isfile(os.path.join(self.player, "source", "README.md")))
        self.assert_no_staging_left()

        code, output = self.install(archive)
        self.assertEqual(code, 0, output)
        self.assertIn("already installed", output)

    def test_a_new_pin_replaces_the_installed_client(self):
        old, old_sha = self.archive("old.zip", version="1.0.0")
        self.pin(old_sha, version="1.0.0")
        self.assertEqual(self.install(old)[0], 0)
        new, new_sha = self.archive("new.zip", version="1.1.0")
        self.pin(new_sha, version="1.1.0")
        code, output = self.install(new)
        self.assertEqual(code, 0, output)
        self.assertIn("from 1.0.0 to 1.1.0", output)
        self.assertEqual(self.installed_version(), "1.1.0")
        self.assert_no_staging_left()

    def test_a_checksum_mismatch_installs_nothing(self):
        good, good_sha = self.archive("good.zip", version="1.0.0")
        self.pin(good_sha, version="1.0.0")
        self.assertEqual(self.install(good)[0], 0)
        other, _ = self.archive("other.zip", version="2.0.0")
        self.pin(good_sha, version="2.0.0")
        code, output = self.install(other)
        self.assertEqual(code, 4, output)
        self.assertIn("failed its checksum", output)
        self.assertEqual(self.installed_version(), "1.0.0", "the previous client must survive")
        self.assert_no_staging_left()

    def test_an_archive_without_the_player_leaves_the_old_client(self):
        good, good_sha = self.archive("good.zip", version="1.0.0")
        self.pin(good_sha, version="1.0.0")
        self.assertEqual(self.install(good)[0], 0)
        hollow, hollow_sha = self.archive("hollow.zip", version="2.0.0", with_player=False)
        self.pin(hollow_sha, version="2.0.0")
        code, output = self.install(hollow)
        self.assertEqual(code, 5, output)
        self.assertEqual(self.installed_version(), "1.0.0")
        self.assert_no_staging_left()

    def test_a_missing_archive_or_pin_is_reported(self):
        archive, sha256 = self.archive("client.zip")
        self.pin(sha256)
        code, output = self.install(os.path.join(self.root, "absent.zip"))
        self.assertEqual(code, 3, output)
        os.remove(os.path.join(self.root, "player_release.json"))
        code, output = self.install(archive)
        self.assertEqual(code, 2, output)
        self.assertFalse(os.path.exists(self.player))


class NoticesTests(unittest.TestCase):
    """The notices describe the Godot client, and match the ones it ships."""

    def test_the_unity_notices_are_gone(self):
        self.assertFalse(os.path.exists(os.path.join(OPT_VR, "END_USER_NOTICE.md")))
        with open(NOTICES, encoding="utf-8") as handle:
            notices = handle.read()
        self.assertIn("Godot 4.7.2-stable", notices)
        self.assertIn("MPL-2.0", notices)

    @unittest.skipUnless(os.path.isfile(os.path.join(INSTALLED_PLAYER, "THIRD_PARTY_NOTICES.md")),
                         "no VR client is installed in player/")
    def test_the_installed_client_ships_the_same_notices(self):
        info = build.read_client_info(INSTALLED_PLAYER) or {}
        pin = build.read_release_pin(PIN) or {}
        if info.get("version") != pin.get("version"):
            self.skipTest("the installed client is not the pinned release")
        with open(NOTICES, "rb") as ours, \
                open(os.path.join(INSTALLED_PLAYER, "THIRD_PARTY_NOTICES.md"), "rb") as shipped:
            self.assertEqual(ours.read().replace(b"\r\n", b"\n"),
                             shipped.read().replace(b"\r\n", b"\n"))


if __name__ == "__main__":
    unittest.main()
