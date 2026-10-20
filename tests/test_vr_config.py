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
    if sys.platform != "win32":
        # The GUI refuses to start anywhere else (_bootstrap_vr), so every
        # test that runs it is skipped, as the player and lock tests are.
        raise unittest.SkipTest("the VR Configuration GUI runs on Windows only")
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

        def finish_statistics(window, timeout=60.0):
            # run_statistics works on a worker thread; wait for it, inside any patch its reads need.
            import time
            deadline = time.monotonic() + timeout
            while window._statistics_request is not None:
                if time.monotonic() > deadline:
                    raise AssertionError("the network statistics did not finish")
                app.processEvents()
                time.sleep(0.005)
            app.processEvents()
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
                "unused_in_vr": sorted(namespace["UNUSED_IN_VR"]),
                "low_resource_keys": sorted(
                    key for key in namespace["VISUAL_PROFILE_DEFAULTS"]
                    if key.startswith("LOW_RESOURCE_") or key in ("FEWER_EDGES_WHILE_MOVING", "SHOW_FPS")),
                "profile_tabs": sorted(window.profile_selectors),
                "cache_settings": window._cache_setting_values(),
                "settings_file": namespace["SETTINGS_FILE"],
                "submodule": _bootstrap_vr.OPT_VR_DIR,
                "has_statistics": hasattr(window, "run_statistics"),
                "has_histogram": hasattr(window, "btn_hist") or hasattr(window, "run_histogram"),
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
        for key in ("TEXT_SIZE", "TEXT_COLOR", "FEWER_EDGES_WHILE_MOVING", "LOW_RESOURCE_ANIMATIONS",
                    "LOW_RESOURCE_DRAWING", "LOW_RESOURCE_WEBSERVER", "SHOW_FPS", "LOW_RESOURCE_MODE"):
            self.assertNotIn(key, self.report["inputs"], key)

    def test_every_low_resource_setting_is_unused_in_vr(self):
        """Low Resource Mode's categories and Show FPS, as the desktop Config has them."""
        self.assertEqual(
            set(self.report["low_resource_keys"]) - set(self.report["unused_in_vr"]), set())
        self.assertIn("SHOW_FPS", self.report["low_resource_keys"])

    def test_the_optional_embedding_input_came_with_the_copy(self):
        """Shared commands that need an embedding run in VR too."""
        for key in ("EMBED_FILE", "EMBED_DIR", "MSA_FILE", "MSA_DIR"):
            self.assertIn(key, self.report["inputs"], key)

    def test_packing_geometry_has_a_control(self):
        """In 3D, Square packs components into a cube and Circle into a ball."""
        self.assertIn("PACKING_GEOMETRY", self.report["inputs"])

    def test_node_colour_has_exactly_one_control(self):
        """Settings_VR republishes INITIAL_NODE_COLOR as NEIGHBOR_COLOR and wins,
        so a second control would silently discard the user's choice."""
        self.assertIn("INITIAL_NODE_COLOR", self.report["inputs"])
        self.assertNotIn("NEIGHBOR_COLOR", self.report["inputs"])

    def test_inherited_features_survived_the_copy(self):
        """Statistics and the report panel come along for free."""
        for flag in ("has_statistics", "has_stat_display"):
            self.assertTrue(self.report[flag], flag)

    def test_the_histogram_button_is_gone_as_in_the_desktop_gui(self):
        """The statistics report draws the score distribution behind its table."""
        self.assertFalse(self.report["has_histogram"])

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


class EmbeddingRootTests(unittest.TestCase):
    """The Directories tab lists the embedding directory as its fourth root.

    Like the main program's Config, which this window is a copy of: after the
    Input File, Cache File and Analysis Results Directories and before the
    separator, standing for ``$embedding$`` and refreshing the Embedding Input
    dropdown once when it changes.
    """

    @classmethod
    def setUpClass(cls):
        cls.report = report_from(
            """
            import tempfile
            from desktop.Tip_Panel import tip_plain
            layout = window.labels["INPUT_FILE_DIR"].parentWidget().layout()
            row = lambda widget: layout.getWidgetPosition(widget)[0]
            keys = ["INPUT_FILE_DIR", "CACHE_FILE_DIR", "ANALYSIS_RESULT_DIR", "EMBED_DIR",
                    "FASTA_DIR", "MSA_DIR", "HDF5_DIR", "METADATA_DIR", "HEADER_LIST_DIR",
                    "SAVED_LAYOUT_DIR", "SETTING_EXPORT_DIR"]
            rows = {key: row(window.labels[key]) for key in keys}
            separator_row = row(window.directory_base_separator.parentWidget())
            initial = window.inputs["EMBED_DIR"].text()
            refreshed = []
            real_refresh = window.refresh_combo

            def counting_refresh(combo, key, extensions):
                if combo is window.cb_embed:
                    refreshed.append(key)
                return real_refresh(combo, key, extensions)

            with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
                open(os.path.join(folder, "listed_[model]_embeddings.h5"), "wb").close()
                window.refresh_combo = counting_refresh
                window.inputs["EMBED_DIR"].setText(folder)
                del window.refresh_combo
                items = [window.cb_embed.itemText(i) for i in range(window.cb_embed.count())]
                resolved = window._resolved_directory_value("$embedding$/sub")
                print("@@" + json.dumps({
                    "rows": rows,
                    "separator_row": separator_row,
                    "initial": initial,
                    "folder": folder,
                    "refreshed": refreshed,
                    "items": items,
                    "resolved": resolved,
                    "aliases": namespace["DIRECTORY_PATH_ALIASES"],
                    "open_button": "EMBED_DIR" in window.directory_open_buttons,
                    "tip": tip_plain(window.tip_db[window.inputs["EMBED_DIR"]]),
                    "label_tip": tip_plain(window.tip_db[window.labels["EMBED_DIR"]]),
                }))
            """
        )

    def test_it_is_the_fourth_root_and_the_separator_follows_it(self):
        rows = self.report["rows"]
        roots = ["INPUT_FILE_DIR", "CACHE_FILE_DIR", "ANALYSIS_RESULT_DIR", "EMBED_DIR"]
        self.assertEqual([rows[key] for key in roots],
                         list(range(rows[roots[0]], rows[roots[0]] + 4)))
        self.assertEqual(self.report["separator_row"], rows["EMBED_DIR"] + 1)
        for key in ("FASTA_DIR", "MSA_DIR", "HDF5_DIR", "METADATA_DIR",
                    "HEADER_LIST_DIR", "SAVED_LAYOUT_DIR", "SETTING_EXPORT_DIR"):
            self.assertGreater(rows[key], self.report["separator_row"], key)
        self.assertTrue(self.report["open_button"])

    def test_the_root_has_the_alias_and_a_root_style_tip(self):
        self.assertEqual(self.report["aliases"]["$embedding$"], "EMBED_DIR")
        self.assertEqual(len(self.report["aliases"]), 4)
        for tip in (self.report["tip"], self.report["label_tip"]):
            self.assertIn("$embedding$", tip)
        resolved = os.path.normcase(os.path.normpath(self.report["resolved"]))
        self.assertEqual(
            resolved,
            os.path.normcase(os.path.normpath(os.path.join(self.report["folder"], "sub"))),
        )

    def test_changing_it_refreshes_the_embedding_dropdown_once(self):
        self.assertEqual(self.report["refreshed"], ["EMBED_DIR"])
        self.assertEqual(self.report["items"], ["", "listed_[model]_embeddings.h5"])

    def test_old_settings_holding_the_default_folder_still_show_it(self):
        self.assertEqual(self.report["initial"], "Embeddings")


class TipPanelStatusLockTests(unittest.TestCase):
    """Hovering never replaces a status message in the tip panel, as in the desktop Config.

    Hovering shows tips only while the panel holds a tip. A left click, or
    focus by Tab, on an element with a tip always shows it and makes hovering
    work again; right clicks and focus Qt moves by itself don't. Tips never
    open Qt's own tooltip popup.
    """

    @classmethod
    def setUpClass(cls):
        cls.report = report_from(
            """
            import tempfile
            import h5py
            from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
            from PySide6.QtGui import QFocusEvent, QHelpEvent, QMouseEvent, QTextDocumentFragment
            from PySide6.QtWidgets import QToolTip

            from desktop.Tip_Panel import Tip, plain

            def panel():
                shown = QTextDocumentFragment.fromHtml(window.tip_panel.text()).toPlainText()
                # A status message's icon is an image: one object-replacement character.
                return shown.replace("\\ufffc", "").strip()

            def tip_texts(key):
                # The texts a tip shows: a rich tip's, each by itself, or a plain tip as it is.
                tip = window.tip_db_keys[key]
                return [plain(text) for text in tip.texts()] if isinstance(tip, Tip) else [tip]

            def hover(widget):
                app.sendEvent(widget, QHelpEvent(
                    QEvent.Type.ToolTip, QPoint(1, 1), widget.mapToGlobal(QPoint(1, 1))
                ))
                shown = QToolTip.isVisible()
                QToolTip.hideText()
                return shown

            def press(widget, button):
                for event_type, buttons in ((QEvent.Type.MouseButtonPress, button),
                                            (QEvent.Type.MouseButtonRelease, Qt.MouseButton.NoButton)):
                    app.sendEvent(widget, QMouseEvent(
                        event_type, QPointF(1, 1), QPointF(1, 1), button, buttons,
                        Qt.KeyboardModifier.NoModifier,
                    ))

            def focus(widget, reason):
                app.sendEvent(widget, QFocusEvent(QEvent.Type.FocusIn, reason))

            window.show()
            app.processEvents()
            reference = window.labels["ALIGNMENT_REFERENCE"]
            offset = window.labels["ALIGNMENT_OFFSET"]
            steps = {"tips": {key: tip_texts(key) for key in ("ALIGNMENT_REFERENCE", "ALIGNMENT_OFFSET")}}
            # The Clear button has a tooltip of its own, so Qt would pop it up.
            steps["popup before a check"] = hover(window.btn_clear_top_edge)
            hover(reference)
            steps["hover before a check"] = panel()

            folder = tempfile.mkdtemp()
            with open(os.path.join(folder, "nodes.fasta"), "w", encoding="utf-8") as handle:
                handle.write(">a\\nMKTA\\n>b\\nMSEQ\\n")
            with h5py.File(os.path.join(folder, "network.h5"), "w") as hf:
                hf.create_dataset("headers", data=[b"a", b"b"])
            for key in ("FASTA_DIR", "HDF5_DIR"):
                window.inputs[key].blockSignals(True)
                window.inputs[key].setText(folder)
                window.inputs[key].blockSignals(False)
            for combo, name in ((window.cb_fasta, "nodes.fasta"), (window.cb_hdf5, "network.h5"),
                                (window.cb_msa, None)):
                combo.blockSignals(True)
                combo.clear()
                if name:
                    combo.addItem(name)
                combo.blockSignals(False)
            window.run_consistency_check()
            steps["check result"] = panel()
            steps["check is a table"] = "<table" in window.tip_panel.text()
            corner = window.tip_panel._corner_icon()
            steps["corner after a check"] = corner.icon_name
            steps["popup after a check"] = hover(window.btn_clear_top_edge)
            hover(offset)
            press(reference, Qt.MouseButton.RightButton)
            focus(window.line_ref, Qt.FocusReason.ActiveWindowFocusReason)
            steps["after hover, right click and window focus"] = panel()
            press(reference, Qt.MouseButton.LeftButton)
            steps["after a left click"] = panel()
            steps["corner after a left click"] = corner.icon_name
            hover(offset)
            steps["hover after the left click"] = panel()

            with mock.patch.object(window, "_prepare_profile_writes",
                                   return_value=([], dict(window._custom_settings), [], [])):
                window.save_only()
            steps["save message"] = panel()
            hover(offset)
            steps["hover after the save"] = panel()
            focus(window.line_ref, Qt.FocusReason.TabFocusReason)
            steps["after Tab"] = panel()
            hover(offset)
            steps["hover after Tab"] = panel()

            with mock.patch("h5py.File", side_effect=OSError("unreadable network")):
                window.run_statistics()
                finish_statistics(window)
            steps["statistics message"] = panel()
            hover(offset)
            steps["hover after statistics"] = panel()
            print("@@" + json.dumps(steps))
            """
        )
        cls.tips = cls.report["tips"]

    def assert_shows_tip(self, shown, key):
        """shown is the tip of key: a plain tip as it is, a rich tip holding each of its texts."""
        texts = self.tips[key]

        def squashed(text):
            # A chip pads its text with spaces, which are not in the tip's own text.
            return "".join(text.split())

        if len(texts) == 1:
            self.assertEqual(shown, texts[0])
        for text in texts:
            self.assertIn(squashed(text), squashed(shown))

    def test_hovering_shows_tips_until_a_status_message_arrives(self):
        self.assert_shows_tip(self.report["hover before a check"], "ALIGNMENT_REFERENCE")
        result = self.report["check result"]
        # The result is a table of rich text, with a row per check.
        self.assertIn("FASTA vs HDF5", result)
        self.assertIn("strict subset", result)
        self.assertTrue(self.report["check is a table"])
        self.assertEqual(self.report["after hover, right click and window focus"], result)

    def test_the_corner_icon_shows_the_checks_verdict_until_a_tip_replaces_it(self):
        # Every check passed: the corner shows the success icon, and a tip gives back the info icon.
        self.assertEqual(self.report["corner after a check"], "check")
        self.assertEqual(self.report["corner after a left click"], "info")

    def test_a_left_click_or_tab_shows_its_tip_and_reenables_hovering(self):
        for picked, hovered in (("after a left click", "hover after the left click"),
                                ("after Tab", "hover after Tab")):
            with self.subTest(picked):
                self.assert_shows_tip(self.report[picked], "ALIGNMENT_REFERENCE")
                self.assert_shows_tip(self.report[hovered], "ALIGNMENT_OFFSET")

    def test_save_and_statistics_messages_also_stay_while_hovering(self):
        self.assertTrue(self.report["save message"].startswith("Settings saved successfully."))
        self.assertEqual(self.report["hover after the save"], self.report["save message"])
        self.assertEqual(
            self.report["statistics message"],
            "Error during network statistics calculation: unreadable network",
        )
        self.assertEqual(self.report["hover after statistics"], self.report["statistics message"])

    def test_tips_never_open_qt_tooltip_popups(self):
        self.assertFalse(self.report["popup before a check"])
        self.assertFalse(self.report["popup after a check"])


class TipPanelFixedHeightTests(unittest.TestCase):
    """The tip panel is as tall at the first layout as the desktop Config's, and what it shows never changes that.

    It starts at a fixed number of lines of its own font; text that does not fit scrolls, by a
    vertical bar only while it is needed, and each new tip starts at the top. The pointer resting
    on fields shows their tips, until a message, as in the desktop Config.
    """

    @classmethod
    def setUpClass(cls):
        cls.report = report_from(
            """
            from PySide6.QtCore import QEvent, QObject, QPoint, Qt
            from PySide6.QtGui import QTextDocumentFragment
            from PySide6.QtTest import QTest
            from PySide6.QtWidgets import QTextEdit

            window.resize(1000, 650)
            window.show()
            window.activateWindow()
            app.processEvents()
            panel = window.tip_panel
            first_height = panel.height()
            held = lambda: [panel.height(), window.left_split.sizes(), window.tabs.height(),
                            [window.minimumSizeHint().width(), window.minimumSizeHint().height()]]
            before = held()
            bar = panel.verticalScrollBar()
            moved, scrolls, horizontal, mismatch = [], [], [], []
            # The tips of fields this window has (VR hides some of the desktop's, whose tips no pointer reaches).
            shown_tips = {key: entry for key, entry in window._field_tips.items() if entry.field.widget is not None}
            for key, entry in shown_tips.items():
                panel.setTip(entry)
                app.processEvents()
                if held() != before:
                    moved.append(key)
                needed, available = panel.document().size().height(), panel.viewport().height()
                if bar.isVisible() != (needed > available):
                    mismatch.append(key)
                if bar.isVisible():
                    scrolls.append(key)
                    bar.setValue(bar.maximum())
                horizontal.append(panel.horizontalScrollBar().isVisible())
            tips = len(shown_tips)
            panel.setTip(window._field_tips["NORM_MODE"])
            bar.setValue(bar.maximum())
            panel.setTip(window._field_tips["ALIGNMENT_OFFSET"])
            at_top = bar.value() == 0

            def title():
                text = QTextDocumentFragment.fromHtml(panel.text()).toPlainText()
                return text.replace("\\ufffc", "").strip().split("\\n")[0].strip()

            def real_hover(widget):
                class Spy(QObject):
                    arrived = False

                    def eventFilter(spy, watched, event):
                        if watched is widget and event.type() == QEvent.Type.ToolTip:
                            spy.arrived = True
                        return False

                spy = Spy()
                app.installEventFilter(spy)
                window.activateWindow()
                QTest.mouseMove(window, QPoint(2, 2))
                QTest.qWait(30)
                QTest.mouseMove(widget, QPoint(5, 5))
                QTest.qWait(30)
                QTest.mouseMove(widget, QPoint(7, 6))
                waited = 0
                while not spy.arrived and waited < 3000:
                    QTest.qWait(50)
                    waited += 50
                app.processEvents()
                app.removeEventFilter(spy)
                return spy.arrived

            window.tabs.setCurrentIndex(0)
            first, second = window.labels["NODE_FASTA_FILE"], window.labels["MSA_FILE"]
            pointer = {"visible": first.isVisible() and second.isVisible()}
            pointer["first"] = [real_hover(first), title()]
            pointer["second"] = [real_hover(second), title()]
            panel.setStatus("success", "Settings saved.")
            message = panel.text()
            pointer["locked second"] = [real_hover(second), panel.text() == message]
            pointer["locked first"] = [real_hover(first), panel.text() == message]
            QTest.mouseClick(first, Qt.MouseButton.LeftButton, pos=QPoint(5, 5))
            app.processEvents()
            pointer["click"] = title()
            pointer["after click"] = [real_hover(second), title()]
            print("@@" + json.dumps({
                "first_height": first_height, "preferred": panel.preferred_height(),
                "is_scrolling_text_edit": isinstance(panel, QTextEdit),
                "moved": moved, "scrolls": scrolls, "mismatch": mismatch, "tips": tips,
                "horizontal": any(horizontal), "at_top": at_top, "pointer": pointer,
            }))
            """
        )

    def test_the_panel_starts_at_its_fixed_height_and_no_tip_or_message_moves_anything(self):
        report = self.report
        self.assertTrue(report["is_scrolling_text_edit"])
        self.assertEqual(report["first_height"], report["preferred"])
        self.assertEqual(report["moved"], [])
        self.assertFalse(report["horizontal"])

    def test_a_tip_scrolls_exactly_when_it_does_not_fit_and_a_new_one_starts_at_the_top(self):
        report = self.report
        self.assertEqual(report["mismatch"], [])
        self.assertIn("NORM_MODE", report["scrolls"])
        self.assertLess(len(report["scrolls"]), report["tips"])
        self.assertTrue(report["at_top"])

    def test_the_real_pointer_follows_the_fields_until_a_message_and_a_left_click_gives_it_back(self):
        pointer = self.report["pointer"]
        self.assertTrue(pointer["visible"])
        self.assertEqual(pointer["first"], [True, "Sequence Set / Subset (.fasta)"])
        self.assertEqual(pointer["second"], [True, "MSA Input (.fasta / _sparse.h5)"])
        # A status message: hovering leaves it where it is (the ToolTip event did arrive).
        self.assertEqual(pointer["locked second"], [True, True])
        self.assertEqual(pointer["locked first"], [True, True])
        self.assertEqual(pointer["click"], "Sequence Set / Subset (.fasta)")
        self.assertEqual(pointer["after click"], [True, "MSA Input (.fasta / _sparse.h5)"])


class RichTipTests(unittest.TestCase):
    """Every tip of the window is a Tip the shared panel lays out, as in the desktop Config.

    The live notes (a colour's swatch, the folder a directory resolves to, the
    devices found) and the range and default facts are the shared code's,
    checked here only where this window wires them. What is VR's own: the
    tips of the bridge fields, and the client note that joins three of them.
    """

    @classmethod
    def setUpClass(cls):
        cls.report = report_from(
            """
            import os, re, tempfile
            from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
            from PySide6.QtGui import QMouseEvent, QTextDocumentFragment
            from desktop.Desktop_App import NAME_ITEM_ROLE
            from desktop.Tip_Panel import FieldTip, Tip, resolve, tip_plain

            def click(widget):
                app.sendEvent(widget, QMouseEvent(
                    QEvent.Type.MouseButtonPress, QPointF(1, 1), QPointF(1, 1), Qt.MouseButton.LeftButton,
                    Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                ))
                return QTextDocumentFragment.fromHtml(window.tip_panel.text()).toPlainText().replace(chr(0xfffc), "")

            def squash(text):
                return re.sub(r"[ \\t\\r\\n]+", " ", text).strip()

            keys = list(namespace["VR_CONTROL_KEYS"])
            report = {"keys": keys}
            report["all are tips"] = all(isinstance(tip, Tip) for tip in window.tip_db_keys.values())
            report["own"] = {}
            for key in keys:
                widget = window.inputs[key]
                entry = window.tip_db[widget]
                report["own"][key] = {
                    "field": isinstance(entry, FieldTip) and entry.field.key,
                    "title": isinstance(entry, FieldTip) and entry.field.title(),
                    "label shares it": window.tip_db[window.labels[key]] is entry,
                    "tooltip is plain": widget.toolTip() == tip_plain(entry),
                    "facts": dict(resolve(entry).facts),
                    "summary": resolve(entry).summary,
                }

            # The client note, over several refreshes: once on each endpoint field and nowhere else.
            tab = "visual_effects"
            profile = dict(namespace["VR_VISUAL_PROFILE_DEFAULTS"])
            profile.update(VR_APP_DIR="test_build", VR_HOST="10.0.0.5", VR_PORT=6000)
            with mock.patch.object(namespace["Player_Build_VR"], "read_endpoint", return_value=("localhost", 7777)):
                for _ in range(3):
                    window._apply_profile_data(tab, profile)
                window.inputs["VR_PORT"].setValue(6001)
                window.inputs["VR_PORT"].setValue(6000)
                note = squash(window._bridge_note)
                report["note"] = note
                report["noted"] = {
                    key: squash(window.inputs[key].toolTip()).count(note) for key in keys
                }
                report["noted label"] = squash(window.labels["VR_PORT"].toolTip()).count(note)
                report["noted browse"] = squash(window._client_browse_button.toolTip()).count(note)
                report["browse is the field's"] = (
                    window._client_browse_button.toolTip() == window.inputs["VR_APP_DIR"].toolTip()
                )
                report["panel shows it"] = note in squash(click(window.labels["VR_HOST"]))
                report["panel title"] = squash(click(window.labels["VR_HOST"])).startswith(
                    window.tip_db[window.inputs["VR_HOST"]].field.title()
                )
            with mock.patch.object(namespace["Player_Build_VR"], "read_endpoint", return_value=None):
                window._apply_profile_data(tab, profile)
                report["note after"] = squash(window._bridge_note)
                report["noted after"] = squash(window.inputs["VR_APP_DIR"].toolTip()).count(report["note after"])
                report["old note gone"] = note not in squash(window.inputs["VR_APP_DIR"].toolTip())

            # VR's defaults are facts too.
            report["port default"] = dict(resolve(window.tip_db[window.inputs["VR_PORT"]]).facts).get("Default")
            report["default port"] = str(namespace["VR_PROFILE_DEFAULTS"]["VR_PORT"])

            # The live notes this window wires.
            colours = {}
            for key in ("INITIAL_NODE_COLOR", "HOVER_COLOR", "CONNECTED_NODE_COLOR", "EDGE_COLOR", "NODE_BOUNDARY_COLOR"):
                window.inputs[key].setText("#123456")
                colours[key] = "Current color: #123456" in squash(click(window.labels[key]))
                window.inputs[key].setText("")
                colours[key + " blank"] = "Current color" not in squash(
                    QTextDocumentFragment.fromHtml(window.tip_panel.text()).toPlainText()
                )
            report["colours"] = colours

            combo = window.inputs["LAYOUT_DEVICE_SELECTION"]
            for index in reversed(range(combo.count())):
                combo.removeItem(index)
            combo.addItem("Automatic", "auto")
            report["no device"] = "Detected devices" in squash(click(window.labels["LAYOUT_DEVICE_SELECTION"]))
            combo.addItem("NVIDIA A100-SXM4-40GB", "cuda:0")
            combo.setItemData(combo.count() - 1, True, NAME_ITEM_ROLE)
            report["device"] = squash(click(window.labels["LAYOUT_DEVICE_SELECTION"]))

            with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
                window.inputs["SETTING_EXPORT_DIR"].setText(os.path.join(folder, "exports"))
                window.inputs["FASTA_DIR"].setText(os.path.join(folder, "fasta"))
                scope = type(window)._folder_note.__globals__
                with mock.patch.dict(scope, {"free_bytes": lambda path: 7.5 * 1024 ** 3}):
                    report["export"] = squash(click(window.labels["SETTING_EXPORT_DIR"]))
                    report["fasta"] = squash(click(window.labels["FASTA_DIR"]))
                report["folder"] = folder
            print("@@" + json.dumps(report))
            """
        )

    def test_every_tip_is_a_tip_and_each_of_the_bridge_fields_has_its_own(self):
        self.assertTrue(self.report["all are tips"])
        self.assertEqual(
            self.report["keys"],
            ["VR_APP_DIR", "VR_HOST", "VR_PORT", "ENABLE_EDGE_FILTERING", "MAX_RENDER_EDGES",
             "DISTANCE_SCALE", "EXIT_WITH_UNITY"],
        )
        titles = {
            "VR_APP_DIR": "VR Client Build", "VR_HOST": "VR Client Host", "VR_PORT": "VR Client Port",
            "MAX_RENDER_EDGES": "Max Edges", "DISTANCE_SCALE": "Distance Scale",
        }
        for key in self.report["keys"]:
            with self.subTest(key=key):
                own = self.report["own"][key]
                self.assertEqual(own["field"], key)
                self.assertTrue(own["title"])
                self.assertTrue(own["label shares it"])
                # The endpoint fields' tooltips add the client note to the tip.
                self.assertTrue(own["tooltip is plain"] or key in ("VR_APP_DIR", "VR_HOST", "VR_PORT"))
                self.assertEqual(own["facts"]["Setting"], key)
                self.assertTrue(own["summary"])
        for key, title in titles.items():
            self.assertEqual(self.report["own"][key]["title"], title)

    def test_the_client_note_joins_the_three_endpoint_fields_once_however_often_it_is_refreshed(self):
        report = self.report
        self.assertTrue(report["note"])
        self.assertEqual(
            {key: count for key, count in report["noted"].items() if count},
            {"VR_APP_DIR": 1, "VR_HOST": 1, "VR_PORT": 1},
        )
        self.assertEqual((report["noted label"], report["noted browse"]), (1, 1))
        self.assertTrue(report["browse is the field's"])
        self.assertTrue(report["panel shows it"])
        self.assertTrue(report["panel title"])

    def test_a_new_client_state_replaces_the_note_and_does_not_add_to_it(self):
        report = self.report
        self.assertNotEqual(report["note after"], report["note"])
        self.assertEqual(report["noted after"], 1)
        self.assertTrue(report["old note gone"])

    def test_vrs_own_defaults_are_facts(self):
        self.assertEqual(self.report["port default"], self.report["default port"])

    def test_the_colour_fields_show_a_swatch_note_and_a_blank_one_none(self):
        for key, ok in self.report["colours"].items():
            with self.subTest(key=key):
                self.assertTrue(ok)

    def test_the_layout_device_tip_lists_the_devices_found_by_name(self):
        self.assertFalse(self.report["no device"])
        self.assertIn("Detected devices: NVIDIA A100-SXM4-40GB", self.report["device"])

    def test_a_directory_tip_names_its_folder_and_the_export_folder_the_room_free(self):
        folder = self.report["folder"]
        self.assertIn(os.path.join(folder, "exports"), self.report["export"].replace("​", ""))
        self.assertIn("7.5 GiB free on its drive.", self.report["export"])
        self.assertIn("Resolves to", self.report["fasta"])
        self.assertNotIn("free on its drive", self.report["fasta"])


class ConsistencyReportTests(unittest.TestCase):
    """The Consistency Check shows a table with a row per check, as in the desktop Config.

    What each check says is the desktop Config's tests' business; here the
    copy must lay the report out: one row per check, what the MSA misses
    named below the table, all of it shown, and a header too long for the
    panel wrapped rather than widening the window.
    """

    @classmethod
    def setUpClass(cls):
        cls.report = report_from(
            """
            import tempfile
            import h5py
            from PySide6.QtGui import QTextCursor, QTextDocument, QTextTable

            window.resize(1000, 650)
            window.show()
            app.processEvents()
            first_height = window.tip_panel.height()
            folder = tempfile.mkdtemp()
            long_header = "tr" + "A0A0A0_9BACT" * 40
            headers = ["WP_1_alpha", "WP_2_beta", long_header]
            sequences = ["MKTAYIAK", "MSEQNNTE", "MAAAGGGK"]
            with open(os.path.join(folder, "nodes.fasta"), "w", encoding="utf-8") as handle:
                for header, sequence in zip(headers, sequences):
                    handle.write(">" + header + "\\n" + sequence + "\\n")
            with open(os.path.join(folder, "alignment.fasta"), "w", encoding="utf-8") as handle:
                handle.write(">WP_1_alpha\\nMKTAYIAK\\n>WP_2_beta\\nMSEQNNTE\\n")
            with h5py.File(os.path.join(folder, "network.h5"), "w") as hf:
                hf.create_dataset("headers", data=[header.encode() for header in headers])
            for key in ("FASTA_DIR", "HDF5_DIR", "MSA_DIR"):
                window.inputs[key].blockSignals(True)
                window.inputs[key].setText(folder)
                window.inputs[key].blockSignals(False)
            for combo, name in ((window.cb_fasta, "nodes.fasta"), (window.cb_hdf5, "network.h5"),
                                (window.cb_msa, "alignment.fasta")):
                combo.blockSignals(True)
                combo.clear()
                combo.addItem(name)
                combo.blockSignals(False)
            window.line_ref.setText("WP_2")
            width_before = window.minimumSizeHint().width()
            window.run_consistency_check()
            app.processEvents()

            document = QTextDocument()
            document.setHtml(window.tip_panel.text())
            table = [frame for frame in document.rootFrame().childFrames()
                     if isinstance(frame, QTextTable)][0]

            def cell(row, column):
                found = table.cellAt(row, column)
                cursor = found.firstCursorPosition()
                cursor.setPosition(found.lastCursorPosition().position(),
                                   QTextCursor.MoveMode.KeepAnchor)
                return cursor.selectedText().replace("\\xa0", " ")

            panel = window.tip_panel
            bar = panel.verticalScrollBar()
            states = []
            for width in (width_before, 1000, width_before, 1000):
                window.resize(width, 650)
                app.processEvents()
                app.processEvents()
                states.append({
                    "width": width, "height": panel.height(), "minimum": panel.minimumHeight(),
                    "bar": bar.isVisible(), "value": bar.value(),
                    # What the viewport and the scroll range don't reach of the document.
                    "lost": panel.document().size().height() - (bar.maximum() + panel.viewport().height()),
                    "horizontal": panel.horizontalScrollBar().isVisible(),
                    "text width": panel.document().textWidth() - panel.viewport().width(),
                })

            print("@@" + json.dumps({
                "first_height": first_height,
                "preferred": panel.preferred_height(),
                "states": states,
                "rows": [[cell(row, column) for column in (1, 2, 3)] for row in range(table.rows())],
                "text": document.toPlainText().replace("\\u200b", ""),
                "width_before": width_before,
                "width_after": window.minimumSizeHint().width(),
                "long_header": long_header,
            }))
            """
        )

    def test_there_is_a_row_for_each_check(self):
        rows = self.report["rows"]
        self.assertEqual([row[0] for row in rows], ["FASTA vs HDF5", "FASTA vs MSA", "Reference ID"])
        self.assertEqual(rows[0][1:], ["3 of 3 matched", "strict subset"])
        self.assertEqual(rows[1][1:], ["2 of 3 matched", "coverage incomplete: 1 missing"])
        self.assertEqual(rows[2][1], "'WP_2' resolves to WP_2_beta")

    def test_what_the_msa_misses_follows_the_table(self):
        text = self.report["text"]
        self.assertIn("Missing examples: " + self.report["long_header"], text)
        self.assertIn(
            "Missing nodes remain plotted but are excluded from alignment-dependent analyses.", text
        )

    def test_the_report_scrolls_in_the_fixed_panel_and_does_not_widen_the_window(self):
        report = self.report
        self.assertEqual(report["width_after"], report["width_before"])
        # Laid out at its fixed height, the report does not change it: it scrolls.
        self.assertEqual(report["first_height"], report["preferred"])
        for state in report["states"]:
            with self.subTest(width=state["width"]):
                self.assertEqual(state["minimum"], 0)
                self.assertTrue(state["bar"])
                self.assertEqual(state["value"], 0)
                self.assertLessEqual(state["lost"], 1)  # scrolled to the end, all of it has been shown
                self.assertFalse(state["horizontal"])
                self.assertLessEqual(abs(state["text width"]), 1)

    def test_the_panel_has_the_same_height_each_time_the_window_comes_back_to_a_width(self):
        # (Narrower, the action buttons under it wrap onto another row, as they always did;
        # the report never changes the height.)
        heights = {}
        for state in self.report["states"]:
            heights.setdefault(state["width"], set()).add(state["height"])
        for width, seen in heights.items():
            self.assertEqual(len(seen), 1, (width, seen))
        self.assertEqual(heights[1000], {self.report["first_height"]})


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
    """Alignment Offset spans the row once the fields stack, and the aligned rows
    stay side by side down to the narrowest window, as in the desktop Config."""

    @classmethod
    def setUpClass(cls):
        cls.report = report_from(
            """
            from PySide6.QtCore import QPoint
            from PySide6.QtWidgets import QWidget
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
                    "offset_minimum": offset.minimumSizeHint().width(),
                    "rights": [right(offset), right(window.line_ref),
                               right(window.spin_min_occ)],
                })

            aligned = [window.findChild(QWidget, name) for name in
                       ("alignmentModeRow", "alignmentReferenceRow", "filterRow")]
            # The narrowest window, with the report collapsed.
            window.resize(0, 850)
            window.main_split.setSizes([sum(window.main_split.sizes()), 0])
            flush()
            print("@@" + json.dumps({
                "rows": rows,
                "full_layout_minimum": [row.layout()._wide_width() for row in aligned],
                "narrowest_widths": [row.width() for row in aligned],
                "narrowest": {
                    "at_window_minimum": window.width() == window.minimumWidth(),
                    "stacked": [bool(row.property("stacked")) for row in aligned],
                },
            }))
            """
        )

    def test_offset_spans_stacked_rows_and_keeps_its_wide_width(self):
        for row in self.report["rows"]:
            with self.subTest(width=row["width"]):
                stacked = row["width"] < 1400
                self.assertEqual(row["stacked"], stacked)
                self.assertTrue(row["label_fits"])
                if stacked:
                    self.assertEqual(len(set(row["rights"])), 1, row["rights"])
                else:
                    # Its minimum, which has room for a sign and a few digits.
                    self.assertEqual(row["offset_width"], row["offset_minimum"])

    def test_rows_stay_side_by_side_in_the_narrowest_window_without_the_report(self):
        # The fields stay side by side down to the width they need, which the
        # narrowest window has room for: 772 px with Windows' unhinted text.
        minima = self.report["full_layout_minimum"]
        self.assertEqual(len(set(minima)), 1, minima)
        for width in self.report["narrowest_widths"]:
            self.assertLessEqual(minima[0], width)
        self.assertEqual(self.report["narrowest"],
                         {"at_window_minimum": True, "stacked": [False, False, False]})


class BridgeFieldsTests(unittest.TestCase):
    """The VR client rows stack in a narrow tab, as the other rows do, and line up with them."""

    def test_client_halves_stack_without_sideways_scroll_and_keep_the_label_column(self):
        report = report_from(
            """
            from PySide6.QtCore import QPoint
            from PySide6.QtWidgets import QWidget
            window.show()

            def flush():
                for _ in range(6):
                    app.processEvents()

            def resize_panel(width):
                window.resize(width + 360, 850)
                window.main_split.setSizes([width + 4, 326])
                flush()
                delta = width - window.tabs.currentWidget().width()
                left, right = window.main_split.sizes()
                window.main_split.setSizes([left + delta, right - delta])
                flush()

            window.tabs.setCurrentIndex(1)
            scroll = window.tabs.currentWidget()
            page = scroll.widget()
            fields = page.findChild(QWidget, "vrBridgeFields")
            client = page.findChild(QWidget, "vrBridgeClient")
            endpoint = page.findChild(QWidget, "vrBridgeEndpoint")

            def left(widget):
                return widget.mapTo(page, QPoint(0, 0)).x()

            rows = []
            for width in (1400, 700, 1400):
                resize_panel(width)
                rows.append({
                    "width": width,
                    "stacked": bool(fields.property("stacked")),
                    "sideways": scroll.horizontalScrollBar().maximum(),
                    "tops": [client.y(), endpoint.y()],
                    "widths": [client.width(), endpoint.width()],
                    "field_x": [left(window.inputs[key]) for key in
                                ("VR_APP_DIR", "VR_HOST", "DISTANCE_SCALE")],
                })
            print("@@" + json.dumps(rows))
            """
        )
        for row in report:
            with self.subTest(width=row["width"]):
                self.assertEqual(row["sideways"], 0)
                if row["width"] == 1400:
                    # Wide: two equal halves side by side, as before.
                    self.assertFalse(row["stacked"])
                    self.assertEqual(row["tops"][0], row["tops"][1])
                    self.assertLessEqual(abs(row["widths"][0] - row["widths"][1]), 1)
                else:
                    # Narrow: the endpoint half goes under the client half, and
                    # its fields start in the label column like the ones above.
                    self.assertTrue(row["stacked"])
                    self.assertGreater(row["tops"][1], row["tops"][0])
                    self.assertEqual(len(set(row["field_x"])), 1, row["field_x"])


class LongFileNameTests(unittest.TestCase):
    """The file lists keep twelve characters at their narrowest, as in the desktop Config."""

    def test_long_file_names_listed_at_launch_do_not_widen_the_window(self):
        # Long, but short enough for Windows' 260-character paths in a temp folder.
        name = "A_long_network_filename_" * 5 + "network.h5"
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as project:
            # Input_Files is the project root's, as in the main program.
            folder = os.path.join(project, "Input_Files", "Networks_EValues")
            os.makedirs(folder)
            open(os.path.join(folder, name), "w").close()
            report = report_from(
                """
                # The Inputs tab lists its folders as it is built, before its
                # scroll area first measures it, and a combo box keeps that
                # first minimum. The event loop has not run yet.
                listed = [window.cb_hdf5.itemText(i) for i in range(window.cb_hdf5.count())]
                window.show()
                window.tabs.setCurrentIndex(0)
                # The narrowest window, with the report collapsed.
                window.resize(0, 850)
                window.main_split.setSizes([sum(window.main_split.sizes()), 0])
                for _ in range(6):
                    app.processEvents()
                print("@@" + json.dumps({
                    "listed": listed,
                    "widths": [window.cb_hdf5.minimumSizeHint().width(),
                               window.cb_fasta.minimumSizeHint().width()],
                    "sideways": window.tabs.currentWidget().horizontalScrollBar().maximum(),
                }))
                """,
                project_root=project,
            )
        # The test's own folder, not the checkout's (run_gui_script).
        self.assertEqual(report["listed"], ["", name])
        # As narrow as the (empty) sequence set list.
        self.assertEqual(report["widths"][0], report["widths"][1])
        self.assertEqual(report["sideways"], 0)


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
            relabel(window.inputs["PACKING_GEOMETRY"])
            select(window.inputs["PACKING_GEOMETRY"], "Circle")
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
                "geometry": data["PACKING_GEOMETRY"],
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
        self.assertEqual(self.report["geometry"], "Circle")

    def test_new_layout_cache_entry_is_found_without_its_label(self):
        self.assertTrue(self.report["new_cache"])

    def test_saved_config_entries_are_found_without_their_labels(self):
        self.assertEqual(self.report["profile_selection"], "(default)")
        self.assertFalse(self.report["profile_error"])


class NormalizationLabelTests(unittest.TestCase):
    """The Normalization Mode dropdown names each mode in words; the stored value stays.

    Alignment Length is shown, alignment_length is saved: settings files, profiles,
    caches and the MCP documents hold the values, so only the labels read as words.
    """

    VALUES = ["alignment_length", "shorter_sequence", "longer_sequence", "average_sequence"]
    WORDS = ["Alignment Length", "Shorter Sequence", "Longer Sequence", "Average Sequence"]

    @classmethod
    def setUpClass(cls):
        project = tempfile.mkdtemp()
        cls.addClassCleanup(shutil.rmtree, project, ignore_errors=True)
        cls.report = report_from(
            """
            from desktop.Tip_Panel import resolve
            select = namespace["select_combo_value"]
            value = namespace["combo_value"]
            combo = window.cb_norm_mode

            def listing():
                return [
                    [combo.itemText(i) for i in range(combo.count())],
                    [combo.itemData(i) for i in range(combo.count())],
                ]

            window._set_network_type_controls("alignment")
            select(window.cb_score_mode, "global")
            select(combo, "alignment_length")
            global_listing, current_global = listing(), combo.currentText()
            tip_rows = [label for label, _text in resolve(window.tip_db[combo]).options]
            global_facts = resolve(window.tip_db[combo]).facts
            select(window.cb_score_mode, "local")
            local_listing, current_local = listing(), combo.currentText()
            local_facts = resolve(window.tip_db[combo]).facts
            select(window.cb_score_mode, "global")

            restored = {}
            profile = dict(namespace["TAB_PROFILE_SPECS"]["inputs_outputs"]["defaults"])
            for mode in global_listing[1]:
                select(combo, "shorter_sequence")
                profile.update(ALIGNMENT_SCORE="global", NORM_MODE=mode)
                window._apply_profile_data("inputs_outputs", profile)
                restored[mode] = [
                    value(combo), combo.currentText(),
                    window._collect_tab_profile_data("inputs_outputs")["NORM_MODE"],
                    window.collect_data()["NORM_MODE"],
                    window._cache_setting_values()["normalization"],
                ]

            names = namespace["normalization_names"]()
            metrics = {}
            for mode in names:
                summary, _headings = namespace["statistics_report_text"]({
                    "blast": False, "score_mode": "global", "normalization": mode,
                    "model": "E1_RA", "fasta": "a.fasta", "nodes": 3, "stored_edges": 3,
                    "possible_edges": 3, "maximum": 1.0, "minimum": 0.0, "mean": 0.5,
                })
                metrics[mode] = summary[3]
            select(combo, "average_sequence")
            saved_ok = window.save_settings()

            from desktop.Desktop_App import install_translations
            install_translations(app, "zh_CN")
            window.update_norm_mode_options()
            chinese = listing()
            chinese_names = list(namespace["normalization_names"]().values())
            print("@@" + json.dumps({
                "global": global_listing, "current_global": current_global,
                "local": local_listing, "current_local": current_local,
                "tip_rows": tip_rows, "restored": restored,
                "global_facts": global_facts, "local_facts": local_facts,
                "names": [list(names), list(names.values())], "metrics": metrics,
                "saved_ok": saved_ok, "tip": window.tip_panel.text(),
                "chinese": chinese, "chinese_names": chinese_names,
            }))
            """,
            project_root=project,
        )
        settings_file = os.path.join(project, "opt_vr", "viewer_settings_vr.json")
        cls.saved_text = ""
        if os.path.exists(settings_file):
            with open(settings_file, encoding="utf-8") as handle:
                cls.saved_text = handle.read()

    def test_a_global_score_offers_the_four_modes_in_words(self):
        self.assertEqual(self.report["global"], [self.WORDS, self.VALUES])
        self.assertEqual(self.report["current_global"], "Alignment Length")
        self.assertFalse(any("_" in label for label in self.report["global"][0]))

    def test_a_local_score_leaves_alignment_length_out(self):
        self.assertEqual(self.report["local"], [self.WORDS[1:], self.VALUES[1:]])
        self.assertEqual(self.report["current_local"], "Longer Sequence")

    def test_each_stored_value_is_restored_collected_and_cached_as_itself(self):
        for value, words in zip(self.VALUES, self.WORDS):
            with self.subTest(value=value):
                self.assertEqual(self.report["restored"][value], [value, words, value, value, value])

    def test_saved_settings_hold_the_value_not_the_label(self):
        self.assertTrue(self.report["saved_ok"], self.report["tip"])
        self.assertEqual(json.loads(self.saved_text)["NORM_MODE"], "average_sequence")
        self.assertNotIn("Average Sequence", self.saved_text)

    def test_the_tip_and_the_statistics_report_name_the_modes_as_the_dropdown_does(self):
        self.assertEqual(self.report["tip_rows"], self.WORDS)
        # Its footer names the default by its words, and leaves it out while Alignment Length is hidden.
        self.assertIn(["Default", "Alignment Length"], self.report["global_facts"])
        self.assertIn(["Setting", "NORM_MODE"], self.report["global_facts"])
        self.assertNotIn("Default", dict(self.report["local_facts"]))
        self.assertNotIn("alignment_length", [value for _label, value in self.report["local_facts"]])
        self.assertEqual(self.report["names"], [self.VALUES, self.WORDS])
        # The report's metric line quotes the same words.
        for value, words in zip(self.VALUES, self.WORDS):
            with self.subTest(value=value):
                self.assertEqual(
                    self.report["metrics"][value],
                    f"Metric: Global Alignment Score with {words} Normalization",
                )

    def test_simplified_chinese_shows_the_reviewed_wording_of_the_report(self):
        labels, values = self.report["chinese"]
        self.assertEqual(values, self.VALUES)
        # The statistics report's translations are the dropdown's.
        self.assertEqual(labels, self.report["chinese_names"])
        for words, chinese in zip(self.WORDS, labels):
            with self.subTest(words=words):
                self.assertNotEqual(chinese, words)
                self.assertNotIn("_", chinese)
                self.assertTrue(any("一" <= character <= "鿿" for character in chinese))


class ComboPopupTests(unittest.TestCase):
    """An open dropdown list scrolls by the wheel, scroll bar and keys, not by the mouse.

    The desktop Config's tests (tests/test_combo_popup.py) cover the behaviour;
    this copy only has to keep every combo box on the shared base class, and
    its own classes steady.
    """

    @classmethod
    def setUpClass(cls):
        cls.report = report_from(
            """
            import json
            from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
            from PySide6.QtGui import QMouseEvent
            from PySide6.QtWidgets import QApplication, QComboBox, QVBoxLayout, QWidget
            from desktop.Desktop_App import SteadyPopupComboBox

            def flush():
                for _ in range(4):
                    app.processEvents()

            def rest_on_the_partly_visible_row(combo):
                # A list cut off by 12 px, as a screen edge cuts a popup.
                combo.addItems(["Entry %d" % number for number in range(60)])
                host = QWidget()
                QVBoxLayout(host).addWidget(combo)
                host.resize(300, 120)
                host.show()
                flush()
                combo.showPopup()
                flush()
                view = combo.view()
                container = view.window()
                container.resize(container.width(), container.height() - 12)
                flush()
                viewport = view.viewport()
                y = viewport.height() - 3
                row = view.indexAt(QPoint(20, y)).row()
                cut_off = not viewport.rect().contains(
                    view.visualRect(view.model().index(row, 0))
                )
                for step in range(6):
                    local = QPoint(20 + step, y - step % 3)
                    QApplication.sendEvent(viewport, QMouseEvent(
                        QEvent.Type.MouseMove, QPointF(local),
                        QPointF(viewport.mapToGlobal(local)), Qt.MouseButton.NoButton,
                        Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
                    ))
                    flush()
                report = {
                    "cut_off": cut_off,
                    "scrolled": view.verticalScrollBar().value(),
                    "current": view.currentIndex().row(),
                    "row": row,
                }
                combo.hidePopup()
                host.close()
                return report

            combos = window.findChildren(QComboBox)
            print("@@" + json.dumps({
                "combos": len(combos),
                "plain": [
                    type(combo).__name__ for combo in combos
                    if not isinstance(combo, SteadyPopupComboBox)
                ],
                "no_scroll": rest_on_the_partly_visible_row(namespace["NoScrollComboBox"]()),
                "dynamic": rest_on_the_partly_visible_row(
                    namespace["DynamicComboBox"](lambda: None)
                ),
            }))
            """
        )

    def test_every_combo_box_of_the_window_has_a_steady_list(self):
        self.assertGreater(self.report["combos"], 5)
        self.assertEqual(self.report["plain"], [])

    def test_resting_the_pointer_on_the_partly_visible_row_does_not_scroll_the_list(self):
        for name in ("no_scroll", "dynamic"):
            with self.subTest(name):
                report = self.report[name]
                self.assertTrue(report["cut_off"])
                self.assertEqual(report["scrolled"], 0)
                self.assertEqual(report["current"], report["row"])


class TextSizedControlsTests(unittest.TestCase):
    """Labels share one column sized by the longest, and switches fit their text,
    as in the desktop Config. The VR client block joins both. The statistics
    report's hint wraps to the report's width."""

    @classmethod
    def setUpClass(cls):
        cls.report = report_from(
            """
            from PySide6.QtCore import QPoint
            from PySide6.QtGui import QFont, QFontMetrics
            from PySide6.QtWidgets import QTextEdit
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
            report_box = window.stat_display
            hint = report_box.findChild(namespace["QLabel"], "wrappedPlaceholder")
            print("@@" + json.dumps({
                "column": window.label_column_width,
                "column_labels": [window.labels[key].width() for key in client_keys],
                "client_fields": [x(window.inputs[key]) for key in client_keys],
                "visual_field": x(window.inputs["NODE_SIZE"].parentWidget()),
                "switches": switches,
                "statistics_hint": {
                    "shown": hint.isVisible(),
                    "text": hint.text() == report_box.placeholderText() != "",
                    "qt_placeholder": QTextEdit.placeholderText(report_box),
                    "fonts": [hint.font().family(), report_box.viewport().font().family()],
                    "one_line": QFontMetrics(hint.font()).horizontalAdvance(hint.text()),
                    "size": [hint.width(), hint.height()],
                    "wrapped_height": hint.heightForWidth(hint.width()),
                    "inside": report_box.viewport().rect().contains(hint.geometry()),
                },
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

    def test_statistics_hint_wraps_inside_the_report(self):
        """Qt shows only the first line of a QTextEdit placeholder, which the
        report at the default size cuts off; the hint wraps instead, in the
        report's font."""
        hint = self.report["statistics_hint"]
        width, height = hint["size"]
        self.assertTrue(hint["shown"])
        self.assertTrue(hint["text"])
        self.assertEqual(hint["qt_placeholder"], "")
        self.assertEqual(hint["fonts"][0], hint["fonts"][1])
        self.assertTrue(hint["inside"])
        self.assertGreater(hint["one_line"], width)
        self.assertLessEqual(hint["wrapped_height"], height)

    def test_fixed_width_labels_get_the_width_they_ask_for(self):
        """A label given a fixed width gets its size hint, not its text's advance.
        Linux font hinting can draw a text past its advance, which cut a pixel
        off "Min % Drop Threshold:" there. A right contents margin makes every
        label need 1 px more than its text's advance, on every platform."""
        rows = report_from(
            """
            from PySide6.QtWidgets import QLabel

            class OverhangLabel(QLabel):
                def __init__(self, *args, **kwargs):
                    super().__init__(*args, **kwargs)
                    self.setContentsMargins(0, 0, 1, 0)

            # The window was built on import; build another whose labels overhang.
            gui = namespace["ConfigGUI"]
            with mock.patch.dict(gui.__init__.__globals__, {"QLabel": OverhangLabel}):
                overhang = gui()
            overhang.show()
            rows = []
            for width in (1600, 700):
                overhang.resize(width + 360, 850)
                for _ in range(6):
                    app.processEvents()
                rows += [{"width": width, "text": label.text(), "fixed": label.width(),
                          "hint": label.sizeHint().width(),
                          "drop": label is overhang.labels["PERCENTAGE_DROP_THRESHOLD"]}
                         for label in overhang.findChildren(OverhangLabel)
                         if label.text() and label.minimumWidth() == label.maximumWidth()]
            overhang.close()
            print("@@" + json.dumps(rows))
            """
        )
        self.assertEqual(sum(row["drop"] for row in rows), 2)
        for row in rows:
            with self.subTest(width=row["width"], label=row["text"]):
                # QLabel's size hint is at least its minimum width, so this
                # fails only when the fixed width is narrower than the text.
                self.assertGreaterEqual(row["fixed"], row["hint"])


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


class LanguageFollowTests(unittest.TestCase):
    """An open VR Config takes a language another window saved when it is next activated."""

    @classmethod
    def setUpClass(cls):
        cls.report = report_from(
            """
            from PySide6.QtWidgets import QWidget
            from desktop import Desktop_App
            from desktop.Desktop_App import installed_language
            from utilities.App_Settings import save_app_setting

            def flush():
                for _ in range(6):
                    app.processEvents()

            window.show()
            flush()
            window.inputs["NODE_SIZE"].setValue(window.inputs["NODE_SIZE"].value() + 1)  # unsaved
            values = window.language_carry_over()["values"]
            elsewhere = QWidget()
            elsewhere.show()
            flush()
            save_app_setting("LANGUAGE", "zh_CN")  # as Config or Tools saves it
            flush()
            waited = window.isVisible() and installed_language() is None
            window.activateWindow()
            flush()
            replacement = Desktop_App._redrawn_windows[-1] if Desktop_App._redrawn_windows else window
            installed = Desktop_App._installed_translations
            print("@@" + json.dumps({
                "waited": waited,
                "replaced": replacement is not window,
                "language": installed_language(),
                "extra_catalogs": [name for _, name in installed.extra_catalogs] if installed else [],
                "title": replacement.windowTitle(),
                "setting": replacement.language_selector.setting(),
                "values_kept": replacement.language_carry_over()["values"] == values,
            }, default=str))
            elsewhere.close()
            window = replacement
            """
        )

    def test_it_waits_for_its_activation_and_then_redraws_in_the_saved_language(self):
        report = self.report
        self.assertTrue(report["waited"], "saving alone changes nothing")
        self.assertTrue(report["replaced"])
        self.assertEqual(report["language"], "zh_CN")
        self.assertEqual(report["setting"], "zh_CN")
        self.assertTrue(report["values_kept"])

    def test_the_redraw_brings_opt_vr_s_own_catalog(self):
        self.assertEqual(self.report["extra_catalogs"], ["emapssn_vr"])
        self.assertEqual(self.report["title"], "EMAP-SSN VR 配置")


class ThemeColorTests(unittest.TestCase):
    """VR Config keeps a theme colour of its own, chosen as in the desktop Config."""

    @classmethod
    def setUpClass(cls):
        folder = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        cls.addClassCleanup(folder.cleanup)
        with open(os.path.join(folder.name, "app_settings.json"), "w", encoding="utf-8") as handle:
            json.dump({"VR_CONFIG_THEME_COLOR": "teal", "CONFIG_THEME_COLOR": "red"}, handle)
        cls.report = report_from(
            """
            from PySide6.QtCore import QPoint
            from PySide6.QtWidgets import QFrame
            from desktop import Desktop_App
            from desktop.Studio_Theme import theme_color, theme_tokens
            from utilities.App_Settings import read_app_settings

            def section_lines(shown):
                lines = [frame for frame in shown.findChildren(QFrame)
                         if frame.property("role") == "separator" and frame.isVisible()]
                images = [line.grab().toImage() for line in lines]
                return {"count": len(lines), "heights": sorted({line.height() for line in lines}),
                        "colours": sorted({image.pixelColor(image.width() // 2, y).name()
                                           for image in images for y in range(image.height())})}

            window.show()
            for _ in range(4):
                app.processEvents()
            switch, language = window.theme_switch, window.language_selector
            started = {"window": theme_color(), "switch": switch.color(), "setting": switch.theme_setting}
            lines_before = section_lines(window)
            after_language = (switch.mapTo(window, QPoint(0, 0)).x()
                              > language.mapTo(window, QPoint(language.width(), 0)).x())
            values = window.language_carry_over()["values"]
            switch.color_chosen.emit("orange")
            for _ in range(4):
                app.processEvents()
            replacement = Desktop_App._redrawn_windows[-1]
            print("@@" + json.dumps({
                "started": started,
                "after_language": after_language,
                "saved": read_app_settings(),
                "color": theme_color(),
                "replacement": replacement.theme_switch.color(),
                "replaced": replacement is not window and not window.isVisible(),
                "values_kept": replacement.language_carry_over()["values"] == values,
                "lines_before": lines_before,
                "lines_after": section_lines(replacement),
                "line_shades": {name: theme_tokens(name)["separator"] for name in ("teal", "orange")},
                "border": theme_tokens("teal")["border"],
                "thickness": theme_tokens("teal")["separator_thickness"],
            }, default=str))
            window = replacement
            """,
            project_root=folder.name,
        )

    def test_the_window_starts_in_its_own_colour_not_configs(self):
        self.assertEqual(self.report["started"],
                         {"window": "teal", "switch": "teal", "setting": "VR_CONFIG_THEME_COLOR"})

    def test_the_circle_sits_after_the_language_dropdown(self):
        self.assertTrue(self.report["after_language"])

    def test_choosing_a_colour_saves_it_and_redraws_keeping_the_values(self):
        report = self.report
        self.assertEqual(report["saved"], {"VR_CONFIG_THEME_COLOR": "orange", "CONFIG_THEME_COLOR": "red"})
        self.assertEqual((report["color"], report["replacement"]), ("orange", "orange"))
        self.assertTrue(report["replaced"])
        self.assertTrue(report["values_kept"])

    def test_the_section_lines_take_the_colour(self):
        # A light shade of the window's colour, not the cards' grey hairline, after a redraw too.
        report, shades = self.report, self.report["line_shades"]
        self.assertNotEqual(shades["teal"], report["border"])
        self.assertGreater(report["lines_before"]["count"], 0)
        self.assertEqual(report["lines_before"]["colours"], [shades["teal"]])
        self.assertGreater(report["lines_after"]["count"], 0)
        self.assertEqual(report["lines_after"]["colours"], [shades["orange"]])
        # As thick as the theme's lines, the same in every window.
        for lines in (report["lines_before"], report["lines_after"]):
            self.assertEqual(lines["heights"], [report["thickness"]])


class RunTimeTextTests(unittest.TestCase):
    """Text the window shows after it opens, under the pseudo-language, as for the desktop Config.

    Tips, VR's own tooltips and client notes, the save message, profile
    errors and the two reports. outside_the_catalog
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

            from desktop.Tip_Panel import Tip

            for key, tip in window.tip_db_keys.items():
                # A tip the panel lays out holds several texts, each translated by itself.
                for text in (tip.texts() if isinstance(tip, Tip) else [tip]):
                    checked.append("tip " + key)
                    if not is_pseudo_translated(text):
                        left["tip " + key] = text
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
                finish_statistics(window)
            check("statistics report", window.stat_display.toPlainText())
            check("statistics tip", plain(window.tip_panel.text()))
            print("@@" + json.dumps({{"checked": checked, "left": left}}))
            """.format(foreign=foreign),
            pseudo_translation=True,
        )

    def test_every_text_shown_later_comes_from_a_catalog(self):
        checked = self.report["checked"]
        self.assertGreater(sum(name.startswith("tip ") for name in checked), 50)
        for name in ("tooltip VR_APP_DIR", "note foreign", "save", "consistency report",
                     "statistics report"):
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
        os.makedirs(os.path.join(main, "de"))  # Each language in a folder of its own.
        with open(os.path.join(main, "de", "emapssn_de.ts"), "w", encoding="utf-8") as handle:
            handle.write(template.format(language=' language="de"'))
        lines = []
        options = dict(report=lines.append, source_dir=source, languages_dir=own, main_languages_dir=main)
        self.assertEqual(self.updater.update_vr_catalogs(**options), 0, "\n".join(lines))
        self.assertEqual(sorted(os.listdir(own)), ["de", "emapssn_vr.ts"])
        self.assertEqual(sorted(os.listdir(os.path.join(own, "de"))), ["emapssn_vr_de.qm", "emapssn_vr_de.ts"])
        self.assertEqual(
            [message.source for message in read_catalog(os.path.join(own, "de", "emapssn_vr_de.ts"))], ["Own sentence"]
        )
        self.assertEqual(self.updater.update_vr_catalogs(check=True, **options), 0, "\n".join(lines))
        os.remove(os.path.join(own, "de", "emapssn_vr_de.ts"))
        lines.clear()
        self.assertEqual(self.updater.update_vr_catalogs(check=True, **options), 1)
        self.assertTrue(any(line.startswith("de/emapssn_vr_de.ts is missing") for line in lines), lines)

    def test_it_lists_no_text_the_main_catalog_lists(self):
        from utilities.Localization import read_catalog

        updater = self.updater
        main = {message.key for message in read_catalog(updater.MAIN_LANGUAGES_DIR / "emapssn.ts")}
        own = [message.key for message in read_catalog(updater.LANGUAGES_DIR / f"{updater.CATALOG_NAME}.ts")]
        self.assertGreater(len(own), 20)
        self.assertEqual([key for key in own if key in main], [])

    def test_the_bundled_chinese_font_draws_what_the_chinese_translations_add(self):
        from fontTools.ttLib import TTFont

        from desktop.Desktop_App import DESKTOP_FONT_DIR, LANGUAGE_FONTS
        from utilities.Localization import read_catalog

        # A translation keeps the English's emoji and symbols, which the
        # system's fonts draw in every language; the rest is the font's.
        catalog = self.updater.LANGUAGES_DIR / "zh_CN" / f"{self.updater.CATALOG_NAME}_zh_CN.ts"
        added = {
            char
            for message in read_catalog(catalog)
            for translation in message.translations
            for char in translation
            if not char.isspace() and char not in message.source
        }
        self.assertGreater(len(added), 20, "the Chinese catalog holds translations")
        for face in LANGUAGE_FONTS["zh_CN"].files:
            cmap = TTFont(DESKTOP_FONT_DIR / face).getBestCmap()
            self.assertNotIn(ord("龘"), cmap, "the check can fail: 龘 is not in GB2312")
            self.assertEqual(sorted(char for char in added if ord(char) not in cmap), [], face)

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

    def test_relative_directories_resolve_against_the_project_root(self):
        """A relative directory is the parent checkout's, as in the main program.

        Only the VR client build stays in the submodule. This drives a
        settings file of its own rather than whatever the user last saved:
        pointing the VR front end at an external data store is a supported
        configuration - an absolute path is honoured as written, and the next
        test pins that - so reading the live file made this assert the user's
        setup instead of the resolution rule.
        """
        relative = {
            "CACHE_FILE_DIR": "Cache_Files_VR",
            "SAVED_LAYOUT_DIR": r"$cache_file$\Saved_Layouts",
            "INPUT_FILE_DIR": "Input_Files",
            "ANALYSIS_RESULT_DIR": "Analysis_Results",
            "NODE_FASTA_FILE": r"$input_file$\Sequence_Sets\set.fasta",
            "VR_APP_DIR": "player",
        }
        values = self._settings_from(relative)
        expected = {
            "CACHE_FILE_DIR": (_bootstrap_vr.PROJECT_ROOT, "Cache_Files_VR"),
            "SAVED_LAYOUT_DIR": (_bootstrap_vr.PROJECT_ROOT, "Cache_Files_VR", "Saved_Layouts"),
            "INPUT_FILE_DIR": (_bootstrap_vr.PROJECT_ROOT, "Input_Files"),
            "ANALYSIS_RESULT_DIR": (_bootstrap_vr.PROJECT_ROOT, "Analysis_Results"),
            "NODE_FASTA_FILE": (_bootstrap_vr.PROJECT_ROOT, "Input_Files", "Sequence_Sets", "set.fasta"),
            "VR_APP_DIR": (_bootstrap_vr.OPT_VR_DIR, "player"),
        }
        for key, parts in expected.items():
            with self.subTest(key=key):
                self.assertEqual(os.path.normcase(os.path.normpath(values[key])),
                                 os.path.normcase(os.path.join(*parts)))

    def test_default_folders_are_the_main_programs_except_the_cache(self):
        """Every default folder resolves as the main program resolves it,
        against the same root, except the cache folder, Cache_Files_VR, which
        everything under $cache_file$ follows."""
        from desktop.Viewer_State import DEFAULTS, DIRECTORY_PROFILE_DEFAULTS, normalize_viewer_paths

        values = self._settings_from({})
        main = normalize_viewer_paths(
            {**DEFAULTS, "CACHE_FILE_DIR": "Cache_Files_VR",
             # Placeholders: the main program requires these two inputs.
             "NODE_FASTA_FILE": "set.fasta", "INPUT_HDF5": "network.h5"},
            _bootstrap_vr.PROJECT_ROOT, require_cache=False,
        )
        for key in (*DIRECTORY_PROFILE_DEFAULTS, "SAVED_CONFIG_DIR"):
            with self.subTest(key=key):
                self.assertEqual(os.path.normcase(os.path.normpath(values[key])),
                                 os.path.normcase(os.path.normpath(main[key])))
        root = _bootstrap_vr.PROJECT_ROOT
        for key, parts in {
            "CACHE_FILE_DIR": ("Cache_Files_VR",),
            "INPUT_FILE_DIR": ("Input_Files",),
            "EMBED_DIR": ("Embeddings",),
            "SAVED_CONFIG_DIR": ("Cache_Files_VR", "Saved_Config"),
            "HISTORY_DIR": ("Cache_Files_VR", "History"),
            "CLUSTER_ALIGNMENT_DIR": ("Analysis_Results", "Cluster_Alignments"),
        }.items():
            with self.subTest(key=key):
                self.assertEqual(os.path.normcase(os.path.normpath(values[key])),
                                 os.path.normcase(os.path.join(root, *parts)))
        self.assertEqual(os.path.normcase(values["VR_APP_DIR"]),
                         os.path.normcase(os.path.join(_bootstrap_vr.OPT_VR_DIR, "player")))

    def test_absolute_directories_are_left_alone(self):
        """An external data store is a supported choice, not a mistake."""
        import Settings_VR

        external = os.path.join(tempfile.gettempdir(), "SSN_Viewer_Data")
        values = self._settings_from({"INPUT_FILE_DIR": external})
        self.assertEqual(os.path.normpath(values["INPUT_FILE_DIR"]),
                         os.path.normpath(external))

    def test_the_embedding_alias_resolves_to_the_embedding_directory(self):
        """$embedding$ is the fourth reusable root: a folder or a file written
        under it resolves under EMBED_DIR, with no list of aliases of VR's own."""
        import Settings_VR
        from desktop.Viewer_State import ALIASES

        self.assertEqual(Settings_VR.ALIASES["$embedding$"], "EMBED_DIR")
        self.assertIs(Settings_VR.ALIASES, ALIASES)
        root = _bootstrap_vr.PROJECT_ROOT
        norm = lambda path: os.path.normcase(os.path.normpath(path))  # noqa: E731
        values = self._settings_from({
            "EMBED_DIR": "my_embeddings",
            "EMBED_FILE": "$embedding$\\set_[model]_embeddings.h5",
            "HDF5_DIR": "$embedding$/sub",
        })
        folder = os.path.join(root, "my_embeddings")
        self.assertEqual(norm(values["EMBED_DIR"]), norm(folder))
        self.assertEqual(norm(values["EMBED_FILE"]),
                         norm(os.path.join(folder, "set_[model]_embeddings.h5")))
        self.assertEqual(norm(values["HDF5_DIR"]), norm(os.path.join(folder, "sub")))
        # The command-side resolver reads the same table.
        self.assertEqual(
            norm(Settings_VR.resolve_directory_path(
                "$embedding$\\sub", {"EMBED_DIR": folder})),
            norm(os.path.join(folder, "sub")),
        )
        self.assertEqual(
            norm(Settings_VR.resolve_directory_path("$embedding$/sub")),
            norm(os.path.join(Settings_VR.EMBED_DIR, "sub")),
        )
        self.assertEqual(Settings_VR.resolve_directory_path("$embedding$suffix/sub"),
                         "$embedding$suffix/sub")

    def test_old_settings_holding_the_default_embedding_directory_still_load(self):
        root = _bootstrap_vr.PROJECT_ROOT
        norm = lambda path: os.path.normcase(os.path.normpath(path))  # noqa: E731
        values = self._settings_from({"EMBED_DIR": "Embeddings"})
        self.assertEqual(norm(values["EMBED_DIR"]), norm(os.path.join(root, "Embeddings")))
        # A folder an old file placed under the input root resolves under it.
        values = self._settings_from({
            "INPUT_FILE_DIR": "inputs", "EMBED_DIR": "$input_file$/Embeddings",
        })
        self.assertEqual(norm(values["EMBED_DIR"]),
                         norm(os.path.join(root, "inputs", "Embeddings")))
        # Without the key, the default is the same folder.
        values = self._settings_from({})
        self.assertEqual(norm(values["EMBED_DIR"]), norm(os.path.join(root, "Embeddings")))

    def test_a_root_that_names_itself_is_refused_for_every_alias(self):
        from desktop.Viewer_State import ALIASES

        for alias, key in ALIASES.items():
            with self.subTest(alias=alias):
                with self.assertRaisesRegex(ValueError, "Circular directory alias"):
                    self._settings_from({key: alias + "/folder"})

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
            player = os.path.join(str(namespace["OPT_VR_DIR"]), "player")
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
    fresh window. So are its Save & Run pause tests, and its tests of the
    next look for caches published after the check.
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

            # Save & Run's pause after a click: a double click launches once.
            import time
            from types import SimpleNamespace
            from PySide6.QtCore import Qt
            from PySide6.QtTest import QTest

            gui, work, shown = open_window()
            select(gui, "a.fasta")
            finish(workers[-1])
            gui.show()
            button = gui.btn_save_run
            launches = []
            gui.save_and_run = lambda: launches.append(1)
            pause = window_globals["CONFIG_RUN_BUTTON_PAUSE_MS"]
            window_globals["CONFIG_RUN_BUTTON_PAUSE_MS"] = 150
            started = time.monotonic()
            QTest.mouseClick(button, Qt.MouseButton.LeftButton)
            QTest.mouseClick(button, Qt.MouseButton.LeftButton)
            double_click = {"launches": len(launches), "enabled": button.isEnabled()}
            while not button.isEnabled() and time.monotonic() < started + 5.0:
                QTest.qWait(10)
            double_click["back"] = button.isEnabled()
            double_click["seconds"] = time.monotonic() - started
            QTest.mouseClick(button, Qt.MouseButton.LeftButton)
            double_click["launches_after"] = len(launches)
            window_globals["CONFIG_RUN_BUTTON_PAUSE_MS"] = pause
            close(gui)

            # A check that ends in the pause neither ends it nor outlasts it.
            # The pause ends when the script says, not on a clock.
            gui, work, shown = open_window()
            select(gui, "a.fasta")
            finish(workers[-1])
            button = gui.btn_save_run
            gui.save_and_run = lambda: None
            timers = []
            real_timer = window_globals["QTimer"]
            window_globals["QTimer"] = SimpleNamespace(singleShot=lambda *args: timers.append(args))
            button.click()
            check = {"timer": [timers[0][0], timers[0][1] is button],
                     "in_pause": button.isEnabled()}
            select(gui, "b.fasta")
            finish(workers[-1])
            check["found"] = gui.lbl_cache_tracker.text() == shown["b.fasta"]
            check["found_in_pause"] = button.isEnabled()
            timers[-1][2]()
            check["after_pause"] = button.isEnabled()
            button.click()
            select(gui, "")
            check["cleared"] = gui.lbl_cache_tracker.text()
            timers[-1][2]()
            check["cleared_after_pause"] = button.isEnabled()
            window_globals["QTimer"] = real_timer
            close(gui)
            report["save_run_pause"] = {"pause": pause, "double_click": double_click, "check": check}

            # A cache published after the check shows at the next look.
            import shutil

            def generate(gui, work, fasta_name, folder, cache_name="version_00.h5"):
                # As the Layout Generator publishes one: the manifest, then the
                # .h5 file (none for cache_name=None).
                if not (folder / cache_manifest.MANIFEST_FILENAME).exists():
                    sequence = cache_manifest.fingerprint_file(work / fasta_name)
                    network = cache_manifest.fingerprint_file(work / "network.h5")
                    compatibility = cache_manifest.build_compatibility(
                        sequence["sha256"], network["sha256"], "blast",
                        **gui._cache_setting_values(),
                    )
                    cache_manifest.write_manifest_atomic(
                        folder, cache_manifest.build_manifest(sequence, network, compatibility)
                    )
                if cache_name:
                    (folder / cache_name).write_bytes(b"")

            def items(gui):
                combo = gui.cb_cache_file
                return [combo.itemText(index) for index in range(combo.count())]

            def needs_computing(gui, work, fasta_name):
                # The FASTA's layout folder is gone; returns the folder the window targets.
                shutil.rmtree(work / "layouts" / (Path(fasta_name).stem + "_layout"))
                select(gui, fasta_name)
                finish(workers[-1])
                return Path(gui.current_cache_folder)

            recheck = {}
            gui, work, shown = open_window()
            target = needs_computing(gui, work, "a.fasta")
            case = {"folder": target.name, "before": gui.lbl_cache_tracker.text(), "items_before": items(gui)}
            gui._recheck_saved_caches()
            case["nothing_yet"] = gui.lbl_cache_tracker.text()
            generate(gui, work, "a.fasta", target)
            gui._recheck_saved_caches()
            case.update(after=gui.lbl_cache_tracker.text(), items=items(gui),
                        selected=gui.cb_cache_file.currentText(), hashed=len(workers))
            recheck["generated"] = case
            close(gui)

            # The manifest is published before the cache; a .partial file is no cache yet.
            gui, work, shown = open_window()
            target = needs_computing(gui, work, "a.fasta")
            generate(gui, work, "a.fasta", target, None)
            gui._recheck_saved_caches()
            case = {"folder": target.name, "manifest_only": [gui.lbl_cache_tracker.text(), items(gui)]}
            (target / ".version_00.h5.x1y2.partial").write_bytes(b"")
            with mock.patch.object(gui, "_request_cache_discovery") as search:
                gui._recheck_saved_caches()
            case["partial_searched"] = search.called
            generate(gui, work, "a.fasta", target)
            gui._recheck_saved_caches()
            case["selected"] = gui.cb_cache_file.currentText()
            recheck["manifest_first"] = case
            close(gui)

            # Generated into the compatible folder while a new cache was being named.
            gui, work, shown = open_window()
            select(gui, "b.fasta")
            finish(workers[-1])
            case = {"items_before": items(gui)}
            gui.line_new_cache.setText("mine.h5")
            generate(gui, work, "b.fasta", work / "layouts" / "b_layout", "mine.h5")
            gui._recheck_saved_caches()
            case.update(items=items(gui), selected=gui.cb_cache_file.currentText(),
                        name=gui.line_new_cache.text())
            recheck["into_compatible"] = case
            close(gui)

            # A look that finds no new cache keeps the choice.
            gui, work, shown = open_window()
            folder = work / "layouts" / "b_layout"
            for age, name in enumerate(("newer.h5", "older.h5")):
                (folder / name).write_bytes(b"")
                os.utime(folder / name, (1_700_000_000 - age, 1_700_000_000 - age))
            select(gui, "b.fasta")
            finish(workers[-1])
            combo = gui.cb_cache_file
            case = {"items_before": items(gui)}
            combo.setCurrentIndex(combo.findText("older.h5"))
            generate(gui, work, "a.fasta", work / "layouts" / "other_inputs_layout", None)
            with mock.patch.object(combo, "clear", wraps=combo.clear) as clear:
                gui._recheck_saved_caches()
            case["unrelated"] = {"rebuilt": clear.called, "selected": combo.currentText()}
            (folder / "newer.h5").unlink()
            gui._recheck_saved_caches()
            case["removed"] = {"items": items(gui), "selected": combo.currentText()}
            combo.setCurrentIndex(combo.count() - 1)
            gui._toggle_new_cache_input()
            gui.line_new_cache.setText("draft.h5")
            (folder / "older.h5").unlink()
            gui._recheck_saved_caches()
            case["naming"] = {"items": items(gui), "name": gui.line_new_cache.text()}
            recheck["no_new_cache"] = case
            close(gui)

            # A second compatible folder appears, then goes.
            gui, work, shown = open_window()
            select(gui, "b.fasta")
            finish(workers[-1])
            folder = work / "layouts" / "b_layout"
            shutil.copytree(folder, folder.with_name("b_layout_copy"))
            gui._recheck_saved_caches()
            case = {"copied": [gui.lbl_cache_tracker.text(), gui._cache_launch_allowed]}
            shutil.rmtree(folder.with_name("b_layout_copy"))
            gui._recheck_saved_caches()
            case.update(expected=shown["b.fasta"], removed=gui.lbl_cache_tracker.text())
            recheck["second_folder"] = case
            close(gui)

            # Published during the search: what it looked at was read before it ran.
            gui, work, shown = open_window()
            target = needs_computing(gui, work, "a.fasta")
            find_matching = cache_manifest.find_matching_manifest_folders

            def search_then_generate(saved_layout_dir, compatibility):
                matches = find_matching(saved_layout_dir, compatibility)
                generate(gui, work, "a.fasta", target)
                return matches

            (target.parent / "unrelated").mkdir()
            with mock.patch.object(
                cache_manifest, "find_matching_manifest_folders", side_effect=search_then_generate
            ):
                gui._recheck_saved_caches()
            case = {"missed": gui.lbl_cache_tracker.text().endswith("[Needs Computing]")}
            gui._recheck_saved_caches()
            case["next_look"] = gui.cb_cache_file.currentText()
            recheck["during_search"] = case
            close(gui)

            # Opening the cache list looks again.
            gui, work, shown = open_window()
            target = needs_computing(gui, work, "a.fasta")
            generate(gui, work, "a.fasta", target)
            gui.show()
            gui.cb_cache_file.showPopup()
            gui.cb_cache_file.hidePopup()
            recheck["opened_list"] = {"folder": target.name, "tracker": gui.lbl_cache_tracker.text(),
                                      "selected": gui.cb_cache_file.currentText()}
            close(gui)

            # A shown window looks again by itself; a hidden one does not.
            gui, work, shown = open_window()
            timer = gui._cache_recheck_timer
            case = {"constant": window_globals["CONFIG_CACHE_RECHECK_MS"],
                    "timer": [timer.isActive(), timer.interval()]}
            target = needs_computing(gui, work, "a.fasta")
            generate(gui, work, "a.fasta", target)
            gui._recheck_saved_caches_while_shown()
            case["hidden"] = gui.lbl_cache_tracker.text().endswith("[Needs Computing]")
            window_globals["CONFIG_CACHE_RECHECK_MS"] = 20
            timer.setInterval(20)
            gui.show()
            deadline = time.monotonic() + 5.0
            while gui.lbl_cache_tracker.text().endswith("[Needs Computing]") and time.monotonic() < deadline:
                QTest.qWait(10)
            window_globals["CONFIG_CACHE_RECHECK_MS"] = case["constant"]
            case.update(folder=target.name, shown=gui.lbl_cache_tracker.text())
            recheck["by_itself"] = case
            close(gui)

            # A slow layout folder is looked at less often: a 200 ms look, then a 1 ms one.
            gui, work, shown = open_window()
            gui.show()
            clock = iter([10.0, 10.2, 20.0, 20.001])
            real_time = window_globals["time"]
            window_globals["time"] = SimpleNamespace(perf_counter=lambda: next(clock))
            intervals = []
            with mock.patch.object(gui, "_recheck_saved_caches"):
                for _ in range(2):
                    gui._recheck_saved_caches_while_shown()
                    intervals.append(gui._cache_recheck_timer.interval())
            window_globals["time"] = real_time
            recheck["slow_folder"] = intervals
            close(gui)

            # A folder removed between the search and listing its caches.
            gui, work, shown = open_window()
            select(gui, "b.fasta")
            finish(workers[-1])
            looked = gui._saved_cache_look is not None
            with mock.patch.object(
                cache_manifest, "find_matching_manifest_folders",
                return_value=[{"folder": str(work / "layouts" / "removed_layout"), "manifest": {}}],
            ):
                gui.update_live_validators()  # b.fasta's hashes are cached
                case = {
                    "looked": looked,
                    "error": gui.lbl_cache_tracker.text().startswith("Cache compatibility error: "),
                    "look": gui._saved_cache_look,
                }
                # Nor does it escape the result of hashing, which nothing else guards.
                select(gui, "a.fasta")
                finish(workers[-1])
                case["after_hashing"] = gui.lbl_cache_tracker.text().startswith("Cache compatibility error: ")
            recheck["folder_removed"] = case
            close(gui)
            report["recheck"] = recheck
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

    def test_a_double_click_on_save_and_run_launches_once_and_the_button_comes_back(self):
        case = self.report["save_run_pause"]
        self.assertEqual(case["pause"], 1000)
        click = case["double_click"]
        self.assertEqual((click["launches"], click["enabled"]), (1, False))
        self.assertTrue(click["back"])
        self.assertGreaterEqual(click["seconds"], 0.14)
        self.assertEqual(click["launches_after"], 2)

    def test_a_cache_check_ending_in_the_pause_neither_ends_it_nor_outlasts_it(self):
        self.assertEqual(self.report["save_run_pause"]["check"], {
            "timer": [1000, True],
            "in_pause": False,
            "found": True,
            "found_in_pause": False,
            "after_pause": True,
            "cleared": "Target Cache: Missing FASTA or HDF5",
            "cleared_after_pause": False,
        })

    def test_a_cache_generated_after_the_check_shows_at_the_next_look(self):
        case = self.report["recheck"]["generated"]
        needs_computing = f"Target Folder: {case['folder']} [Needs Computing]"
        self.assertEqual(case["before"], needs_computing)
        self.assertEqual(case["items_before"], ["(New Layout Cache)"])
        self.assertEqual(case["nothing_yet"], needs_computing)
        self.assertEqual(case["after"], f"Compatible Folder: {case['folder']}")
        self.assertEqual(case["items"], ["version_00.h5", "(New Layout Cache)"])
        self.assertEqual(case["selected"], "version_00.h5")
        self.assertEqual(case["hashed"], 1, "the inputs were not hashed again")

    def test_a_manifest_published_before_its_cache_shows_the_folder_then_the_cache(self):
        case = self.report["recheck"]["manifest_first"]
        self.assertEqual(
            case["manifest_only"], [f"Compatible Folder: {case['folder']}", ["(New Layout Cache)"]]
        )
        self.assertFalse(case["partial_searched"])
        self.assertEqual(case["selected"], "version_00.h5")

    def test_a_cache_generated_into_the_compatible_folder_is_selected(self):
        self.assertEqual(self.report["recheck"]["into_compatible"], {
            "items_before": ["(New Layout Cache)"],
            "items": ["mine.h5", "(New Layout Cache)"],
            "selected": "mine.h5",
            "name": "",
        })

    def test_a_look_that_finds_no_new_cache_keeps_the_choice(self):
        self.assertEqual(self.report["recheck"]["no_new_cache"], {
            "items_before": ["newer.h5", "older.h5", "(New Layout Cache)"],
            "unrelated": {"rebuilt": False, "selected": "older.h5"},
            "removed": {"items": ["older.h5", "(New Layout Cache)"], "selected": "older.h5"},
            "naming": {"items": ["(New Layout Cache)"], "name": "draft.h5"},
        })

    def test_a_second_compatible_folder_shows_the_duplicate_error_at_the_next_look(self):
        case = self.report["recheck"]["second_folder"]
        self.assertEqual(case["copied"], ["Error: 2 compatible cache folders found", False])
        self.assertEqual(case["removed"], case["expected"])

    def test_a_cache_published_during_the_search_shows_at_the_next_look(self):
        self.assertEqual(
            self.report["recheck"]["during_search"], {"missed": True, "next_look": "version_00.h5"}
        )

    def test_opening_the_cache_list_looks_again(self):
        case = self.report["recheck"]["opened_list"]
        self.assertEqual(case["tracker"], f"Compatible Folder: {case['folder']}")
        self.assertEqual(case["selected"], "version_00.h5")

    def test_a_shown_window_looks_again_by_itself(self):
        case = self.report["recheck"]["by_itself"]
        self.assertEqual(case["constant"], 1000)
        self.assertEqual(case["timer"], [True, 1000])
        self.assertTrue(case["hidden"])
        self.assertEqual(case["shown"], f"Compatible Folder: {case['folder']}")

    def test_a_slow_layout_folder_is_looked_at_less_often(self):
        self.assertEqual(self.report["recheck"]["slow_folder"], [4000, 1000])

    def test_a_folder_removed_before_its_caches_are_listed_shows_an_error(self):
        self.assertEqual(
            self.report["recheck"]["folder_removed"],
            {"looked": True, "error": True, "look": None, "after_hashing": True},
        )


class ProjectRootFolderTests(unittest.TestCase):
    """The window uses the main program's folders, at the project root,
    except its own cache folder; only its settings file and the VR client
    build are in opt_vr."""

    def test_folders_resolve_at_the_project_root_and_the_client_in_opt_vr(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as root:
            for folder, name in (
                (os.path.join(root, "Input_Files", "Sequence_Sets"), "root_set.fasta"),
                # Left from when relative folders resolved inside opt_vr.
                (os.path.join(root, "opt_vr", "Input_Files", "Sequence_Sets"), "old_set.fasta"),
            ):
                os.makedirs(folder)
                with open(os.path.join(folder, name), "w", encoding="utf-8") as handle:
                    handle.write(">a\nMKT\n")
            for folder in (os.path.join(root, "player"), os.path.join(root, "opt_vr", "player")):
                os.makedirs(folder)
                open(os.path.join(folder, "EMAP-SSN-VR.exe"), "w").close()
            report = report_from(
                """
                window.cb_fasta.refresh_callback()
                foreign = namespace["_holds_foreign_client"]
                print("@@" + json.dumps({
                    "cwd": os.getcwd(),
                    "project_root": str(namespace["PROJECT_ROOT"]),
                    "opt_vr": str(namespace["OPT_VR_DIR"]),
                    "settings_file": namespace["DEFAULT_SETTINGS_FILE"],
                    "directories": {key: window.inputs[key].text() for key in
                                    ("INPUT_FILE_DIR", "CACHE_FILE_DIR", "ANALYSIS_RESULT_DIR", "EMBED_DIR")},
                    "saved_config_root": str(window._saved_config_root()),
                    "fasta": [window.cb_fasta.itemText(i) for i in range(window.cb_fasta.count())],
                    "player_in_opt_vr_is_foreign": foreign(os.path.join(str(namespace["OPT_VR_DIR"]), "player")),
                    "player_at_root_is_foreign": foreign(os.path.join(str(namespace["PROJECT_ROOT"]), "player")),
                    # Save & Run starts the viewer or generator in the project root.
                    "launch_root": "script_dir = str(PROJECT_ROOT)" in __import__("inspect").getsource(
                        namespace["ConfigGUI"].save_and_run),
                }))
                """,
                project_root=root,
            )
        norm = lambda path: os.path.normcase(os.path.normpath(path))  # noqa: E731
        self.assertEqual(norm(report["project_root"]), norm(root))
        self.assertEqual(norm(report["cwd"]), norm(root))
        self.assertEqual(norm(report["opt_vr"]), norm(os.path.join(root, "opt_vr")))
        self.assertEqual(norm(os.path.dirname(report["settings_file"])), norm(os.path.join(root, "opt_vr")))
        # The main program's default folders, but VR's own cache folder.
        self.assertEqual(report["directories"], {
            "INPUT_FILE_DIR": "Input_Files", "CACHE_FILE_DIR": "Cache_Files_VR",
            "ANALYSIS_RESULT_DIR": "Analysis_Results", "EMBED_DIR": "Embeddings",
        })
        self.assertEqual(norm(report["saved_config_root"]),
                         norm(os.path.join(root, "Cache_Files_VR", "Saved_Config")))
        self.assertIn("root_set.fasta", report["fasta"])
        self.assertNotIn("old_set.fasta", report["fasta"])
        # player/ is the client folder only in opt_vr.
        self.assertFalse(report["player_in_opt_vr_is_foreign"])
        self.assertTrue(report["player_at_root_is_foreign"])
        self.assertTrue(report["launch_root"])


class StatisticsWindowTests(unittest.TestCase):
    """Compute Network Statistics works on a thread, keeps the window usable and never reports stale inputs.

    The desktop Config's tests (test_emapssn_config_statistics) hold the details; the VR copy of
    the code is held to the same behaviour. The worker starts deferred (start() only records) and
    the script runs it on its own thread when it chooses, so every interleaving is deterministic.
    """

    @classmethod
    def setUpClass(cls):
        cls.report = report_from(
            """
            import tempfile
            import threading
            import h5py
            import numpy as np
            from PySide6.QtGui import QTextDocumentFragment
            from utilities import Network_Score_Statistics as scores

            window_globals = window.run_statistics.__globals__
            real_worker = window_globals["StatisticsWorker"]
            started = []

            class DeferredWorker(real_worker):
                interrupted = False

                def start(self):
                    started.append(self)

                def requestInterruption(self):
                    self.interrupted = True

                def isInterruptionRequested(self):
                    return self.interrupted

            window_globals["StatisticsWorker"] = DeferredWorker
            work = tempfile.mkdtemp()
            rng = np.random.default_rng(1)
            first = rng.integers(0, 5, size=60)
            second = rng.integers(first + 1, 6)
            with h5py.File(os.path.join(work, "network.h5"), "w") as network:
                network.attrs["model_name"] = "BLAST"
                network.create_dataset("headers", data=[("n%d" % index).encode() for index in range(6)])
                network.create_dataset("i", data=first.astype(np.uint16))
                network.create_dataset("j", data=second.astype(np.uint16))
                network.create_dataset("score", data=(rng.random(60) * 40).astype(np.float32))
            for name, nodes in (("all.fasta", range(6)), ("half.fasta", range(0, 6, 2))):
                with open(os.path.join(work, name), "w", encoding="utf-8") as handle:
                    handle.write("".join(">n%d\\nACDE\\n" % index for index in nodes))

            def select(fasta):
                for key in ("FASTA_DIR", "HDF5_DIR"):
                    window.inputs[key].blockSignals(True)
                    window.inputs[key].setText(work)
                    window.inputs[key].blockSignals(False)
                for combo, name in ((window.cb_fasta, fasta), (window.cb_hdf5, "network.h5")):
                    combo.blockSignals(True)
                    combo.clear()
                    combo.addItem(name)
                    combo.blockSignals(False)
                window._update_statistics_button()

            def panel():
                return QTextDocumentFragment.fromHtml(window.tip_panel.text()).toPlainText().strip()

            def run_deferred(worker):
                worker.run()
                app.processEvents()

            steps = {}
            select("all.fasta")

            # A run left alone: progress, a waiting button, then the report.
            window.run_statistics()
            worker = started[-1]
            steps["panel at start"] = panel()
            steps["button while running"] = window.btn_stats.isEnabled()
            window.update_live_validators()
            steps["button after an unrelated edit"] = window.btn_stats.isEnabled()
            shown = []
            worker.progress.connect(lambda request, fraction: shown.append(panel()))
            with mock.patch.object(scores, "CHUNK_EDGES", 10), mock.patch.object(scores, "worker_count", lambda: 1):
                run_deferred(worker)
            steps["progress"] = shown
            steps["panel at end"] = panel()
            steps["button after"] = window.btn_stats.isEnabled()
            steps["report"] = window.stat_display.toPlainText()
            first_report = steps["report"]

            # Changing the selection stops it, and its late result lands nowhere.
            started.clear()
            window.stat_display.clear()
            window._statistics = None
            window.run_statistics()
            worker = started[-1]
            window.cb_fasta.addItem("half.fasta")
            window.cb_fasta.setCurrentText("half.fasta")
            steps["interrupted by a selection"] = worker.interrupted
            steps["panel after a selection"] = panel()
            run_deferred(worker)
            steps["report after a stale run"] = window.stat_display.toPlainText()
            steps["workers left"] = len(window._statistics_workers)

            # A second run replaces the first.
            started.clear()
            select("all.fasta")
            window.run_statistics()
            window.run_statistics()
            first_worker, second_worker = started
            steps["first interrupted by the second"] = [first_worker.interrupted, second_worker.interrupted]
            run_deferred(first_worker)
            steps["report after the replaced run"] = window.stat_display.toPlainText()
            run_deferred(second_worker)
            steps["report after the second run"] = window.stat_display.toPlainText()

            # An error shows as it always did.
            started.clear()
            window.run_statistics()
            with mock.patch("h5py.File", side_effect=OSError("unreadable network")):
                run_deferred(started[-1])
            steps["error"] = panel()
            steps["button after the error"] = window.btn_stats.isEnabled()

            # A network rewritten while it ran is not reported.
            started.clear()
            window.stat_display.clear()
            window._statistics = None
            window.run_statistics()
            worker = started[-1]
            network_path = os.path.join(work, "network.h5")
            before = os.stat(network_path)
            with h5py.File(network_path, "a") as network:
                network.attrs["touched"] = "x" * 500
            os.utime(network_path, ns=(before.st_atime_ns, before.st_mtime_ns + 5_000_000_000))
            run_deferred(worker)
            steps["panel after a rewrite"] = panel()
            steps["report after a rewrite"] = window.stat_display.toPlainText()
            steps["button after a rewrite"] = window.btn_stats.isEnabled()

            # Progress leaves a tip the user chose alone.
            started.clear()
            window.run_statistics()
            worker = started[-1]
            window.tip_panel.setTip("A tip the user asked for.")
            during = []
            worker.progress.connect(lambda request, fraction: during.append(panel()))
            with mock.patch.object(scores, "CHUNK_EDGES", 10), mock.patch.object(scores, "worker_count", lambda: 1):
                run_deferred(worker)
            steps["panel during progress after a tip"] = sorted(set(during))
            steps["panel after that run"] = panel()

            # Closing the window stops a run.
            started.clear()
            window.run_statistics()
            worker = started[-1]
            window.close()
            steps["interrupted by closing"] = worker.interrupted
            run_deferred(worker)
            steps["workers after closing"] = len(window._statistics_workers)

            # Closing while the real thread runs waits for it (a shown window, so closing sends the event).
            window.show()
            window_globals["StatisticsWorker"] = real_worker
            reached, release = threading.Event(), threading.Event()
            real_compute = scores.compute_score_statistics

            def gated(source, **options):
                reached.set()
                release.wait(30)
                if options["cancelled"]():
                    raise scores.StatisticsCancelled()
                return real_compute(source, **options)

            with mock.patch.object(scores, "compute_score_statistics", gated):
                window.run_statistics()
                steps["gate reached"] = reached.wait(30)
                running = next(iter(window._statistics_workers.values()))
                threading.Timer(0.3, release.set).start()
                window.close()
                steps["thread finished on closing"] = running.isFinished()
                release.set()
            print("@@" + json.dumps(steps))
            """
        )

    def test_progress_runs_while_the_button_waits(self):
        steps = self.report
        self.assertEqual(steps["panel at start"], "Computing network statistics... 0 %")
        self.assertFalse(steps["button while running"])
        self.assertFalse(steps["button after an unrelated edit"])
        percents = [int(text.split("... ")[1].rstrip(" %")) for text in steps["progress"]]
        self.assertEqual(percents, sorted(percents))
        self.assertGreater(len(set(percents)), 3)
        self.assertEqual(percents[-1], 100)
        self.assertTrue(steps["button after"])
        self.assertEqual(steps["panel at end"], "Network statistics computed successfully.")
        self.assertIn("Stored Edges: 60 (Max possible: 15)", steps["report"])

    def test_changing_the_selection_stops_the_run_and_its_result_lands_nowhere(self):
        steps = self.report
        self.assertTrue(steps["interrupted by a selection"])
        self.assertEqual(steps["panel after a selection"], "Network statistics stopped: the inputs changed.")
        self.assertEqual(steps["report after a stale run"], "")
        self.assertEqual(steps["workers left"], 0)

    def test_a_second_run_replaces_the_first(self):
        steps = self.report
        self.assertEqual(steps["first interrupted by the second"], [True, False])
        self.assertEqual(steps["report after the replaced run"], "")
        self.assertIn("Stored Edges: 60", steps["report after the second run"])

    def test_an_error_shows_as_before_and_frees_the_button(self):
        self.assertEqual(self.report["error"], "Error during network statistics calculation: unreadable network")
        self.assertTrue(self.report["button after the error"])

    def test_a_network_rewritten_while_it_ran_is_not_reported(self):
        steps = self.report
        self.assertEqual(steps["panel after a rewrite"], "Network statistics stopped: the inputs changed.")
        self.assertEqual(steps["report after a rewrite"], "")
        self.assertTrue(steps["button after a rewrite"])

    def test_progress_leaves_a_tip_the_user_chose_alone(self):
        steps = self.report
        self.assertEqual(steps["panel during progress after a tip"], ["A tip the user asked for."])
        self.assertEqual(steps["panel after that run"], "Network statistics computed successfully.")

    def test_closing_the_window_stops_the_run(self):
        self.assertTrue(self.report["interrupted by closing"])
        self.assertEqual(self.report["workers after closing"], 0)

    def test_closing_while_the_thread_runs_waits_for_it(self):
        self.assertTrue(self.report["gate reached"])
        self.assertTrue(self.report["thread finished on closing"])


if __name__ == "__main__":
    unittest.main()
