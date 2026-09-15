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
            window.inputs["VR_APP_DIR"].setText("no_such_build")
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
        """A relative directory is the submodule's, never the parent's.

        This drives a settings file of its own rather than whatever the user
        last saved. Pointing the VR front end at an external data store is a
        supported configuration - an absolute path is honoured as written, and
        the next test pins that - so reading the live file made this assert the
        user's setup instead of the resolution rule.
        """
        import Settings_VR

        relative = {
            "CACHE_FILE_DIR": "Cache_Files",
            "SAVED_LAYOUT_DIR": r"$cache_file$\Saved_Layouts",
            "INPUT_FILE_DIR": "Input_Files",
            "ANALYSIS_RESULT_DIR": "Analysis_Results",
            "VR_APP_DIR": "VR_App",
        }
        values = self._settings_from(relative)
        for key in relative:
            with self.subTest(key=key):
                self.assertTrue(
                    str(values[key]).startswith(_bootstrap_vr.OPT_VR_DIR),
                    f"{key} escaped the submodule: {values[key]}",
                )

    def test_absolute_directories_are_left_alone(self):
        """An external data store is a supported choice, not a mistake."""
        import Settings_VR

        external = os.path.join(tempfile.gettempdir(), "SSN_Viewer_Data")
        values = self._settings_from({"INPUT_FILE_DIR": external})
        self.assertEqual(os.path.normpath(values["INPUT_FILE_DIR"]),
                         os.path.normpath(external))

    def _settings_from(self, document):
        """Load settings from a throwaway file holding exactly `document`."""
        import Settings_VR

        handle = tempfile.NamedTemporaryFile(
            "w", suffix=".json", delete=False, encoding="utf-8"
        )
        json.dump(document, handle)
        handle.close()
        self.addCleanup(lambda: os.path.exists(handle.name) and os.unlink(handle.name))
        os.environ["SSN_VIEWER_SETTINGS_PATH"] = handle.name
        try:
            return Settings_VR.load_settings()
        finally:
            os.environ.pop("SSN_VIEWER_SETTINGS_PATH", None)

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


class UnityEndpointTests(unittest.TestCase):
    """The GUI reads the endpoint out of the build instead of asking for it.

    Every case drives the build path and the fields explicitly. Reading the
    live settings file would make these describe whichever build the user last
    selected rather than the behaviour.
    """

    SHIPPED_BUILD = os.path.join(OPT_VR, "VR_App")

    def note_for(self, build_dir, host="127.0.0.1", port=5005):
        return report_from(
            """
            window.inputs["VR_APP_DIR"].setText({build!r})
            window.inputs["VR_HOST"].setText({host!r})
            window.inputs["VR_PORT"].setValue({port!r})
            print("@@" + json.dumps({{
                "text": window.inputs["VR_APP_DIR"].toolTip(),
                "warning": window._bridge_endpoint_warning,
                "host": window.inputs["VR_HOST"].text(),
                "port": window.inputs["VR_PORT"].value(),
                "editable": [window.inputs[key].isEnabled() for key in ("VR_HOST", "VR_PORT")],
            }}))
            """.format(build=build_dir, host=host, port=port)
        )

    def test_note_text_is_decided_without_qt(self):
        """The wording is a pure function, so it is worth pinning directly."""
        report = report_from(
            """
            decide = namespace["bridge_note_text"]
            print("@@" + json.dumps({
                "unknown": decide(None, "127.0.0.1", 5005),
                "match": decide(("127.0.0.1", 5005), "127.0.0.1", 5005),
                "host_differs": decide(("127.0.0.1", 5005), "10.0.0.5", 5005),
                "port_differs": decide(("127.0.0.1", 5005), "127.0.0.1", 6000),
            }))
            """
        )
        self.assertFalse(report["unknown"][1], "an unreadable build is not an error")
        self.assertFalse(report["match"][1])
        for key in ("host_differs", "port_differs"):
            with self.subTest(case=key):
                text, warning = report[key]
                self.assertTrue(warning)
                self.assertIn("127.0.0.1:5005", text, "must name what the build dials")
                self.assertIn("never connect", text)

    @unittest.skipUnless(
        os.path.isdir(os.path.join(OPT_VR, "VR_App")), "VR_App is not checked out"
    )
    def test_agreement_with_the_shipped_build_is_reported(self):
        report = self.note_for(self.SHIPPED_BUILD)
        self.assertIn("127.0.0.1:5005", report["text"])
        self.assertFalse(report["warning"])

    @unittest.skipUnless(
        os.path.isdir(os.path.join(OPT_VR, "VR_App")), "VR_App is not checked out"
    )
    def test_a_mismatch_is_corrected_and_locked(self):
        report = self.note_for(self.SHIPPED_BUILD, port=6000)
        self.assertFalse(report["warning"])
        self.assertIn("127.0.0.1:5005", report["text"])
        self.assertIn("Parsing succeeded", report["text"])
        self.assertEqual((report["host"], report["port"]), ("127.0.0.1", 5005))
        self.assertEqual(report["editable"], [False, False])

    def test_an_unreadable_build_falls_back_to_the_typed_values(self):
        report = self.note_for(os.path.join(OPT_VR, "no_such_build"))
        self.assertFalse(report["warning"], "an unreadable build is not a mismatch")
        self.assertIn("matched by hand", report["text"])
        self.assertIn("Parsing failed", report["text"])
        self.assertEqual(report["editable"], [True, True])

    def test_profile_changes_switch_between_parsed_and_manual_endpoints(self):
        report = report_from(
            """
            tab = "visual_effects"
            profile = dict(namespace["VR_VISUAL_PROFILE_DEFAULTS"])
            profile.update(VR_APP_DIR="test_build", VR_HOST="10.0.0.5", VR_PORT=6000)
            def state():
                return {
                    "host": window.inputs["VR_HOST"].text(),
                    "port": window.inputs["VR_PORT"].value(),
                    "enabled": [window.inputs[k].isEnabled() for k in ("VR_HOST", "VR_PORT")],
                    "label_enabled": [window.labels[k].isEnabled() for k in ("VR_HOST", "VR_PORT")],
                }
            with mock.patch.object(namespace["Unity_Build_VR"], "read_endpoint", return_value=("localhost", 7777)):
                window._apply_profile_data(tab, profile)
                parsed = state()
                saved = window._collect_tab_profile_data(tab)
                window._apply_profile_data(tab, profile, read_only=True)
                window._apply_profile_data(tab, profile)
                after_default = state()
            with mock.patch.object(namespace["Unity_Build_VR"], "read_endpoint", return_value=None):
                window._apply_profile_data(tab, profile)
                manual = state()
                window._apply_profile_data(tab, profile, read_only=True)
                read_only = state()
            with mock.patch.object(namespace["Unity_Build_VR"], "read_endpoint", side_effect=PermissionError("unreadable build")):
                window._apply_profile_data(tab, profile)
                unreadable = state()
            print("@@" + json.dumps({"parsed": parsed, "saved": saved,
                "after_default": after_default, "manual": manual,
                "read_only": read_only, "unreadable": unreadable}))
            """
        )
        parsed = report["parsed"]
        self.assertEqual((parsed["host"], parsed["port"]), ("localhost", 7777))
        self.assertEqual(parsed["enabled"], [False, False])
        self.assertEqual(parsed["label_enabled"], [False, False])
        self.assertEqual(report["after_default"], parsed)
        self.assertEqual(report["saved"]["VR_HOST"], "localhost")
        self.assertEqual(int(report["saved"]["VR_PORT"]), 7777)
        self.assertEqual(report["manual"]["enabled"], [True, True])
        self.assertEqual((report["manual"]["host"], report["manual"]["port"]), ("10.0.0.5", 6000))
        self.assertEqual(report["read_only"]["enabled"], [False, False])
        self.assertEqual(report["unreadable"], report["manual"])

    def test_each_new_window_rereads_the_build_before_using_saved_values(self):
        report = report_from(
            """
            import tempfile, struct
            from pathlib import Path
            reports = []
            with tempfile.TemporaryDirectory() as folder:
                scene = Path(folder) / "Player_Data" / "level0"
                scene.parent.mkdir()
                custom = dict(window._custom_settings)
                custom.update(VR_APP_DIR=folder, VR_HOST="10.0.0.5", VR_PORT=6000)
                for port in (7001, 7002):
                    host = b"127.0.0.1"
                    scene.write_bytes(struct.pack("<i", len(host)) + host + b"\\x00" * (-len(host) % 4) + struct.pack("<i", port))
                    with mock.patch.object(type(window), "_read_custom_settings", return_value=custom):
                        fresh = type(window)()
                    try:
                        reports.append({"port": fresh.inputs["VR_PORT"].value(),
                            "enabled": fresh.inputs["VR_PORT"].isEnabled(),
                            "tooltip": fresh.inputs["VR_APP_DIR"].toolTip()})
                    finally:
                        fresh.close()
            print("@@" + json.dumps(reports))
            """
        )
        self.assertEqual([item["port"] for item in report], [7001, 7002])
        for item in report:
            self.assertFalse(item["enabled"])
            self.assertIn("Parsing succeeded", item["tooltip"])

    @unittest.skipUnless(
        os.path.isdir(os.path.join(OPT_VR, "VR_App")), "VR_App is not checked out"
    )
    def test_choosing_a_build_fills_the_endpoint_in(self):
        """Picking a build is the moment the user says which client they mean."""
        report = report_from(
            """
            from PySide6.QtWidgets import QFileDialog, QPushButton
            window.inputs["VR_HOST"].setText("10.0.0.5")
            window.inputs["VR_PORT"].setValue(6000)
            field = window.inputs["VR_APP_DIR"]
            browse = [b for b in field.parentWidget().findChildren(QPushButton)
                      if b.text() == "Browse"]
            with mock.patch.object(
                QFileDialog, "getExistingDirectory", return_value={build!r}
            ):
                browse[0].click()
            print("@@" + json.dumps({{
                "browse_buttons": len(browse),
                "host": window.inputs["VR_HOST"].text(),
                "port": window.inputs["VR_PORT"].value(),
                "warning": window._bridge_endpoint_warning,
            }}))
            """.format(build=os.path.join(OPT_VR, "VR_App"))
        )
        self.assertEqual(report["browse_buttons"], 1)
        self.assertEqual(report["host"], "127.0.0.1")
        self.assertEqual(report["port"], 5005)
        self.assertFalse(report["warning"])


class QuitWithUnityTests(unittest.TestCase):
    """The VR-only control for whether the viewer outlives the headset app."""

    def test_it_is_a_switch_with_its_own_label(self):
        report = report_from(
            """
            from PySide6.QtWidgets import QPushButton
            widget = window.inputs["EXIT_WITH_UNITY"]
            print("@@" + json.dumps({
                "is_button": isinstance(widget, QPushButton),
                "checkable": widget.isCheckable(),
                "label": window.labels["EXIT_WITH_UNITY"].text(),
                "declared_default": namespace["VR_PROFILE_DEFAULTS"]["EXIT_WITH_UNITY"],
            }))
            """
        )
        self.assertTrue(report["is_button"], "asked for a button, not a checkbox")
        self.assertTrue(report["checkable"])
        self.assertEqual(report["label"], "Quit with Unity:")
        self.assertIs(report["declared_default"], True, "killing is the default")

    def test_both_positions_round_trip(self):
        report = report_from(
            """
            widget = window.inputs["EXIT_WITH_UNITY"]
            readings = {}
            for state in (False, True):
                widget.setChecked(state)
                readings[str(state)] = {
                    "value": window._widget_profile_value("EXIT_WITH_UNITY"),
                    "text": widget.text(),
                }
            print("@@" + json.dumps(readings))
            """
        )
        self.assertIs(report["False"]["value"], False)
        self.assertIs(report["True"]["value"], True)
        # The pill has to say which way it is pointing.
        self.assertEqual(report["False"]["text"], "OFF")
        self.assertEqual(report["True"]["text"], "ON")

    def test_it_belongs_to_the_visual_effects_profile(self):
        """Otherwise a saved profile would silently drop it."""
        report = report_from(
            """
            print("@@" + json.dumps({
                "in_profile": "EXIT_WITH_UNITY" in namespace[
                    "VR_VISUAL_PROFILE_DEFAULTS"
                ],
            }))
            """
        )
        self.assertTrue(report["in_profile"])


if __name__ == "__main__":
    unittest.main()
