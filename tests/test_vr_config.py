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

"""Tests for the VR Configuration GUI.

The GUI half runs in a subprocess on the offscreen Qt platform. That is not
fussiness: ``test_opt_vr.SettingsTests.test_no_qt_is_imported`` asserts PySide6
never reaches the viewer's process, and importing Config here would break it
for every other test sharing this interpreter.

The settings half needs no Qt and is tested in-process.
"""

import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest

OPT_VR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if OPT_VR not in sys.path:
    sys.path.insert(0, OPT_VR)

import _bootstrap  # noqa: E402


def run_gui_script(body):
    """Execute `body` against a live VRConfigGUI in an offscreen subprocess."""
    script = textwrap.dedent(
        """
        import json, os, sys
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        sys.path.insert(0, {opt_vr!r})
        from PySide6.QtWidgets import QApplication
        app = QApplication([])
        import Config
        window = Config.VRConfigGUI()
        """
    ).format(opt_vr=OPT_VR) + textwrap.dedent(body)
    environment = dict(os.environ)
    environment["QT_QPA_PLATFORM"] = "offscreen"
    result = subprocess.run(
        [sys.executable, "-u", "-c", script],
        capture_output=True, text=True, env=environment, cwd=OPT_VR, timeout=600,
    )
    if result.returncode != 0:
        raise AssertionError(
            f"GUI subprocess failed:\n{result.stdout}\n{result.stderr}"
        )
    return result.stdout


class ConfigWindowTests(unittest.TestCase):
    """The window builds and covers the settings the main GUI covers."""

    @classmethod
    def setUpClass(cls):
        cls.report = json.loads(run_gui_script(
            """
            from desktop.Viewer_State import (
                INPUT_PROFILE_DEFAULTS, VISUAL_PROFILE_DEFAULTS,
                PHYSICS_PROFILE_DEFAULTS, DIRECTORY_PROFILE_DEFAULTS,
            )
            schema = set(INPUT_PROFILE_DEFAULTS) | set(VISUAL_PROFILE_DEFAULTS) \\
                | set(PHYSICS_PROFILE_DEFAULTS) | set(DIRECTORY_PROFILE_DEFAULTS)
            print("@@" + json.dumps({
                "title": window.windowTitle(),
                "tabs": [window.tabs.tabText(i) for i in range(window.tabs.count())],
                "inputs": sorted(window.inputs),
                "schema": sorted(schema),
                "collected": {
                    k: v for k, v in window.collect_data().items()
                    if k in ("LAYOUT_DIMENSIONS", "VR_HOST", "VR_PORT")
                },
                "cache_settings": window._cache_setting_values(),
            }))
            """
        ).split("@@", 1)[1])

    def test_window_builds_with_the_expected_tabs(self):
        self.assertEqual(
            self.report["tabs"],
            ["Inputs && Outputs", "Visual Effects", "Simulation && Physics",
             "VR && Unity", "Directories"],
        )

    def test_every_shared_setting_has_a_control(self):
        """A missing control silently freezes that setting at its default."""
        missing = sorted(set(self.report["schema"]) - set(self.report["inputs"]))
        self.assertEqual(missing, [], f"settings with no widget: {missing}")

    def test_vr_bridge_settings_are_present(self):
        for key in ("VR_HOST", "VR_PORT", "DISTANCE_SCALE", "MAX_RENDER_EDGES",
                    "ENABLE_EDGE_FILTERING", "NEIGHBOR_COLOR", "VR_APP_DIR"):
            self.assertIn(key, self.report["inputs"], key)

    def test_layout_dimensionality_is_not_a_control(self):
        """It follows from which viewer was opened, so it is never offered."""
        self.assertNotIn("LAYOUT_DIMENSIONS", self.report["inputs"])

    def test_collected_data_always_requests_three_dimensions(self):
        self.assertEqual(self.report["collected"]["LAYOUT_DIMENSIONS"], 3)

    def test_cache_identity_includes_dimensionality(self):
        """Without this a 3D cache would collide with the 2D one."""
        self.assertEqual(self.report["cache_settings"]["layout_dimensions"], 3)


class ConfigPersistenceTests(unittest.TestCase):
    """Saving writes into the submodule and nowhere else."""

    def test_settings_round_trip_through_the_submodule_file(self):
        output = run_gui_script(
            """
            window.inputs["VR_PORT"].setValue(5123)
            window.inputs["NODE_SIZE"].setValue(19)
            original = None
            if os.path.exists(Config.SETTINGS_FILE):
                with open(Config.SETTINGS_FILE, encoding="utf-8") as handle:
                    original = handle.read()
            try:
                assert window.save_settings()
                with open(Config.SETTINGS_FILE, encoding="utf-8") as handle:
                    saved = json.load(handle)
            finally:
                if original is not None:
                    with open(Config.SETTINGS_FILE, "w", encoding="utf-8") as handle:
                        handle.write(original)
            print("@@" + json.dumps({
                "path": Config.SETTINGS_FILE,
                "port": saved.get("VR_PORT"),
                "node_size": saved.get("NODE_SIZE"),
                "dimensions": saved.get("LAYOUT_DIMENSIONS"),
                "has_directories": all(
                    key in saved for key in
                    ("CACHE_FILE_DIR", "SAVED_LAYOUT_DIR", "INPUT_FILE_DIR")
                ),
            }))
            """
        )
        report = json.loads(output.split("@@", 1)[1])
        self.assertEqual(report["port"], 5123)
        self.assertEqual(report["node_size"], 19)
        self.assertEqual(report["dimensions"], 3)
        self.assertTrue(report["has_directories"], "directories must be persisted")
        self.assertEqual(
            os.path.dirname(os.path.abspath(report["path"])),
            os.path.abspath(OPT_VR),
            "VR settings must live inside the submodule",
        )

    def test_the_desktop_settings_file_is_never_written(self):
        desktop = os.path.join(_bootstrap.PROJECT_ROOT, "viewer_settings.json")
        before = os.path.getmtime(desktop) if os.path.exists(desktop) else None
        run_gui_script(
            """
            original = None
            if os.path.exists(Config.SETTINGS_FILE):
                with open(Config.SETTINGS_FILE, encoding="utf-8") as handle:
                    original = handle.read()
            try:
                window.save_settings()
            finally:
                if original is not None:
                    with open(Config.SETTINGS_FILE, "w", encoding="utf-8") as handle:
                        handle.write(original)
            print("@@done")
            """
        )
        after = os.path.getmtime(desktop) if os.path.exists(desktop) else None
        self.assertEqual(before, after, "the desktop program's settings were touched")


class VRSettingsSourceTests(unittest.TestCase):
    """The Qt-free settings module reads the submodule's file, not the parent's."""

    def setUp(self):
        self._saved = os.environ.pop("SSN_VIEWER_SETTINGS_PATH", None)

    def tearDown(self):
        if self._saved is not None:
            os.environ["SSN_VIEWER_SETTINGS_PATH"] = self._saved

    def test_default_settings_path_is_in_the_submodule(self):
        import Settings

        path = Settings._settings_path()
        self.assertEqual(
            os.path.dirname(os.path.abspath(path)), os.path.abspath(OPT_VR)
        )
        self.assertTrue(path.endswith("vr_settings.json"), path)

    def test_environment_override_still_wins(self):
        """That override is how the GUI hands a per-launch snapshot over."""
        import Settings

        handle = tempfile.NamedTemporaryFile(
            "w", suffix=".json", delete=False, encoding="utf-8"
        )
        handle.close()
        self.addCleanup(lambda: os.path.exists(handle.name) and os.unlink(handle.name))
        os.environ["SSN_VIEWER_SETTINGS_PATH"] = handle.name
        try:
            self.assertEqual(Settings._settings_path(), handle.name)
        finally:
            os.environ.pop("SSN_VIEWER_SETTINGS_PATH", None)

    def test_relative_directories_resolve_inside_the_submodule(self):
        import Settings

        values = Settings.load_settings()
        for key in ("CACHE_FILE_DIR", "SAVED_LAYOUT_DIR", "INPUT_FILE_DIR",
                    "ANALYSIS_RESULT_DIR", "VR_APP_DIR"):
            with self.subTest(key=key):
                self.assertTrue(
                    str(values[key]).startswith(_bootstrap.OPT_VR_DIR),
                    f"{key} escaped the submodule: {values[key]}",
                )

    def test_layout_dimensions_defaults_to_three(self):
        import Settings

        self.assertEqual(Settings.VR_DEFAULTS["LAYOUT_DIMENSIONS"], 3)


if __name__ == "__main__":
    unittest.main()
