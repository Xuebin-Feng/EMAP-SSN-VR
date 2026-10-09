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

Every script runs the GUI in a throwaway project instead of this checkout,
whose settings files belong to whoever runs the suite, and an audit hook fails
the script if anything still reads or writes those files.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from unittest import mock

#: The submodule root; VR_SRC is its module tree, mirroring the main
#: program's project-root/src split.
OPT_VR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VR_SRC = os.path.join(OPT_VR, "src")
if VR_SRC not in sys.path:
    sys.path.insert(0, VR_SRC)

import _bootstrap_vr  # noqa: E402

#: This checkout's own settings files, which belong to whoever runs the suite.
#: No GUI script may read or write them.
USER_SETTINGS_FILES = (
    os.path.join(OPT_VR, "viewer_settings_vr.json"),
    os.path.join(_bootstrap_vr.PROJECT_ROOT, "viewer_settings.json"),
    os.path.join(_bootstrap_vr.PROJECT_ROOT, "app_settings.json"),
)

#: Installed before anything else in a GUI script. An audit hook sees every
#: open, rename and delete the process makes, whichever module worked out the
#: path, and raising from it stops the call before the file is touched.
SETTINGS_GUARD = textwrap.dedent(
    """
    import os, sys
    _refused = []

    def _guard(event, args):
        if event in ("open", "os.remove", "os.truncate"):
            paths = args[:1]
        elif event == "os.rename":  # os.replace raises this one too
            paths = args[:2]
        else:
            return
        for path in paths:
            if isinstance(path, int):  # a descriptor, checked when it was opened
                continue
            path = os.fsdecode(path)
            if os.path.normcase(os.path.abspath(path)) in _USER_FILES:
                _refused.append(f"{event} {path}")
                print(f"Refused {event} of {path}", file=sys.stderr)
                raise PermissionError(f"GUI tests may not touch {path}")

    sys.addaudithook(_guard)
    """
)


def run_gui_script(body, project_root=None, pseudo_translation=False):
    """Build the GUI in an offscreen subprocess and run `body` against it.

    The GUI never sees this checkout's settings. It runs as if opt_vr sat at
    `<project_root>/opt_vr`, so its settings file and every relative
    directory resolve there: a throwaway folder, unless a test passes its own
    to inspect afterwards. `body` runs under SETTINGS_GUARD, and the run fails
    if anything still tried to read or write the real settings files. The
    GUI starts in English unless pseudo_translation asks for the test-only
    pseudo-language, whatever the shell running the tests has set.
    """
    if project_root is None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as throwaway:
            return run_gui_script(body, throwaway, pseudo_translation)
    working_directory = os.path.join(project_root, "opt_vr")
    os.makedirs(working_directory, exist_ok=True)
    guard = f"_USER_FILES = {set(map(os.path.normcase, USER_SETTINGS_FILES))!r}\n"
    script = guard + SETTINGS_GUARD + textwrap.dedent(
        """
        import json, os, runpy, sys
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        sys.path.insert(0, {vr_src!r})
        import _bootstrap_vr  # puts the parent src tree on sys.path
        # The GUI derives its own paths from these two when it is loaded.
        _bootstrap_vr.PROJECT_ROOT = {project_root!r}
        _bootstrap_vr.OPT_VR_DIR = {opt_vr!r}
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
    ).format(
        vr_src=VR_SRC, project_root=project_root, opt_vr=working_directory
    ) + textwrap.dedent(body) + textwrap.dedent(
        """
        window.close()
        if _refused:
            raise SystemExit("Touched the user's settings: " + "; ".join(_refused))
        """
    )
    environment = dict(os.environ)
    environment["QT_QPA_PLATFORM"] = "offscreen"
    # Start from the GUI's own default settings path. Sibling test modules
    # point SSN_VIEWER_SETTINGS_PATH at a neutral temp file, and inheriting it
    # would make these tests describe that file instead of the submodule's.
    environment.pop("SSN_VIEWER_SETTINGS_PATH", None)
    environment.pop("SSN_PSEUDO_TRANSLATION", None)
    if pseudo_translation:
        environment["SSN_PSEUDO_TRANSLATION"] = "1"
    # The language setting, too, comes from the throwaway project.
    environment["SSN_APP_SETTINGS_PATH"] = os.path.join(project_root, "app_settings.json")
    result = subprocess.run(
        [sys.executable, "-u", "-c", script],
        capture_output=True, text=True, env=environment, cwd=working_directory,
        timeout=900,
    )
    if result.returncode != 0:
        raise AssertionError(
            f"GUI subprocess failed:\n{result.stdout}\n{result.stderr}"
        )
    return result.stdout


def report_from(body, **options):
    return json.loads(run_gui_script(body, **options).split("@@", 1)[1])


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
                "submodule": _bootstrap_vr.OPT_VR_DIR,
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
        # The submodule the GUI was given: the throwaway project's opt_vr.
        self.assertEqual(
            os.path.dirname(os.path.abspath(self.report["settings_file"])),
            os.path.abspath(self.report["submodule"]),
        )
        self.assertTrue(
            self.report["settings_file"].endswith("viewer_settings_vr.json"),
            self.report["settings_file"],
        )


class AutoStepSizeTests(unittest.TestCase):
    """The Auto button beside Step Size behaves as in the desktop Config."""

    def test_auto_button_greys_out_the_step_size_field(self):
        report = report_from(
            """
            window.profile_selectors["simulation_physics"].setCurrentText("(new)")
            button, field = window.inputs["AUTO_DT"], window.inputs["DT"]
            cell = button.parentWidget()

            def minimum_width(widget):
                return widget.minimumSizeHint().expandedTo(widget.minimumSize()).width()

            states = {}
            for checked in (False, True):
                button.setChecked(checked)
                app.processEvents()
                states[str(checked)] = {
                    "text": button.text(),
                    "field_enabled": field.isEnabled(),
                    "collected": window.collect_data()["AUTO_DT"],
                }
            button.setChecked(False)
            print("@@" + json.dumps({
                "button_starts_the_cell": cell.layout().itemAt(0).widget() is button,
                "field_follows": cell.layout().itemAt(1).widget() is field,
                "cell_is_as_narrow_as_a_field": minimum_width(cell)
                    == minimum_width(window.inputs["MAX_STEPS"]),
                "gap_matches_label_spacing": cell.layout().spacing()
                    == namespace["CONFIG_FIELD_HORIZONTAL_SPACING"],
                "in_physics_profile": "AUTO_DT"
                    in namespace["TAB_PROFILE_SPECS"]["simulation_physics"]["defaults"],
                "states": states,
            }))
            """
        )
        for key in ("button_starts_the_cell", "field_follows",
                    "cell_is_as_narrow_as_a_field", "gap_matches_label_spacing",
                    "in_physics_profile"):
            self.assertTrue(report[key], key)
        self.assertEqual(
            report["states"]["False"],
            {"text": "Auto OFF", "field_enabled": True, "collected": False},
        )
        self.assertEqual(
            report["states"]["True"],
            {"text": "Auto ON", "field_enabled": False, "collected": True},
        )


class AlignmentOffsetTests(unittest.TestCase):
    """Alignment Offset spans the row once the fields stack, as in the desktop Config."""

    def test_offset_spans_stacked_rows_and_keeps_its_wide_width(self):
        report = report_from(
            """
            from PySide6.QtCore import QPoint
            window.show()

            def flush():
                for _ in range(4):
                    app.processEvents()

            def resize_panel(width):
                window.resize(width + 360, 850)
                window.main_split.setSizes([width + 4, 326])
                flush()
                delta = width - window.tabs.currentWidget().width()
                left, right = window.main_split.sizes()
                window.main_split.setSizes([left + delta, right - delta])
                flush()

            window.tabs.setCurrentIndex(0)
            page = window.tabs.currentWidget().widget()
            offset, label = window.spin_alignment_offset, window.lbl_alignment_offset

            def right(widget):
                return widget.mapTo(page, QPoint(widget.width(), 0)).x()

            rows = []
            for width in (1400, 600, 800, 1400):
                resize_panel(width)
                rows.append({
                    "width": width,
                    "stacked": bool(offset.parentWidget().property("stacked")),
                    "label_fits": label.width() >= label.sizeHint().width(),
                    "offset_width": offset.width(),
                    "rights": [right(offset), right(window.line_ref),
                               right(window.spin_min_occ)],
                })
            print("@@" + json.dumps(rows))
            """
        )
        for row in report:
            with self.subTest(width=row["width"]):
                stacked = row["width"] < 1400
                self.assertEqual(row["stacked"], stacked)
                self.assertTrue(row["label_fits"])
                if stacked:
                    self.assertEqual(len(set(row["rights"])), 1, row["rights"])
                else:
                    self.assertEqual(row["offset_width"], 100)


class DropdownValueTests(unittest.TestCase):
    """Options are read and selected by stored value, as in the desktop Config.

    Every option gets a label that differs from its value first, so code that
    still reads or matches the displayed text fails here.
    """

    @classmethod
    def setUpClass(cls):
        cls.report = report_from(
            """
            select = namespace["select_combo_value"]

            def relabel(combo):
                for index in range(combo.count()):
                    combo.setItemText(index, "[" + combo.itemText(index)[::-1] + "]")

            relabel(window.cb_score_mode)
            select(window.cb_score_mode, "local")
            relabel(window.cb_norm_mode)
            norm_values = [
                window.cb_norm_mode.itemData(index)
                for index in range(window.cb_norm_mode.count())
            ]
            select(window.cb_norm_mode, "average_sequence")
            data = window.collect_data()

            cache = window.cb_cache_file
            cache.blockSignals(True)
            cache.clear()
            cache.addItem("version_00.h5", "folder/version_00.h5")
            cache.addItem("(New Layout Cache)", None)
            cache.blockSignals(False)
            relabel(cache)
            cache.setCurrentIndex(1)
            new_cache = window._new_cache_selected()

            selector = window.profile_selectors["visual_effects"]
            relabel(selector)
            with mock.patch.object(namespace["QMessageBox"], "critical") as critical:
                select(selector, "(default)")
            print("@@" + json.dumps({
                "score": data["ALIGNMENT_SCORE"],
                "norm": data["NORM_MODE"],
                "norm_values": norm_values,
                "new_cache": new_cache,
                "profile_selection": window._profile_previous_selection["visual_effects"],
                "profile_error": critical.called,
            }))
            """
        )

    def test_relabelled_modes_save_their_values(self):
        self.assertEqual(self.report["score"], "local")
        self.assertEqual(self.report["norm"], "average_sequence")
        self.assertNotIn("alignment_length", self.report["norm_values"])

    def test_new_layout_cache_entry_is_found_without_its_label(self):
        self.assertTrue(self.report["new_cache"])

    def test_saved_config_entries_are_found_without_their_labels(self):
        self.assertEqual(self.report["profile_selection"], "(default)")
        self.assertFalse(self.report["profile_error"])


class TextSizedControlsTests(unittest.TestCase):
    """Labels share one column sized by the longest, and switches fit their text,
    as in the desktop Config. The VR client block joins both."""

    @classmethod
    def setUpClass(cls):
        cls.report = report_from(
            """
            from PySide6.QtCore import QPoint
            from PySide6.QtGui import QFont, QFontMetrics
            from desktop.Desktop_App import BUTTON_TEXT_PADDING, ToggleSwitch
            window.show()

            def flush():
                for _ in range(4):
                    app.processEvents()

            flush()
            window.tabs.setCurrentIndex(1)  # Visual Effects holds the client block
            flush()
            page = window.tabs.currentWidget().widget()

            def x(widget):
                return widget.mapTo(page, QPoint()).x()

            switches = []
            for button in window.findChildren(namespace["QPushButton"]):
                if not button.isCheckable():
                    continue
                bold = QFont(button.font())
                bold.setBold(True)
                sizes, texts = set(), []
                for _ in range(2):
                    button.toggle()
                    flush()
                    sizes.add((button.width(), button.height()))
                    texts.append(button.text())
                needed = max(QFontMetrics(bold).horizontalAdvance(text) for text in texts)
                switches.append({
                    "texts": texts,
                    "toggle_switch": isinstance(button, ToggleSwitch),
                    "sizes": sorted(sizes),
                    "needed": needed + 2 * BUTTON_TEXT_PADDING,
                })
            client_keys = ("VR_APP_DIR", "ENABLE_EDGE_FILTERING")
            print("@@" + json.dumps({
                "column": window.label_column_width,
                "column_labels": [window.labels[key].width() for key in client_keys],
                "client_fields": [x(window.inputs[key]) for key in client_keys],
                "visual_field": x(window.inputs["NODE_SIZE"].parentWidget()),
                "switches": switches,
            }))
            """
        )

    def test_client_block_labels_join_the_label_column(self):
        report = self.report
        self.assertEqual(report["column_labels"], [report["column"]] * 2)
        self.assertEqual(report["client_fields"], [report["visual_field"]] * 2)

    def test_every_switch_fits_both_texts_and_keeps_its_size(self):
        switches = self.report["switches"]
        self.assertEqual(len(switches), 5)
        for switch in switches:
            with self.subTest(texts=switch["texts"]):
                self.assertTrue(switch["toggle_switch"])
                self.assertEqual(switch["sizes"], [[switch["needed"], 28]])


class TranslationTests(unittest.TestCase):
    """The window loads translations as it starts, as the desktop Config does.

    Under the test-only pseudo-language, text from the catalogs shows
    bracketed, so unbracketed text was never marked for translation. The
    texts VR Config shares with the desktop Config come from the main
    catalog, and its own from opt_vr's, emapssn_vr. The main repository's
    tests/translation_fixtures.py lists a window's text the same way for
    both Configs.
    """

    @classmethod
    def setUpClass(cls):
        cls.report = report_from(
            """
            import importlib.util
            from desktop.Desktop_App import installed_language
            from utilities.Localization import is_pseudo_translated
            fixtures_path = os.path.join(
                os.path.dirname(_bootstrap_vr.SRC_DIR), "tests", "translation_fixtures.py"
            )
            spec = importlib.util.spec_from_file_location("translation_fixtures", fixtures_path)
            fixtures = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(fixtures)
            window.resize(1800, 1000)
            window.show()
            for _ in range(4):
                app.processEvents()
            texts = fixtures.visible_texts(window)
            print("@@" + json.dumps({
                "language": installed_language(),
                "texts": len(texts),
                "unmarked": [[where, text] for where, text in texts if not is_pseudo_translated(text)],
                "cut_off": fixtures.cut_off_texts(window),
            }))
            """,
            pseudo_translation=True,
        )

    def test_startup_installs_the_language_before_building_the_window(self):
        import ast

        self.assertEqual(self.report["language"], "pseudo")
        path = os.path.join(VR_SRC, "EMAPSSN_Config_VR.py")
        with open(path, encoding="utf-8") as handle:
            tree = ast.parse(handle.read())

        def first_call(name):
            return min(
                node.lineno for node in ast.walk(tree) if isinstance(node, ast.Call)
                and name in (getattr(node.func, "id", None), getattr(node.func, "attr", None))
            )

        install = first_call("install_translations")
        self.assertLess(first_call("QApplication"), install)
        for later in ("SingleInstanceController", "configure_qt_application_fonts", "ConfigGUI"):
            self.assertGreater(first_call(later), install, later)

    def test_every_text_is_marked_and_none_is_cut_off(self):
        self.assertGreater(self.report["texts"], 150)
        self.assertEqual(self.report["unmarked"], [])
        self.assertEqual(self.report["cut_off"], [])


class LanguageOptionTests(unittest.TestCase):
    """The Language dropdown, and the redraw in another language, as in the desktop Config."""

    @classmethod
    def setUpClass(cls):
        cls.report = report_from(
            """
            from PySide6.QtWidgets import QSplitter, QTabWidget
            from desktop.Desktop_App import LanguageSelector, installed_language
            window.show()
            for _ in range(4):
                app.processEvents()
            window.resize(1300, 800)
            window.move(40, 60)
            window.tabs.setCurrentIndex(1)
            window.inputs["NODE_SIZE"].setValue(window.inputs["NODE_SIZE"].value() + 1)
            for _ in range(4):
                app.processEvents()

            def view(shown):
                return {
                    "geometry": shown.geometry().getRect(),
                    "splitters": [splitter.sizes() for splitter in shown.findChildren(QSplitter)],
                    "tabs": [tabs.currentIndex() for tabs in shown.findChildren(QTabWidget)],
                }

            before = view(window)
            values = window.language_carry_over()["values"]
            selectors = window.findChildren(LanguageSelector)
            replacement = window.switch_language("pseudo")
            for _ in range(4):
                app.processEvents()
            print("@@" + json.dumps({
                "selectors": len(selectors),
                "items": [selectors[0].itemData(i) for i in range(selectors[0].count())],
                "language": installed_language(),
                "replaced": replacement is not window and not window.isVisible(),
                "before": before,
                "after": view(replacement),
                "values_kept": replacement.language_carry_over()["values"] == values,
                "first_item": replacement.language_selector.itemText(0),
                "title": replacement.windowTitle(),
            }, default=str))
            window = replacement
            """
        )

    def test_the_window_has_one_language_dropdown(self):
        self.assertEqual(self.report["selectors"], 1)
        self.assertEqual(self.report["items"][:2], ["system", "en"])

    def test_a_redraw_keeps_size_place_splitters_tab_and_values(self):
        report = self.report
        self.assertEqual(report["language"], "pseudo")
        self.assertTrue(report["replaced"])
        self.assertEqual(report["after"], report["before"])
        self.assertTrue(report["values_kept"])
        self.assertTrue(report["first_item"].startswith("["), report["first_item"])
        # The title is VR Config's own text: the redraw installs opt_vr's catalog too.
        self.assertTrue(report["title"].startswith("["), report["title"])


class RunTimeTextTests(unittest.TestCase):
    """Text the window shows after it opens, under the pseudo-language, as for the desktop Config.

    Tips, VR's own tooltips and client notes, the save message, profile
    errors, the two reports and the score histogram. outside_the_catalog
    (the main repository's tests/translation_fixtures.py) gives what is left
    once every bracketed, translated piece is taken out: text from no catalog.
    """

    @classmethod
    def setUpClass(cls):
        foreign = tempfile.mkdtemp()
        cls.addClassCleanup(shutil.rmtree, foreign, ignore_errors=True)
        open(os.path.join(foreign, "EMAP-SSN-VR.exe"), "w").close()
        cls.report = report_from(
            """
            import importlib.util, tempfile
            from types import SimpleNamespace
            from unittest import mock
            import h5py, numpy
            from PySide6.QtGui import QTextDocumentFragment
            from utilities.Localization import display_text, is_pseudo_translated
            fixtures_path = os.path.join(
                os.path.dirname(_bootstrap_vr.SRC_DIR), "tests", "translation_fixtures.py"
            )
            spec = importlib.util.spec_from_file_location("translation_fixtures", fixtures_path)
            fixtures = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(fixtures)
            checked, left = [], {{}}

            def check(name, text):
                checked.append(name)
                if not text or fixtures.outside_the_catalog(text):
                    left[name] = text

            def plain(html):
                return QTextDocumentFragment.fromHtml(html).toPlainText()

            for key, tip in window.tip_db_keys.items():
                checked.append("tip " + key)
                if not is_pseudo_translated(tip):
                    left["tip " + key] = tip
            for key in ("VR_APP_DIR", "VR_HOST", "VR_PORT", "ENABLE_EDGE_FILTERING",
                        "MAX_RENDER_EDGES", "DISTANCE_SCALE", "EXIT_WITH_UNITY"):
                check("tooltip " + key, window.inputs[key].toolTip())
            decide = namespace["bridge_note_text"]
            for name, note in (
                ("missing", decide(None, "127.0.0.1", 5005)),
                ("match", decide(("127.0.0.1", 5005), "127.0.0.1", 5005)),
                ("differs", decide(("127.0.0.1", 5005), "127.0.0.1", 6000)),
                ("foreign", decide(None, "127.0.0.1", 5005, build_dir={foreign!r})),
            ):
                check("note " + name, display_text(note))
            check("save", window._save_success_message(
                [("visual_effects", "mine"), ("directories", "shared")], ["simulation_physics"]
            ))
            validate = namespace["_validate_profile_name"]
            for name, existing in (("", ()), ("(new)", ()), ("name.", ()), ("a/b", ()), ("con", ()),
                                   ("taken", ("taken",))):
                try:
                    validate(name, existing)
                    left["no profile name error " + repr(name)] = ""
                except ValueError as error:
                    check("profile name " + repr(name), display_text(error))
            for tab_id, data in (("visual_effects", []), ("visual_effects", {{"BOGUS": 1}}),
                                 ("visual_effects", {{"NODE_SIZE": 10.5}}),
                                 ("visual_effects", {{"NODE_SIZE": 1e999}}),
                                 ("visual_effects", {{"EDGE_COLOR": "nocolor"}}),
                                 ("inputs_outputs", {{"ALIGNMENT_SCORE": "local",
                                                      "NORM_MODE": "alignment_length"}})):
                try:
                    window._normalize_profile_data(tab_id, data)
                    left["no profile data error " + repr(data)] = ""
                except ValueError as error:
                    check("profile data " + repr(data), display_text(error))

            folder = tempfile.mkdtemp()
            with open(os.path.join(folder, "subset.fasta"), "w", encoding="utf-8") as handle:
                handle.write(">WP_1_alpha\\nMKTA\\n>WP_2_beta\\nMSEQ\\n>Other\\nMAAA\\n")
            with open(os.path.join(folder, "alignment.fasta"), "w", encoding="utf-8") as handle:
                handle.write(">WP_1_alpha\\nMKTA\\n")

            def write_network(headers):
                with h5py.File(os.path.join(folder, "network.h5"), "w") as hf:
                    hf.create_dataset("headers", data=[header.encode() for header in headers])
                    hf.create_dataset("score", data=numpy.asarray([4.0], dtype=numpy.float32))
                    hf.create_dataset("i", data=numpy.asarray([0], dtype=numpy.int64))
                    hf.create_dataset("j", data=numpy.asarray([1], dtype=numpy.int64))

            for key in ("FASTA_DIR", "HDF5_DIR", "MSA_DIR"):
                window.inputs[key].blockSignals(True)
                window.inputs[key].setText(folder)
                window.inputs[key].blockSignals(False)
            for combo, name in ((window.cb_fasta, "subset.fasta"), (window.cb_hdf5, "network.h5"),
                                (window.cb_msa, "alignment.fasta")):
                combo.blockSignals(True)
                combo.clear()
                combo.addItem(name)
                combo.blockSignals(False)
            write_network(["WP_1_alpha", "WP_2_beta"])
            window.line_ref.setText("WP_*")
            window.run_consistency_check()
            check("consistency report", plain(window.tip_panel.text()))
            write_network(["WP_1_alpha", "WP_2_beta", "Other"])
            blast = SimpleNamespace(network_type="blast", model_name="BLAST")
            cache_manifest = window.run_statistics.__globals__["cache_manifest"]
            with mock.patch.object(cache_manifest, "validate_network_schema", return_value=blast):
                window.run_statistics()
            check("statistics report", window.stat_display.toPlainText())
            check("statistics tip", plain(window.tip_panel.text()))
            figure = namespace["build_score_histogram_figure"](
                [0.1, 0.2, 0.3], 0.2, is_evalue=False, norm_mode="alignment_length"
            )
            axes = figure.axes[0]
            check("histogram title", axes.get_title())
            for text in axes.get_legend().get_texts():
                check("histogram legend", text.get_text())
            print("@@" + json.dumps({{"checked": checked, "left": left}}))
            """.format(foreign=foreign),
            pseudo_translation=True,
        )

    def test_every_text_shown_later_comes_from_a_catalog(self):
        checked = self.report["checked"]
        self.assertGreater(sum(name.startswith("tip ") for name in checked), 50)
        for name in ("tooltip VR_APP_DIR", "note foreign", "save", "consistency report",
                     "statistics report", "histogram title", "histogram legend"):
            self.assertIn(name, checked)
        self.assertEqual(self.report["left"], {})


class VRCatalogTests(unittest.TestCase):
    """opt_vr's catalog, emapssn_vr.ts: the texts VR Config marks that the main catalog lacks."""

    @classmethod
    def setUpClass(cls):
        import importlib.util

        path = os.path.join(VR_SRC, "resources", "languages", "Update_Translations_VR.py")
        spec = importlib.util.spec_from_file_location("Update_Translations_VR", path)
        cls.updater = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.updater)

    def test_the_catalog_lists_every_text_the_code_marks(self):
        lines = []
        self.assertEqual(self.updater.update_vr_catalogs(check=True, report=lines.append), 0, "\n".join(lines))

    def test_each_main_language_gets_a_vr_catalog(self):
        from utilities.Localization import read_catalog

        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, ignore_errors=True)
        source = os.path.join(folder, "src")
        own = os.path.join(source, "resources", "languages")
        main = os.path.join(folder, "main")
        os.makedirs(own)
        os.makedirs(main)
        with open(os.path.join(source, "window.py"), "w", encoding="utf-8") as handle:
            handle.write(
                "from PySide6.QtCore import QCoreApplication\n"
                "SHARED = QCoreApplication.translate(\"Config\", \"Shared sentence\")\n"
                "OWN = QCoreApplication.translate(\"Config\", \"Own sentence\")\n"
            )
        template = (
            '<?xml version="1.0" encoding="utf-8"?>\n<!DOCTYPE TS>\n<TS version="2.1"{language} sourcelanguage="en">\n'
            "<context>\n    <name>Config</name>\n    <message>\n        <source>Shared sentence</source>\n"
            '        <translation type="unfinished"></translation>\n    </message>\n</context>\n</TS>\n'
        )
        with open(os.path.join(main, "emapssn.ts"), "w", encoding="utf-8") as handle:
            handle.write(template.format(language=""))
        with open(os.path.join(main, "emapssn_de.ts"), "w", encoding="utf-8") as handle:
            handle.write(template.format(language=' language="de"'))
        lines = []
        options = dict(report=lines.append, source_dir=source, languages_dir=own, main_languages_dir=main)
        self.assertEqual(self.updater.update_vr_catalogs(**options), 0, "\n".join(lines))
        self.assertEqual(sorted(os.listdir(own)), ["emapssn_vr.ts", "emapssn_vr_de.qm", "emapssn_vr_de.ts"])
        self.assertEqual(
            [message.source for message in read_catalog(os.path.join(own, "emapssn_vr_de.ts"))], ["Own sentence"]
        )
        self.assertEqual(self.updater.update_vr_catalogs(check=True, **options), 0, "\n".join(lines))
        os.remove(os.path.join(own, "emapssn_vr_de.ts"))
        lines.clear()
        self.assertEqual(self.updater.update_vr_catalogs(check=True, **options), 1)
        self.assertTrue(any(line.startswith("emapssn_vr_de.ts is missing") for line in lines), lines)

    def test_it_lists_no_text_the_main_catalog_lists(self):
        from utilities.Localization import read_catalog

        updater = self.updater
        main = {message.key for message in read_catalog(updater.MAIN_LANGUAGES_DIR / "emapssn.ts")}
        own = [message.key for message in read_catalog(updater.LANGUAGES_DIR / f"{updater.CATALOG_NAME}.ts")]
        self.assertGreater(len(own), 20)
        self.assertEqual([key for key in own if key in main], [])

    def test_the_window_installs_it_with_the_main_catalog(self):
        report = report_from(
            """
            from desktop import Desktop_App
            installed = Desktop_App._installed_translations
            print("@@" + json.dumps({
                "language": installed.language,
                "extra": [[str(directory), name] for directory, name in installed.extra_catalogs],
                "title": window.windowTitle(),
            }))
            """,
            pseudo_translation=True,
        )
        self.assertEqual(report["language"], "pseudo")
        same_path = os.path.normcase(os.path.normpath(os.path.join(VR_SRC, "resources", "languages")))
        self.assertEqual(
            [[os.path.normcase(os.path.normpath(directory)), name] for directory, name in report["extra"]],
            [[same_path, "emapssn_vr"]],
        )
        # Its title is VR Config's own text, so it comes from opt_vr's catalog.
        self.assertTrue(report["title"].startswith("["), report["title"])


class BlastNetworkSaveTests(unittest.TestCase):
    """A BLAST network blanks both modes; Save keeps the alignment choice they hide.

    As in the desktop Config, saving used to fail with "invalid value for
    ALIGNMENT_SCORE" because the blank controls were saved as empty text. The
    case really saves, so it runs in a throwaway project (see run_gui_script).
    """

    @classmethod
    def setUpClass(cls):
        project = tempfile.mkdtemp()
        cls.addClassCleanup(shutil.rmtree, project, ignore_errors=True)
        cls.report = report_from(
            """
            select = namespace["select_combo_value"]
            value = namespace["combo_value"]

            window._set_network_type_controls("alignment")
            select(window.cb_score_mode, "local")
            select(window.cb_norm_mode, "average_sequence")
            window._set_network_type_controls("blast")
            blank = [window.cb_score_mode.currentIndex(), window.cb_norm_mode.currentIndex()]
            saved_ok = window.save_settings()
            window._set_network_type_controls("alignment")
            print("@@" + json.dumps({
                "blank": blank,
                "saved_ok": saved_ok,
                "tip": window.tip_panel.text(),
                "restored": [value(window.cb_score_mode), value(window.cb_norm_mode)],
            }))
            """,
            project_root=project,
        )
        settings_file = os.path.join(project, "opt_vr", "viewer_settings_vr.json")
        cls.saved = {}
        if os.path.exists(settings_file):
            with open(settings_file, encoding="utf-8") as handle:
                cls.saved = json.load(handle)

    def test_save_keeps_the_choice_the_blank_controls_hide(self):
        self.assertEqual(self.report["blank"], [-1, -1])
        self.assertTrue(self.report["saved_ok"], self.report["tip"])
        self.assertEqual(
            [self.saved.get("ALIGNMENT_SCORE"), self.saved.get("NORM_MODE")],
            ["local", "average_sequence"],
        )

    def test_leaving_blast_restores_the_choice(self):
        self.assertEqual(self.report["restored"], ["local", "average_sequence"])


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
    """Saving writes into the submodule and nowhere else.

    Both cases really save, so each runs in a throwaway project whose opt_vr
    folder stands in for this submodule. They used to save into the
    checkout's own viewer_settings_vr.json and restore its text afterwards:
    every run rewrote the user's file, a run killed in between left it
    changed, and a read-only settings file failed both outright.
    """

    def setUp(self):
        self.project = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.project, ignore_errors=True)
        self.vr_settings = os.path.join(self.project, "opt_vr", "viewer_settings_vr.json")

    def test_settings_round_trip_through_the_submodule_file(self):
        report = report_from(
            """
            window.inputs["VR_APP_DIR"].setText("no_such_build")
            window.inputs["VR_PORT"].setValue(5123)
            print("@@" + json.dumps({
                "saved": window.save_settings(),
                "tip": window.tip_panel.text(),
                "settings_file": namespace["SETTINGS_FILE"],
            }))
            """,
            project_root=self.project,
        )
        self.assertTrue(report["saved"], report["tip"])
        # The file Save writes is the one the next launch reads.
        self.assertEqual(
            os.path.normcase(report["settings_file"]), os.path.normcase(self.vr_settings)
        )
        with open(self.vr_settings, encoding="utf-8") as handle:
            saved = json.load(handle)
        self.assertIn(str(saved.get("VR_PORT")), ("5123", "5123.0"))
        for key in ("CACHE_FILE_DIR", "SAVED_LAYOUT_DIR", "INPUT_FILE_DIR"):
            self.assertIn(key, saved, "directories must be persisted")

    def test_the_desktop_settings_file_is_never_written(self):
        desktop = os.path.join(self.project, "viewer_settings.json")
        with open(desktop, "w", encoding="utf-8") as handle:
            handle.write("{}\n")
        before = self.fingerprint(desktop)
        report = report_from(
            """
            print("@@" + json.dumps({
                "saved": window.save_settings(),
                "tip": window.tip_panel.text(),
            }))
            """,
            project_root=self.project,
        )
        self.assertTrue(report["saved"], report["tip"])
        self.assertEqual(
            self.fingerprint(desktop), before, "the desktop program's settings were touched"
        )
        # Proof that Save wrote somewhere: otherwise the check above means nothing.
        self.assertTrue(os.path.isfile(self.vr_settings), "Save wrote no VR settings")

    @staticmethod
    def fingerprint(path):
        """The file's bytes and modification time, or None once it is gone."""
        if not os.path.exists(path):
            return None
        with open(path, "rb") as handle:
            return handle.read(), os.stat(path).st_mtime_ns


class VRSettingsSourceTests(unittest.TestCase):
    """The Qt-free settings module the viewer itself reads."""

    @classmethod
    def setUpClass(cls):
        # Settings_VR loads its settings file when first imported. Make that
        # load a missing file, not the user's, as the sibling modules do.
        with tempfile.TemporaryDirectory() as folder, mock.patch.dict(
            os.environ, {"SSN_VIEWER_SETTINGS_PATH": os.path.join(folder, "missing.json")}
        ):
            import Settings_VR  # noqa: F401

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
        """The wording is a pure function, so it is worth pinning directly.

        It is a Message, whose str() is the English the tests pin; the window
        shows it translated.
        """
        foreign = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, foreign, ignore_errors=True)
        open(os.path.join(foreign, "EMAP-SSN-VR.exe"), "w").close()
        report = report_from(
            """
            decide = namespace["bridge_note_text"]
            player = os.path.join(str(namespace["PROJECT_ROOT"]), "player")
            print("@@" + json.dumps({{
                "missing": str(decide(None, "127.0.0.1", 5005)),
                "match": str(decide(("127.0.0.1", 5005), "127.0.0.1", 5005)),
                "differs": str(decide(("127.0.0.1", 5005), "127.0.0.1", 6000)),
                "foreign": str(decide(None, "127.0.0.1", 5005, build_dir={foreign!r})),
                "player": str(decide(None, "127.0.0.1", 5005, build_dir=player)),
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


class VRAtomicWriteTests(unittest.TestCase):
    """_atomic_write_json clears temporary copies an interrupted save left behind."""

    def test_a_save_removes_stale_temporary_copies_but_not_recent_ones(self):
        report = report_from(
            """
            import tempfile, time
            from pathlib import Path
            folder = Path(tempfile.mkdtemp())
            target = folder / "viewer_settings_vr.json"
            stale = folder / ".viewer_settings_vr.json.interrupted.partial"
            recent = folder / ".viewer_settings_vr.json.inprogress.partial"
            # Another file's copy is not this save's to remove, however old.
            other = folder / ".layout_settings.json.1234.partial"
            for path in (stale, recent, other):
                path.write_text("{", encoding="utf-8")
            old = time.time() - 2 * namespace["_STALE_PARTIAL_SECONDS"]
            for path in (stale, other):
                os.utime(path, (old, old))
            namespace["_atomic_write_json"](target, {"NODE_SIZE": 12})
            print("@@" + json.dumps({
                "files": sorted(path.name for path in folder.iterdir()),
                "saved": json.loads(target.read_text(encoding="utf-8")),
            }))
            """
        )
        self.assertEqual(report["saved"], {"NODE_SIZE": 12})
        self.assertEqual(report["files"], sorted([
            "viewer_settings_vr.json",
            ".viewer_settings_vr.json.inprogress.partial",
            ".layout_settings.json.1234.partial",
        ]))


class CacheDiscoveryRaceTests(unittest.TestCase):
    """Hashing left running for earlier inputs never decides the target cache.

    The desktop Config's CacheDiscoveryRaceTests
    (tests/test_emapssn_config_cache_dropdown.py), run against this copy's
    code. Each CacheHashWorker hashes only when the script finishes it, on the
    script's thread, so every interleaving is deterministic; each case gets a
    fresh window.
    """

    @classmethod
    def setUpClass(cls):
        cls.report = report_from(
            """
            import tempfile
            from pathlib import Path
            import h5py
            import numpy as np

            cache_manifest = namespace["cache_manifest"]
            window_globals = window._request_cache_discovery.__globals__
            workers, interrupted = [], set()

            class DeferredHashWorker(window_globals["CacheHashWorker"]):
                def start(self):
                    workers.append(self)

                # A thread that never started ignores requestInterruption(),
                # so keep the request where run() looks for it.
                def requestInterruption(self):
                    interrupted.add(self.request_id)

                def isInterruptionRequested(self):
                    return self.request_id in interrupted

            window_globals["CacheHashWorker"] = DeferredHashWorker

            def open_window():
                # Two FASTA files share one BLAST network, and each pair has
                # its own compatible layout folder.
                workers.clear()
                interrupted.clear()
                work = Path(tempfile.mkdtemp(dir=os.getcwd()))
                (work / "a.fasta").write_text(">a1\\nMKTAYIAK\\n>a2\\nMKTAYIAR\\n", encoding="utf-8")
                (work / "b.fasta").write_text(">b1\\nMSDNELKQ\\n>b2\\nMSDNELKE\\n", encoding="utf-8")
                with h5py.File(work / "network.h5", "w") as network:
                    network.attrs["model_name"] = "BLAST"
                    network.create_dataset("headers", data=[b"a1", b"a2"])
                    network.create_dataset("i", data=np.asarray([0], dtype=np.uint16))
                    network.create_dataset("j", data=np.asarray([1], dtype=np.uint16))
                    network.create_dataset("score", data=np.asarray([1e-30]))
                gui = namespace["ConfigGUI"]()
                shown = {}
                for name in ("a.fasta", "b.fasta"):
                    sequence = cache_manifest.fingerprint_file(work / name)
                    network = cache_manifest.fingerprint_file(work / "network.h5")
                    compatibility = cache_manifest.build_compatibility(
                        sequence["sha256"], network["sha256"], "blast",
                        **gui._cache_setting_values(),
                    )
                    folder = work / "layouts" / (Path(name).stem + "_layout")
                    cache_manifest.write_manifest_atomic(
                        folder, cache_manifest.build_manifest(sequence, network, compatibility)
                    )
                    shown[name] = "Compatible Folder: " + folder.name
                gui.inputs["SAVED_LAYOUT_DIR"].setText(str(work / "layouts"))
                gui.inputs["FASTA_DIR"].setText(str(work))
                gui.inputs["HDF5_DIR"].setText(str(work))
                gui.cb_hdf5.setCurrentText("network.h5")
                return gui, work, shown

            def close(gui):
                gui.close()
                gui.deleteLater()
                app.processEvents()

            def select(gui, fasta_name):
                gui.cb_fasta.setCurrentText(fasta_name)
                assert gui.cb_fasta.currentText() == fasta_name, fasta_name

            def finish(worker):
                # Hash and report on this thread, as the worker's own would.
                worker.run()
                app.processEvents()

            report = {}

            # a.fasta is still being hashed when b.fasta, already hashed, is
            # chosen again.
            gui, work, shown = open_window()
            select(gui, "b.fasta")
            finish(workers[-1])
            first = gui.lbl_cache_tracker.text()
            select(gui, "a.fasta")
            hashing_a = workers[-1]
            request_a = hashing_a.request_id
            select(gui, "b.fasta")
            finish(hashing_a)
            late = gui.lbl_cache_tracker.text()
            folder = os.path.basename(gui.current_cache_folder or "")
            gui.update_live_validators()
            report["late_result"] = {
                "expected": shown["b.fasta"], "first": first, "late": late,
                "folder": folder, "refreshed": gui.lbl_cache_tracker.text(),
                "interrupted": request_a in interrupted,
            }
            close(gui)

            # Back to a.fasta after its hashing was dropped.
            gui, work, shown = open_window()
            select(gui, "b.fasta")
            finish(workers[-1])
            select(gui, "a.fasta")
            dropped = workers[-1]
            select(gui, "b.fasta")
            select(gui, "a.fasta")
            reselected = gui.lbl_cache_tracker.text()
            started = len(workers)
            finish(dropped)
            after_dropped = gui.lbl_cache_tracker.text()
            if workers[-1] is not dropped:
                finish(workers[-1])
            report["dropped"] = {
                "expected": shown["a.fasta"], "reselected": reselected,
                "started": started, "after_dropped": after_dropped,
                "final": gui.lbl_cache_tracker.text(),
            }
            close(gui)

            # a.fasta is replaced by b.fasta's sequences right after it is read.
            gui, work, shown = open_window()
            fingerprint_file = cache_manifest.fingerprint_file

            def fingerprint_then_rewrite(path, **options):
                record = fingerprint_file(path, **options)
                if os.path.basename(path) == "a.fasta":
                    a_fasta = work / "a.fasta"
                    a_fasta.write_bytes((work / "b.fasta").read_bytes())
                    modified = a_fasta.stat().st_mtime_ns + 5_000_000_000
                    os.utime(a_fasta, ns=(modified, modified))
                return record

            select(gui, "a.fasta")
            with mock.patch.object(
                cache_manifest, "fingerprint_file", side_effect=fingerprint_then_rewrite
            ):
                finish(workers[-1])
            gui.update_live_validators()
            refreshed = gui.lbl_cache_tracker.text()
            started = len(workers)
            if started > 1:
                finish(workers[-1])
            report["rewritten"] = {
                "expected": shown["b.fasta"], "refreshed": refreshed,
                "started": started, "final": gui.lbl_cache_tracker.text(),
            }
            close(gui)

            # Each way discovery can give up on the selected inputs.
            gui, work, shown = open_window()

            def clear_the_selection():
                gui.cb_fasta.setCurrentText("")

            def fail_to_read_the_inputs():
                with mock.patch.object(
                    cache_manifest, "file_cache_key", side_effect=OSError("access denied")
                ):
                    gui.update_live_validators()

            def choose_inputs_that_need_hashing():
                gui.cb_fasta.setCurrentText("b.fasta")

            def remove_the_network():
                (work / "network.h5").unlink()
                gui.update_live_validators()

            report["give_up"] = {}
            for fasta_name, give_up in (
                ("a.fasta", clear_the_selection),
                ("b.fasta", fail_to_read_the_inputs),
                ("a.fasta", choose_inputs_that_need_hashing),
                ("a.fasta", remove_the_network),
            ):
                select(gui, fasta_name)
                hashing = workers[-1]
                give_up()
                stopped = hashing.request_id in interrupted
                finish(hashing)
                report["give_up"][give_up.__name__] = {
                    "stopped": stopped, "tracker": gui.lbl_cache_tracker.text(),
                }
            close(gui)
            print("@@" + json.dumps(report))
            """
        )

    def test_hashing_left_running_for_earlier_inputs_never_overrides_cached_ones(self):
        case = self.report["late_result"]
        self.assertEqual(case["first"], case["expected"])
        self.assertEqual(case["late"], case["expected"])
        self.assertEqual(case["folder"], "b_layout")
        # Nor was a.fasta's hash cached for b.fasta: the next refresh agrees.
        self.assertEqual(case["refreshed"], case["expected"])
        self.assertTrue(case["interrupted"])

    def test_inputs_whose_hashing_was_dropped_are_hashed_again(self):
        case = self.report["dropped"]
        self.assertEqual(case["reselected"], "Checking input files…")
        self.assertEqual(case["started"], 3)
        self.assertEqual(case["after_dropped"], "Checking input files…")
        self.assertEqual(case["final"], case["expected"])

    def test_a_file_rewritten_while_it_is_hashed_is_hashed_again(self):
        case = self.report["rewritten"]
        self.assertEqual(case["refreshed"], "Checking input files…")
        self.assertEqual(case["started"], 2)
        self.assertEqual(case["final"], case["expected"])

    def test_giving_up_on_the_selected_inputs_stops_their_hashing(self):
        for way, message in (
            ("clear_the_selection", "Target Cache: Missing FASTA or HDF5"),
            ("fail_to_read_the_inputs", "Cache input error: access denied"),
            ("choose_inputs_that_need_hashing", "Checking input files…"),
            ("remove_the_network", "Target Cache: Selected input file is missing"),
        ):
            with self.subTest(way):
                self.assertEqual(
                    self.report["give_up"][way], {"stopped": True, "tracker": message}
                )


if __name__ == "__main__":
    unittest.main()
