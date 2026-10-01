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
three dimensional, and that the VR client bridge settings exist - rather than
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
import shutil
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
                "icon_path": namespace["application_icon_path"](),
                "icon_loads": not window.windowIcon().pixmap(32, 32).isNull(),
            }))
            """
        )

    def test_window_identifies_itself_as_the_vr_configuration(self):
        self.assertEqual(self.report["title"], "EMAP-SSN VR Configuration")

    def test_window_uses_the_vr_logo(self):
        """opt_vr's own logo, not the desktop Config logo it falls back to."""
        self.assertEqual(
            os.path.normcase(os.path.abspath(self.report["icon_path"])),
            os.path.normcase(os.path.join(VR_SRC, "bin", "logos", "vr_logo.ico")),
        )
        self.assertTrue(self.report["icon_loads"])

    def test_tabs_match_the_desktop_gui(self):
        """The bridge settings live on Visual Effects, not a tab of their own."""
        self.assertEqual(
            self.report["tabs"],
            ["Inputs && Outputs", "Visual Effects", "Simulation && Physics",
             "Directories"],
        )

    def test_client_bridge_settings_exist(self):
        for key in ("VR_HOST", "VR_PORT", "DISTANCE_SCALE",
                    "ENABLE_EDGE_FILTERING", "MAX_RENDER_EDGES", "VR_APP_DIR"):
            self.assertIn(key, self.report["inputs"], key)

    def test_settings_the_client_ignores_are_gone(self):
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
                "ignored", "layout.json", {}, executable="/python", launch_viewer=False
            )
            generator_only = list(captured["argv"])
            namespace["_handoff_to_layout_generator"](
                "ignored", "layout.json", {}, executable="/python", launch_viewer=True
            )
            captured["vr_argv"] = list(captured["argv"])
            captured["argv"] = generator_only
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
        self.assertEqual(report["vr_argv"][2], os.path.join(VR_SRC, "Layout_Launcher_VR.py"))
        self.assertNotIn("--launch-viewer", report["vr_argv"])


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
            "VR_APP_DIR": "player",
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


class ClientEndpointTests(unittest.TestCase):
    """The GUI describes the selected client; Host and Port stay the user's.

    The viewer passes VR Client Host and Port to the client it launches, so the
    fields are never locked to the endpoint the build records: that is only
    where a client started by hand dials. Every case drives the folder and the
    fields explicitly. Reading the live settings file would make these describe
    whichever folder the user last chose rather than the behaviour.
    """

    def client_folder(self, host="127.0.0.1", port=5005):
        """A throwaway client folder whose vr_client.json names host:port."""
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, ignore_errors=True)
        with open(os.path.join(folder, "vr_client.json"), "w", encoding="utf-8") as handle:
            json.dump({"client": "EMAP-SSN-VR Godot client", "version": "0.1.0",
                       "protocol": 1, "host": host, "port": port}, handle)
        return folder

    def note_for(self, build_dir, host="127.0.0.1", port=5005):
        return report_from(
            """
            window.inputs["VR_APP_DIR"].setText({build!r})
            window.inputs["VR_HOST"].setText({host!r})
            window.inputs["VR_PORT"].setValue({port!r})
            print("@@" + json.dumps({{
                "text": window.inputs["VR_APP_DIR"].toolTip(),
                "found": window._bridge_client_found,
                "host": window.inputs["VR_HOST"].text(),
                "port": window.inputs["VR_PORT"].value(),
                "editable": [window.inputs[key].isEnabled() for key in ("VR_HOST", "VR_PORT")],
            }}))
            """.format(build=build_dir, host=host, port=port)
        )

    def test_note_text_is_decided_without_qt(self):
        """The wording is a pure function, so it is worth pinning directly."""
        foreign = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, foreign, ignore_errors=True)
        open(os.path.join(foreign, "EMAP-SSN-VR.exe"), "w").close()
        report = report_from(
            """
            decide = namespace["bridge_note_text"]
            player = os.path.join(str(namespace["PROJECT_ROOT"]), "player")
            print("@@" + json.dumps({{
                "missing": decide(None, "127.0.0.1", 5005),
                "match": decide(("127.0.0.1", 5005), "127.0.0.1", 5005),
                "differs": decide(("127.0.0.1", 5005), "127.0.0.1", 6000),
                "foreign": decide(None, "127.0.0.1", 5005, build_dir={foreign!r}),
                "player": decide(None, "127.0.0.1", 5005, build_dir=player),
            }}))
            """.format(foreign=foreign)
        )
        self.assertIn("install_vr.bat", report["missing"])
        self.assertIn("127.0.0.1:5005", report["match"])
        self.assertNotIn("by hand", report["match"])
        self.assertIn("127.0.0.1:6000", report["differs"], "must name what Save & Run passes")
        self.assertIn("127.0.0.1:5005", report["differs"], "must name the build's own default")
        # A Unity-era build folder: Save & Run starts its .exe and installs nothing.
        self.assertIn("installs nothing", report["foreign"])
        self.assertNotIn("downloads", report["foreign"])
        self.assertIn("downloads the pinned release", report["player"])

    def test_a_client_never_overrides_or_locks_the_fields(self):
        report = self.note_for(self.client_folder(port=5005), port=6000)
        self.assertTrue(report["found"])
        self.assertEqual((report["host"], report["port"]), ("127.0.0.1", 6000))
        self.assertEqual(report["editable"], [True, True])
        self.assertIn("127.0.0.1:6000", report["text"])
        self.assertIn("127.0.0.1:5005", report["text"])

    def test_a_folder_without_a_client_says_how_to_install_one(self):
        report = self.note_for(os.path.join(OPT_VR, "no_such_build"))
        self.assertFalse(report["found"])
        self.assertIn("install_vr.bat", report["text"])
        self.assertEqual(report["editable"], [True, True])

    def test_profiles_keep_their_own_endpoint(self):
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
                    "tip": window.inputs["VR_APP_DIR"].toolTip(),
                }
            with mock.patch.object(namespace["Player_Build_VR"], "read_endpoint", return_value=("localhost", 7777)):
                window._apply_profile_data(tab, profile)
                found = state()
                saved = window._collect_tab_profile_data(tab)
            with mock.patch.object(namespace["Player_Build_VR"], "read_endpoint", return_value=None):
                window._apply_profile_data(tab, profile)
                missing = state()
                window._apply_profile_data(tab, profile, read_only=True)
                read_only = state()
            with mock.patch.object(namespace["Player_Build_VR"], "read_endpoint", side_effect=PermissionError("unreadable build")):
                window._apply_profile_data(tab, profile)
                unreadable = state()
            print("@@" + json.dumps({"found": found, "saved": saved, "missing": missing,
                "read_only": read_only, "unreadable": unreadable}))
            """
        )
        found = report["found"]
        self.assertEqual((found["host"], found["port"]), ("10.0.0.5", 6000))
        self.assertEqual(found["enabled"], [True, True])
        self.assertIn("localhost:7777", found["tip"])
        self.assertEqual(report["saved"]["VR_HOST"], "10.0.0.5")
        self.assertEqual(int(report["saved"]["VR_PORT"]), 6000)
        missing = report["missing"]
        self.assertEqual((missing["host"], missing["port"]), ("10.0.0.5", 6000))
        self.assertIn("install_vr.bat", missing["tip"])
        self.assertEqual(report["read_only"]["enabled"], [False, False])
        self.assertEqual(report["unreadable"], missing)

    def test_each_new_window_rereads_the_client(self):
        report = report_from(
            """
            import tempfile
            from pathlib import Path
            reports = []
            with tempfile.TemporaryDirectory() as folder:
                manifest = Path(folder) / "vr_client.json"
                custom = dict(window._custom_settings)
                custom.update(VR_APP_DIR=folder, VR_HOST="10.0.0.5", VR_PORT=6000)
                for port in (7001, 7002):
                    manifest.write_text(json.dumps({"host": "127.0.0.1", "port": port}), encoding="utf-8")
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
        for item, port in zip(report, (7001, 7002)):
            with self.subTest(port=port):
                self.assertEqual(item["port"], 6000, "the saved port is the user's")
                self.assertTrue(item["enabled"])
                self.assertIn(f"127.0.0.1:{port}", item["tooltip"])

    def test_choosing_a_folder_describes_its_client(self):
        """Picking a folder is the moment the user says which client they mean."""
        folder = self.client_folder(host="127.0.0.1", port=5005)
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
                "found": window._bridge_client_found,
                "tooltip": field.toolTip(),
            }}))
            """.format(build=folder)
        )
        self.assertEqual(report["browse_buttons"], 1)
        self.assertEqual((report["host"], report["port"]), ("10.0.0.5", 6000))
        self.assertTrue(report["found"])
        self.assertIn("127.0.0.1:5005", report["tooltip"])

    def test_a_unity_era_folder_setting_moves_to_the_installed_client(self):
        """Settings saved before the Godot client name the old unity/ folder."""
        report = report_from(
            """
            normalized = window._normalize_profile_data("visual_effects", {"VR_APP_DIR": "unity"})
            custom = window._normalize_profile_data("visual_effects", {"VR_APP_DIR": "E:/elsewhere/unity"})
            print("@@" + json.dumps({"migrated": normalized["VR_APP_DIR"],
                                     "chosen": custom["VR_APP_DIR"],
                                     "default": namespace["VR_PROFILE_DEFAULTS"]["VR_APP_DIR"]}))
            """
        )
        self.assertEqual(report["migrated"], "player")
        self.assertEqual(report["chosen"], "E:/elsewhere/unity", "a chosen folder is left alone")
        self.assertEqual(report["default"], "player")


class QuitWithClientTests(unittest.TestCase):
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
        self.assertEqual(report["label"], "Quit with VR Client:")
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

    def test_launch_snapshot_preserves_client_settings_in_a_fresh_viewer_process(self):
        report = report_from(
            """
            import subprocess
            window.inputs["VR_APP_DIR"].setText("test_custom_client_build")
            window.inputs["VR_HOST"].setText("localhost")
            window.inputs["VR_PORT"].setValue(6123)
            window.inputs["DISTANCE_SCALE"].setValue(2.5)
            window.inputs["ENABLE_EDGE_FILTERING"].setChecked(False)
            window.inputs["MAX_RENDER_EDGES"].setValue(12345)
            reports = []
            for checked in (False, True):
                window.inputs["EXIT_WITH_UNITY"].setChecked(checked)
                path = namespace["_create_viewer_settings_snapshot"](window.collect_data())
                try:
                    script = (
                        "import sys, json; sys.path.insert(0, " + repr(str(namespace["_bootstrap_vr"].VR_SRC_DIR)) + "); "
                        "import EMAPSSN_Viewer_VR as viewer; "
                        "print('@@' + json.dumps({'exit': viewer.should_exit_with_unity(), "
                        "'values': {k: getattr(viewer.cfg, k) for k in " + repr(list(namespace["VR_PROFILE_DEFAULTS"])) + "}}))"
                    )
                    result = subprocess.run(
                        [sys.executable, "-c", script, "--settings", path],
                        capture_output=True, text=True, timeout=120,
                    )
                    assert result.returncode == 0, result.stdout + result.stderr
                    reports.append(json.loads(result.stdout.split("@@", 1)[1]))
                finally:
                    os.unlink(path)
            print("@@" + json.dumps(reports))
            """
        )
        for checked, item in zip((False, True), report):
            with self.subTest(checked=checked):
                self.assertIs(item["exit"], checked)
                self.assertIs(item["values"]["EXIT_WITH_UNITY"], checked)
                self.assertEqual(item["values"]["VR_HOST"], "localhost")
                self.assertEqual(item["values"]["VR_PORT"], 6123)
                self.assertEqual(item["values"]["DISTANCE_SCALE"], 2.5)
                self.assertIs(item["values"]["ENABLE_EDGE_FILTERING"], False)
                self.assertEqual(item["values"]["MAX_RENDER_EDGES"], 12345)
                self.assertEqual(item["values"]["VR_APP_DIR"], os.path.join(OPT_VR, "test_custom_client_build"))

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
