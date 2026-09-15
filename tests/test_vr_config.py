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

``EMAPSSN_Config_VR.py`` is a copy of the main program's Config GUI, rebased onto the
submodule. These tests pin the handful of things that copy had to change -
where settings are stored, which viewer is launched, that layouts are always
three dimensional, and that the Unity bridge settings exist - rather than
re-testing the GUI behaviour the main program already covers.

The window is built in a subprocess on the offscreen platform. That is not
fussiness: ``test_opt_vr.SettingsTests.test_no_qt_is_imported`` asserts PySide6
never reaches the viewer's process, and building the GUI here would break it
for every other test sharing this interpreter. The GUI also lives under
``if __name__ == "__main__"``, so it is loaded with runpy, exactly as the main
repository's own offscreen config test does.
"""

import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest

#: The submodule root; VR_SRC is its module tree, mirroring the main
#: program's project-root/src split.
OPT_VR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VR_SRC = os.path.join(OPT_VR, "src")
if VR_SRC not in sys.path:
    sys.path.insert(0, VR_SRC)

import _bootstrap_vr  # noqa: E402


def run_gui_script(body):
    """Build the GUI in an offscreen subprocess and run `body` against it."""
    script = textwrap.dedent(
        """
        import json, os, runpy, sys
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        sys.path.insert(0, {vr_src!r})
        import _bootstrap_vr  # puts the parent src tree on sys.path
        from unittest import mock
        from utilities import Hardware_Acceleration as _preload  # torch before Qt
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance() or QApplication([])
        with mock.patch.object(QApplication, "exec", return_value=0), \\
             mock.patch.object(sys, "exit", return_value=None):
            namespace = runpy.run_path(
                os.path.join({vr_src!r}, "EMAPSSN_Config_VR.py"), run_name="__main__"
            )
        window = namespace["window"]
        Config = type("Config", (), namespace)
        """
    ).format(vr_src=VR_SRC) + textwrap.dedent(body) + textwrap.dedent(
        """
        window.close()
        """
    )
    environment = dict(os.environ)
    environment["QT_QPA_PLATFORM"] = "offscreen"
    # Start from the GUI's own default settings path. Sibling test modules
    # point SSN_VIEWER_SETTINGS_PATH at a neutral temp file, and inheriting it
    # would make these tests describe that file instead of the submodule's.
    environment.pop("SSN_VIEWER_SETTINGS_PATH", None)
    result = subprocess.run(
        [sys.executable, "-u", "-c", script],
        capture_output=True, text=True, env=environment, cwd=OPT_VR, timeout=900,
    )
    if result.returncode != 0:
        raise AssertionError(
            f"GUI subprocess failed:\n{result.stdout}\n{result.stderr}"
        )
    return result.stdout


def report_from(body):
    return json.loads(run_gui_script(body).split("@@", 1)[1])


class ConfigWindowTests(unittest.TestCase):
    """What the copy changed, and what it must have kept."""

    @classmethod
    def setUpClass(cls):
        cls.report = report_from(
            """
            print("@@" + json.dumps({
                "title": window.windowTitle(),
                "tabs": [window.tabs.tabText(i) for i in range(window.tabs.count())],
                "inputs": sorted(window.inputs),
                "profile_tabs": sorted(window.profile_selectors),
                "cache_settings": window._cache_setting_values(),
                "settings_file": namespace["SETTINGS_FILE"],
                "has_statistics": hasattr(window, "run_statistics"),
                "has_histogram": hasattr(window, "run_histogram"),
                "has_stat_display": hasattr(window, "stat_display"),
            }))
            """
        )

    def test_window_identifies_itself_as_the_vr_configuration(self):
        self.assertEqual(self.report["title"], "EMAP-SSN VR Configuration")

    def test_tabs_match_the_desktop_gui(self):
        """The bridge settings live on Visual Effects, not a tab of their own."""
        self.assertEqual(
            self.report["tabs"],
            ["Inputs && Outputs", "Visual Effects", "Simulation && Physics",
             "Directories"],
        )

    def test_unity_bridge_settings_exist(self):
        for key in ("VR_HOST", "VR_PORT", "DISTANCE_SCALE",
                    "ENABLE_EDGE_FILTERING", "MAX_RENDER_EDGES", "VR_APP_DIR"):
            self.assertIn(key, self.report["inputs"], key)

    def test_settings_the_unity_client_ignores_are_gone(self):
        """A control with no effect is worse than no control."""
        for key in ("TEXT_SIZE", "TEXT_COLOR", "LOW_RESOURCE_MODE"):
            self.assertNotIn(key, self.report["inputs"], key)

    def test_packing_geometry_is_gone(self):
        """3D packs onto concentric shells; Square/Circle never reaches it."""
        self.assertNotIn("PACKING_GEOMETRY", self.report["inputs"])

    def test_node_colour_has_exactly_one_control(self):
        """Settings_VR republishes INITIAL_NODE_COLOR as NEIGHBOR_COLOR and wins,
        so a second control would silently discard the user's choice."""
        self.assertIn("INITIAL_NODE_COLOR", self.report["inputs"])
        self.assertNotIn("NEIGHBOR_COLOR", self.report["inputs"])

    def test_inherited_features_survived_the_copy(self):
        """Statistics, histogram and the report panel come along for free."""
        for flag in ("has_statistics", "has_histogram", "has_stat_display"):
            self.assertTrue(self.report[flag], flag)

    def test_saved_config_profiles_cover_every_tab(self):
        for tab in ("inputs_outputs", "visual_effects", "simulation_physics",
                    "directories"):
            self.assertIn(tab, self.report["profile_tabs"], tab)

    def test_layout_dimensionality_is_not_a_control(self):
        """It follows from which viewer was opened, so it is never offered."""
        self.assertNotIn("LAYOUT_DIMENSIONS", self.report["inputs"])

    def test_cache_identity_is_always_three_dimensional(self):
        """Without this a 3D cache would collide with the desktop 2D one."""
        self.assertEqual(self.report["cache_settings"]["layout_dimensions"], 3)

    def test_settings_file_lives_in_the_submodule(self):
        self.assertEqual(
            os.path.dirname(os.path.abspath(self.report["settings_file"])),
            os.path.abspath(OPT_VR),
        )
        self.assertTrue(
            self.report["settings_file"].endswith("viewer_settings_vr.json"),
            self.report["settings_file"],
        )


class LaunchTargetTests(unittest.TestCase):
    """The copy must launch the VR viewer, not the desktop one."""

    def test_handoff_points_at_the_vr_viewer(self):
        report = report_from(
            """
            from unittest import mock
            captured = {}
            def fake(argv, **kwargs):
                captured["argv"] = [str(a) for a in argv]
                captured["title"] = kwargs.get("title")
                return None
            namespace["_handoff_to_viewer"].__globals__["launch_in_terminal"] = fake
            namespace["_handoff_to_viewer"](
                {opt_vr!r}, {}, settings_path="snap.json", executable="/python"
            )
            print("@@" + json.dumps(captured))
            """.replace("{opt_vr!r}", repr(OPT_VR))
        )
        script = report["argv"][2]
        self.assertTrue(
            os.path.samefile(script, os.path.join(VR_SRC, "EMAPSSN_Viewer_VR.py")),
            f"launched {script}",
        )
        self.assertNotIn("EMAPSSN_Viewer.py", script)
        self.assertEqual(report["title"], "EMAP-SSN VR Viewer")

    def test_generator_still_comes_from_the_parent_checkout(self):
        """opt_vr owns no pipeline; layouts are built by the main program."""
        report = report_from(
            """
            captured = {}
            def fake(argv, **kwargs):
                captured["argv"] = [str(a) for a in argv]
                return None
            namespace["_handoff_to_layout_generator"].__globals__[
                "launch_in_terminal"] = fake
            namespace["_handoff_to_layout_generator"](
                "ignored", "layout.json", {}, executable="/python"
            )
            print("@@" + json.dumps(captured))
            """
        )
        script = report["argv"][2]
        self.assertTrue(
            os.path.samefile(
                script,
                os.path.join(_bootstrap_vr.SRC_DIR, "Layout_Cache_Generator.py"),
            ),
            f"generator resolved to {script}",
        )


class ConfigPersistenceTests(unittest.TestCase):
    """Saving writes into the submodule and nowhere else."""

    def test_settings_round_trip_through_the_submodule_file(self):
        report = report_from(
            """
            settings_file = namespace["SETTINGS_FILE"]
            original = None
            if os.path.exists(settings_file):
                with open(settings_file, encoding="utf-8") as handle:
                    original = handle.read()
            window.inputs["VR_PORT"].setValue(5123)
            try:
                window.save_settings()
                with open(settings_file, encoding="utf-8") as handle:
                    saved = json.load(handle)
            finally:
                if original is not None:
                    with open(settings_file, "w", encoding="utf-8") as handle:
                        handle.write(original)
            print("@@" + json.dumps({
                "port": saved.get("VR_PORT"),
                "has_directories": all(
                    key in saved for key in
                    ("CACHE_FILE_DIR", "SAVED_LAYOUT_DIR", "INPUT_FILE_DIR")
                ),
            }))
            """
        )
        self.assertIn(str(report["port"]), ("5123", "5123.0"))
        self.assertTrue(report["has_directories"], "directories must be persisted")

    def test_the_desktop_settings_file_is_never_written(self):
        desktop = os.path.join(_bootstrap_vr.PROJECT_ROOT, "viewer_settings.json")
        before = os.path.getmtime(desktop) if os.path.exists(desktop) else None
        run_gui_script(
            """
            settings_file = namespace["SETTINGS_FILE"]
            original = None
            if os.path.exists(settings_file):
                with open(settings_file, encoding="utf-8") as handle:
                    original = handle.read()
            try:
                window.save_settings()
            finally:
                if original is not None:
                    with open(settings_file, "w", encoding="utf-8") as handle:
                        handle.write(original)
            print("@@done")
            """
        )
        after = os.path.getmtime(desktop) if os.path.exists(desktop) else None
        self.assertEqual(before, after, "the desktop program's settings were touched")


class VRSettingsSourceTests(unittest.TestCase):
    """The Qt-free settings module the viewer itself reads."""

    def setUp(self):
        self._saved = os.environ.pop("SSN_VIEWER_SETTINGS_PATH", None)

    def tearDown(self):
        if self._saved is not None:
            os.environ["SSN_VIEWER_SETTINGS_PATH"] = self._saved

    def test_default_settings_path_is_in_the_submodule(self):
        import Settings_VR

        path = Settings_VR._settings_path()
        self.assertEqual(
            os.path.dirname(os.path.abspath(path)), os.path.abspath(OPT_VR)
        )
        self.assertTrue(path.endswith("viewer_settings_vr.json"), path)

    def test_environment_override_still_wins(self):
        """That override is how the GUI hands a per-launch snapshot over."""
        import Settings_VR

        handle = tempfile.NamedTemporaryFile(
            "w", suffix=".json", delete=False, encoding="utf-8"
        )
        handle.close()
        self.addCleanup(lambda: os.path.exists(handle.name) and os.unlink(handle.name))
        os.environ["SSN_VIEWER_SETTINGS_PATH"] = handle.name
        try:
            self.assertEqual(Settings_VR._settings_path(), handle.name)
        finally:
            os.environ.pop("SSN_VIEWER_SETTINGS_PATH", None)

    def test_relative_directories_resolve_inside_the_submodule(self):
        import Settings_VR

        values = Settings_VR.load_settings()
        for key in ("CACHE_FILE_DIR", "SAVED_LAYOUT_DIR", "INPUT_FILE_DIR",
                    "ANALYSIS_RESULT_DIR", "VR_APP_DIR"):
            with self.subTest(key=key):
                self.assertTrue(
                    str(values[key]).startswith(_bootstrap_vr.OPT_VR_DIR),
                    f"{key} escaped the submodule: {values[key]}",
                )

    def test_bridge_values_are_coerced_to_their_own_types(self):
        """The GUI writes spin boxes as text; unconverted they break arithmetic."""
        import Settings_VR

        self.assertEqual(Settings_VR._coerce("VR_PORT", "5005"), 5005)
        self.assertIsInstance(Settings_VR._coerce("VR_PORT", "5005"), int)
        self.assertEqual(Settings_VR._coerce("DISTANCE_SCALE", "2.5"), 2.5)
        self.assertIs(Settings_VR._coerce("ENABLE_EDGE_FILTERING", "false"), False)

    def test_layout_dimensions_defaults_to_three(self):
        import Settings_VR

        self.assertEqual(Settings_VR.VR_DEFAULTS["LAYOUT_DIMENSIONS"], 3)


if __name__ == "__main__":
    unittest.main()
