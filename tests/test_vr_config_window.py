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

"""Window structure, layout geometry, console capture, and root-folder tests for VR Config."""

import ast
import inspect
import os
import pathlib
import tempfile
import unittest
from unittest import mock

from tests.vr_config_fixtures import (
    VR_SRC,
    flush_events,
    resize_config_panel,
    vr_config_session,
)
import _bootstrap_vr  # noqa: E402


class ConfigWindowTests(unittest.TestCase):
    """What the copy changed, and what it must have kept."""

    @classmethod
    def setUpClass(cls):
        with vr_config_session() as session:
            window = session.window
            namespace = session.namespace
            cls.report = {
                "title": window.windowTitle(),
                "tabs": [window.tabs.tabText(i) for i in range(window.tabs.count())],
                "inputs": sorted(window.inputs),
                "unused_in_vr": sorted(namespace["UNUSED_IN_VR"]),
                "low_resource_keys": sorted(
                    key for key in namespace["VISUAL_PROFILE_DEFAULTS"]
                    if key.startswith("LOW_RESOURCE_")
                    or key in ("FEWER_EDGES_WHILE_MOVING", "SHOW_FPS")
                ),
                "profile_tabs": sorted(window.profile_selectors),
                "cache_settings": window._cache_setting_values(),
                "settings_file": namespace["SETTINGS_FILE"],
                "submodule": _bootstrap_vr.OPT_VR_DIR,
                "has_statistics": hasattr(window, "run_statistics"),
                "has_histogram": hasattr(window, "btn_hist") or hasattr(window, "run_histogram"),
                "has_stat_display": hasattr(window, "stat_display"),
                "icon_path": namespace["application_icon_path"](),
                "icon_loads": not window.windowIcon().pixmap(32, 32).isNull(),
            }

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


class ConsoleTests(unittest.TestCase):
    """VR Config keeps what it prints (temp/logs), as the other windows do; it has no Console window or button.

    The capture is the main program's (utilities/Console_Capture.py), which VR Config shares; what
    VR Config adds is that its entry point starts the capture, before anything prints, and
    routes Qt's messages through it.
    """

    def test_the_entry_point_starts_the_capture_before_anything_else_prints(self):
        path = os.path.join(VR_SRC, "EMAPSSN_Config_VR.py")
        with open(path, encoding="utf-8") as handle:
            source = handle.read()
        calls = [
            node for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "start_console_capture"
        ]
        self.assertEqual([ast.literal_eval(call.args[0]) for call in calls], ["vr-config"])
        # Ahead of every import the window needs, so what they print is kept too.
        self.assertLess(source.index('start_console_capture("vr-config")'), source.index("# Import Libraries"))
        # It replaces the plain UTF-8 setup; headless runs get that from start() itself.
        self.assertNotIn("configure_output_streams()", source)
        self.assertEqual(source.count("install_qt_message_handler()"), 1)

    def test_a_script_that_borrows_the_guis_main_block_writes_no_log_into_the_checkout(self):
        # Test sessions run the main block repeatedly: each run would leave a console log
        # in the checkout's temp/logs and push the real ones out of the ten that are kept.
        logs = os.path.join(_bootstrap_vr.PROJECT_ROOT, "temp", "logs")

        def listing():
            return set(os.listdir(logs)) if os.path.isdir(logs) else set()

        before = listing()
        with vr_config_session() as session:
            title = session.window.windowTitle()
        self.assertTrue(title)
        self.assertEqual(listing() - before, set())

    def test_the_process_sets_its_own_taskbar_identity_before_its_first_window(self):
        path = os.path.join(VR_SRC, "EMAPSSN_Config_VR.py")
        with open(path, encoding="utf-8") as handle:
            source = handle.read()
        calls = [node for node in ast.walk(ast.parse(source)) if isinstance(node, ast.Call)
                 and getattr(node.func, "id", None) == "set_app_user_model_id"]
        self.assertEqual([ast.unparse(call.args[0]) for call in calls], ["VR_CONFIG_APP_USER_MODEL_ID"])
        self.assertLess(source.index("set_app_user_model_id(VR_CONFIG_APP_USER_MODEL_ID)"),
                        source.index("app = existing_qt_application or QApplication(sys.argv)"))

    def test_the_window_gives_itself_the_small_icon_its_own_name_and_a_start_command_for_the_taskbar(self):
        path = os.path.join(VR_SRC, "EMAPSSN_Config_VR.py")
        with open(path, encoding="utf-8") as handle:
            source = handle.read()
        calls = [node for node in ast.walk(ast.parse(source)) if isinstance(node, ast.Call)
                 and ast.unparse(node.func) == "TaskbarIdentity"]
        self.assertEqual(len(calls), 1)
        self.assertEqual(
            [ast.unparse(argument) for argument in calls[0].args],
            ["self", "VR_CONFIG_APP_USER_MODEL_ID", "icon_path", "translate('Config', VR_CONFIG_DISPLAY_NAME)",
             "launcher_relaunch_command(VR_LAUNCHER_WORD, VR_LAUNCHER_BATCH, '')"])
        # The icon is the small one (ICON_CANDIDATES), never vr_logo_large.ico, which the shortcut uses for the desktop.
        self.assertNotIn("_large", source)
        self.assertIn('"vr_logo.ico"', source)
        # The launcher knows the word and the batch file, which takes no word: as install_vr.bat's shortcut runs them.
        with open(os.path.join(_bootstrap_vr.SRC_DIR, "bin", "Launcher.cs"), encoding="utf-8") as handle:
            main_launcher = handle.read()
        self.assertIn('VR_LAUNCHER_WORD = "vr"', source)
        self.assertIn('new[] { "vr",', main_launcher)
        self.assertTrue(os.path.isfile(os.path.join(VR_SRC, "bin", "EMAPSSN_Desktop_Launcher_VR.bat")))
        self.assertIn('"bin" / "EMAPSSN_Desktop_Launcher_VR.bat"', source)

    def test_the_footer_has_no_console_button_and_the_dropdown_has_its_full_width(self):
        with vr_config_session() as session:
            from PySide6.QtWidgets import QPushButton

            window = session.window
            selector = window.language_selector
            console_buttons = len(window.findChildren(QPushButton, "consoleButton"))
            least = selector.minimumSizeHint().width()
            preferred = selector.sizeHint().width()
        # VR Config shows no Console window: what it prints is kept in temp/logs, and the footer is the one it had.
        self.assertEqual(console_buttons, 0)
        self.assertEqual(least, preferred)


class LayoutMethodTests(unittest.TestCase):
    """The Layout Method dropdown, as in the main program's Config (VR layouts are 3D).

    SSN (the default) is the physics layout; UMAP and PaCMAP swap the two edge-filter fields for the manifold
    layout's own: UMAP's neighbour count and minimum distance, or PaCMAP's neighbour count with the minimum
    distance greyed out. The dropdown stands for two saved settings, UMAP_MODE and LAYOUT_METHOD: SSN is
    UMAP_MODE off and leaves LAYOUT_METHOD as saved. The window's cache identity names the method and its
    neighbours, always in three dimensions.
    """

    @classmethod
    def setUpClass(cls):
        with vr_config_session() as session:
            from desktop.Tip_Panel import resolve

            window = session.window
            namespace = session.namespace
            stacks = window._input_mode_stacks
            keys = ("UMAP_NEIGHBORS", "UMAP_MIN_DIST", "PACMAP_NEIGHBORS")
            combo = window.cb_layout_method

            def choose(choice):
                combo.setCurrentIndex(combo.findData(choice))

            def page(stack):
                widget = stack.currentWidget()
                return widget.text() if widget.metaObject().className() == "QLabel" else "field"

            def state():
                return {
                    "pages": [page(stack) for stack in stacks],
                    "enabled": {
                        key: [window.inputs[key].isEnabled(), window.labels[key].isEnabled()]
                        for key in keys
                    },
                    "tab_visible": window.tabs.isTabVisible(2),
                    "dropdown_enabled": [combo.isEnabled(), window.labels["LAYOUT_METHOD"].isEnabled()],
                    "uses_manifold": window.uses_manifold_layout(),
                }

            def saved():
                collected = window.collect_data()
                profile = [window._widget_profile_value("UMAP_MODE"), window._widget_profile_value("LAYOUT_METHOD")]
                carried = window.language_carry_over()["values"]
                same = (profile == [collected["UMAP_MODE"], collected["LAYOUT_METHOD"]]
                        == [carried["UMAP_MODE"], carried["LAYOUT_METHOD"]])
                return profile + [same]

            report = {
                "default_choice": combo.currentData(),
                "values": [combo.itemData(i) for i in range(combo.count())],
                "texts": [combo.itemText(i) for i in range(combo.count())],
                "pacmap_range": [window.spin_pacmap_k.minimum(), window.spin_pacmap_k.maximum(),
                                 window.spin_pacmap_k.value()],
                "label": window.labels["LAYOUT_METHOD"].text(),
                "old_switch": [hasattr(window, "check_umap"), "UMAP_MODE" in window.labels,
                               "UMAP_MODE" in window.inputs],
                "in_filter_row": combo.parentWidget().objectName(),
                "default_saved": saved(),
                "physics": state(),
            }
            choose("umap")
            report["umap"] = state()
            report["umap_saved"] = saved()
            choose("pacmap")
            window.spin_pacmap_k.setValue(21)
            report["pacmap"] = state()
            report["pacmap_saved"] = saved()
            report["cache_settings"] = window._cache_setting_values()
            collected = window.collect_data()
            report["collected"] = [collected["LAYOUT_METHOD"], collected["PACMAP_NEIGHBORS"]]
            # SSN leaves the method it last showed.
            choose("ssn")
            report["ssn_after_pacmap"] = saved()
            report["ssn_cache"] = window._cache_setting_values()
            choose("umap")
            choose("ssn")
            report["ssn_after_umap"] = saved()
            # Profiles, in either order.
            defaults = dict(namespace["TAB_PROFILE_SPECS"]["inputs_outputs"]["defaults"])
            report["profile_defaults"] = [defaults["UMAP_MODE"], defaults["LAYOUT_METHOD"], defaults["PACMAP_NEIGHBORS"]]
            orders = []
            for mode, method in ((True, "pacmap"), (True, "umap"), (False, "pacmap"), (False, "umap")):
                for order in (("UMAP_MODE", "LAYOUT_METHOD"), ("LAYOUT_METHOD", "UMAP_MODE")):
                    choose("pacmap" if method == "umap" else "umap")
                    values = {"UMAP_MODE": mode, "LAYOUT_METHOD": method}
                    for key in order:
                        window._set_widget_profile_value(key, values[key])
                    orders.append([mode, method, list(order), combo.currentData(), saved()[:2]])
            report["orders"] = orders
            window._apply_profile_data("inputs_outputs", dict(defaults))
            report["after_defaults"] = [combo.currentData(), saved()]
            report["tips"] = {
                key: bool(window.tip_db_keys[key].summary)
                for key in ("LAYOUT_METHOD", "PACMAP_NEIGHBORS", "UMAP_MIN_DIST")
            }
            report["tip_options"] = [option.value for option in window.tip_db_keys["LAYOUT_METHOD"].options]
            tip_facts = dict(resolve(window.tip_db[combo]).facts)
            report["tip_facts"] = [tip_facts["Default"], tip_facts["Setting"]]
            report["no_umap_mode_tip"] = "UMAP_MODE" not in window.tip_db_keys
            report["profile_defaults_check"] = [defaults["UMAP_MODE"], defaults["LAYOUT_METHOD"]]
            cls.report = report

    def test_the_dropdown_and_the_neighbour_field(self):
        report = self.report
        self.assertEqual((report["default_choice"], report["values"]), ("ssn", ["ssn", "umap", "pacmap"]))
        self.assertEqual(report["texts"], ["SSN", "UMAP", "PaCMAP"])
        self.assertEqual(report["pacmap_range"], [2, 50, 10])
        self.assertEqual(report["label"], "Layout Method:")
        self.assertEqual(report["profile_defaults"], [False, "umap", 10])
        self.assertEqual(report["in_filter_row"], "filterRow")
        # The switch and the row under the filters are gone.
        self.assertEqual(report["old_switch"], [False, False, False])

    def test_each_choice_shows_and_enables_its_own_fields(self):
        report = self.report
        self.assertEqual(report["physics"]["pages"][0], "Similarity Threshold:")
        self.assertEqual(report["umap"]["pages"][0], "UMAP Nearest Neighbors:")
        self.assertEqual(report["pacmap"]["pages"][0], "PaCMAP Nearest Neighbors:")
        self.assertEqual(report["pacmap"]["pages"][2], "UMAP Min Distance:")
        pair = lambda value: [value, value]          # noqa: E731
        self.assertEqual(report["physics"]["enabled"], {key: pair(False) for key in report["physics"]["enabled"]})
        self.assertEqual(report["umap"]["enabled"], {"UMAP_NEIGHBORS": pair(True), "UMAP_MIN_DIST": pair(True),
                                                      "PACMAP_NEIGHBORS": pair(False)})
        self.assertEqual(report["pacmap"]["enabled"], {"UMAP_NEIGHBORS": pair(False), "UMAP_MIN_DIST": pair(False),
                                                        "PACMAP_NEIGHBORS": pair(True)})
        self.assertTrue(report["physics"]["tab_visible"])
        self.assertFalse(report["umap"]["tab_visible"])
        self.assertFalse(report["pacmap"]["tab_visible"])
        self.assertEqual([report[name]["uses_manifold"] for name in ("physics", "umap", "pacmap")],
                         [False, True, True])
        # The dropdown is never greyed: it is how a layout is chosen.
        for name in ("physics", "umap", "pacmap"):
            self.assertEqual(report[name]["dropdown_enabled"], [True, True], name)

    def test_each_choice_is_saved_as_the_two_settings(self):
        report = self.report
        # (UMAP_MODE, LAYOUT_METHOD, every route agrees)
        self.assertEqual(report["default_saved"], [False, "umap", True])
        self.assertEqual(report["umap_saved"], [True, "umap", True])
        self.assertEqual(report["pacmap_saved"], [True, "pacmap", True])
        self.assertEqual(report["collected"], ["pacmap", "21"])
        # SSN leaves LAYOUT_METHOD as it last was.
        self.assertEqual(report["ssn_after_pacmap"], [False, "pacmap", True])
        self.assertEqual(report["ssn_after_umap"], [False, "umap", True])
        self.assertEqual(report["after_defaults"], ["ssn", [False, "umap", True]])

    def test_a_profile_is_applied_whatever_order_its_two_settings_arrive_in(self):
        for mode, method, order, shown, saved in self.report["orders"]:
            with self.subTest(mode=mode, method=method, order=order):
                self.assertEqual(shown, method if mode else "ssn")
                self.assertEqual(saved, [mode, method])

    def test_the_cache_identity_names_the_method_and_stays_three_dimensional(self):
        settings = self.report["cache_settings"]
        self.assertEqual((settings["umap_mode"], settings["layout_method"], settings["pacmap_neighbors"],
                          settings["layout_dimensions"]), (True, "pacmap", 21, 3))
        # SSN is a physics cache whatever method it remembers.
        ssn = self.report["ssn_cache"]
        self.assertEqual((ssn["umap_mode"], ssn["layout_dimensions"], ssn["layout_method"]), (False, 3, "pacmap"))

    def test_the_one_tip_explains_all_three_choices(self):
        self.assertEqual(set(self.report["tips"].values()), {True})
        self.assertEqual(self.report["tip_options"], ["ssn", "umap", "pacmap"])
        self.assertTrue(self.report["no_umap_mode_tip"])
        # The field it describes starts as SSN and holds both settings.
        self.assertEqual(self.report["tip_facts"], ["SSN", "UMAP_MODE, LAYOUT_METHOD"])


class LayoutMethodColumnTests(unittest.TestCase):
    """Alignment Offset and Layout Method share the last column of the aligned rows.

    Their labels start at one x, their fields share one left edge and one width, and the dropdown keeps room for
    PaCMAP in full. Stacked, both span the row like the other fields.
    """

    @classmethod
    def setUpClass(cls):
        with vr_config_session() as session:
            from PySide6.QtCore import QPoint
            from PySide6.QtWidgets import QComboBox, QLabel, QWidget

            window = session.window
            namespace = session.namespace
            app = session.app
            window.show()
            window.tabs.setCurrentIndex(0)
            page = window.tabs.currentWidget().widget()
            x = lambda widget: widget.mapTo(page, QPoint(0, 0)).x()  # noqa: E731
            right = lambda widget: widget.mapTo(page, QPoint(widget.width(), 0)).x()  # noqa: E731
            offset, offset_label = window.spin_alignment_offset, window.lbl_alignment_offset
            combo, combo_label = window.cb_layout_method, window.labels["LAYOUT_METHOD"]
            reference = QComboBox(page)
            reference.addItem("PaCMAP")
            reference.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
            aligned = [window.findChild(QWidget, name) for name in
                       ("alignmentModeRow", "alignmentReferenceRow", "filterRow")]
            rows = []
            for width in (1400, 1200, 1000, 800, 600, 1400):
                resize_config_panel(window, app, width)
                rows.append({
                    "width": width,
                    "stacked": bool(offset.parentWidget().property("stacked")),
                    "label_x": [x(offset_label), x(combo_label)],
                    "label_widths": [offset_label.width(), combo_label.width()],
                    "label_fits": [offset_label.width() >= offset_label.sizeHint().width(),
                                   combo_label.width() >= combo_label.sizeHint().width()],
                    "field_x": [x(offset), x(combo)],
                    "field_widths": [offset.width(), combo.width()],
                    "field_rights": [right(offset), right(combo), right(window.line_ref)],
                    "dropdown_room": combo.width() >= reference.sizeHint().width(),
                })
            natural = max(QLabel(offset_label.text()).sizeHint().width(),
                          QLabel(combo_label.text()).sizeHint().width())
            facts = {
                "label_natural": natural,
                "contents_length": [combo.minimumContentsLength(), namespace["LAYOUT_METHOD_MINIMUM_CHARACTERS"]],
                "minimum": combo.minimumSizeHint().width(),
                "needed": reference.sizeHint().width(),
                "offset_minimum": offset.minimumSizeHint().width(),
                "full_layout_minimum": [row.layout()._wide_width() for row in aligned],
            }
            window.resize(0, 850)
            window.main_split.setSizes([sum(window.main_split.sizes()), 0])
            flush_events(app)
            facts["narrowest_widths"] = [row.width() for row in aligned]
            facts["narrowest_stacked"] = [bool(row.property("stacked")) for row in aligned]
            facts["at_window_minimum"] = window.width() == window.minimumWidth()
            facts["narrowest_dropdown_room"] = combo.width() >= reference.sizeHint().width()
            cls.report = {"rows": rows, "facts": facts}

    def test_the_labels_start_at_one_x_and_the_fields_share_a_left_edge_and_a_width_while_wide(self):
        wide = [row for row in self.report["rows"] if not row["stacked"]]
        self.assertTrue(wide)
        for row in wide:
            with self.subTest(width=row["width"]):
                self.assertEqual(len(set(row["label_x"])), 1, row["label_x"])
                self.assertEqual(len(set(row["label_widths"])), 1, row["label_widths"])
                self.assertEqual(len(set(row["field_x"])), 1, row["field_x"])
                self.assertEqual(len(set(row["field_widths"])), 1, row["field_widths"])
                self.assertEqual(len(set(row["field_rights"][:2])), 1)
                self.assertTrue(all(row["label_fits"]), row["label_fits"])
                # Only as wide as it needs to be: the label, and the dropdown's minimum.
                self.assertEqual(row["label_widths"][0], self.report["facts"]["label_natural"])
                self.assertEqual(row["field_widths"][0], self.report["facts"]["minimum"])

    def test_the_dropdown_shows_pacmap_in_full_at_every_width(self):
        facts = self.report["facts"]
        self.assertGreaterEqual(facts["minimum"], facts["needed"])
        self.assertLess(facts["minimum"] - facts["needed"], 8)      # no more than needed
        # It was given its own length before anything measured it, and kept it.
        self.assertEqual(facts["contents_length"][0], facts["contents_length"][1])
        self.assertGreaterEqual(facts["minimum"], facts["offset_minimum"])
        for row in self.report["rows"]:
            self.assertTrue(row["dropdown_room"], row["width"])
        self.assertTrue(facts["narrowest_dropdown_room"])

    def test_stacked_rows_span_the_row_with_both_fields(self):
        stacked = [row for row in self.report["rows"] if row["stacked"]]
        self.assertTrue(stacked)
        for row in stacked:
            with self.subTest(width=row["width"]):
                self.assertEqual(len(set(row["field_rights"])), 1, row["field_rights"])
                self.assertEqual(len(set(row["field_x"])), 1, row["field_x"])
                self.assertTrue(all(row["label_fits"]))

    def test_the_rows_stay_side_by_side_in_the_narrowest_window_without_the_report(self):
        facts = self.report["facts"]
        self.assertEqual(len(set(facts["full_layout_minimum"])), 1, facts["full_layout_minimum"])
        for width in facts["narrowest_widths"]:
            self.assertLessEqual(facts["full_layout_minimum"][0], width)
        self.assertTrue(facts["at_window_minimum"])
        self.assertEqual(facts["narrowest_stacked"], [False, False, False])


class EmbeddingRootTests(unittest.TestCase):
    """The Directories tab lists the embedding directory as its fourth root.

    Like the main program's Config, which this window is a copy of: after the
    Input File, Cache File and Analysis Results Directories and before the
    separator, standing for ``$embedding$`` and refreshing the Embedding Input
    dropdown once when it changes.
    """

    @classmethod
    def setUpClass(cls):
        with vr_config_session() as session:
            from desktop.Tip_Panel import tip_plain

            window = session.window
            namespace = session.namespace
            layout = window.labels["INPUT_FILE_DIR"].parentWidget().layout()
            row = lambda widget: layout.getWidgetPosition(widget)[0]  # noqa: E731
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
                cls.report = {
                    "rows": rows,
                    "separator_row": separator_row,
                    "initial": initial,
                    "folder": folder,
                    "refreshed": refreshed,
                    "items": items,
                    "resolved": resolved,
                    "aliases": dict(namespace["DIRECTORY_PATH_ALIASES"]),
                    "open_button": "EMBED_DIR" in window.directory_open_buttons,
                    "tip": tip_plain(window.tip_db[window.inputs["EMBED_DIR"]]),
                    "label_tip": tip_plain(window.tip_db[window.labels["EMBED_DIR"]]),
                }

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


class AutoStepSizeTests(unittest.TestCase):
    """The Auto button beside Step Size behaves as in the desktop Config."""

    def test_auto_button_greys_out_the_step_size_field(self):
        with vr_config_session() as session:
            window = session.window
            namespace = session.namespace
            app = session.app
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
            report = {
                "button_starts_the_cell": cell.layout().itemAt(0).widget() is button,
                "field_follows": cell.layout().itemAt(1).widget() is field,
                "cell_is_as_narrow_as_a_field": (
                    minimum_width(cell) == minimum_width(window.inputs["MAX_STEPS"])
                ),
                "gap_matches_label_spacing": (
                    cell.layout().spacing() == namespace["CONFIG_FIELD_HORIZONTAL_SPACING"]
                ),
                "in_physics_profile": (
                    "AUTO_DT" in namespace["TAB_PROFILE_SPECS"]["simulation_physics"]["defaults"]
                ),
                "states": states,
            }
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
        with vr_config_session() as session:
            from PySide6.QtCore import QPoint
            from PySide6.QtWidgets import QWidget

            window = session.window
            app = session.app
            window.show()
            window.tabs.setCurrentIndex(0)
            page = window.tabs.currentWidget().widget()
            offset, label = window.spin_alignment_offset, window.lbl_alignment_offset

            def right(widget):
                return widget.mapTo(page, QPoint(widget.width(), 0)).x()

            rows = []
            for width in (1400, 600, 800, 1400):
                resize_config_panel(window, app, width)
                rows.append({
                    "width": width,
                    "stacked": bool(offset.parentWidget().property("stacked")),
                    "label_fits": label.width() >= label.sizeHint().width(),
                    "offset_width": offset.width(),
                    "offset_minimum": offset.minimumSizeHint().width(),
                    "dropdown_width": window.cb_layout_method.width(),
                    "rights": [right(offset), right(window.line_ref),
                               right(window.spin_min_occ)],
                })

            aligned = [window.findChild(QWidget, name) for name in
                       ("alignmentModeRow", "alignmentReferenceRow", "filterRow")]
            # The narrowest window, with the report collapsed.
            window.resize(0, 850)
            window.main_split.setSizes([sum(window.main_split.sizes()), 0])
            flush_events(app)
            cls.report = {
                "rows": rows,
                "full_layout_minimum": [row.layout()._wide_width() for row in aligned],
                "narrowest_widths": [row.width() for row in aligned],
                "narrowest": {
                    "at_window_minimum": window.width() == window.minimumWidth(),
                    "stacked": [bool(row.property("stacked")) for row in aligned],
                },
            }

    def test_offset_spans_stacked_rows_and_keeps_its_wide_width(self):
        for row in self.report["rows"]:
            with self.subTest(width=row["width"]):
                stacked = row["width"] < 1400
                self.assertEqual(row["stacked"], stacked)
                self.assertTrue(row["label_fits"])
                if stacked:
                    self.assertEqual(len(set(row["rights"])), 1, row["rights"])
                else:
                    # As wide as the Layout Method dropdown under it, whose minimum (room for PaCMAP)
                    # is wider than its own: room for a sign and a few digits.
                    self.assertEqual(row["offset_width"], row["dropdown_width"])
                    self.assertGreaterEqual(row["offset_width"], row["offset_minimum"])

    def test_rows_stay_side_by_side_in_the_narrowest_window_without_the_report(self):
        # The fields stay side by side down to the width they need, which the
        # narrowest window has room for: 798 px with Windows' unhinted text.
        minima = self.report["full_layout_minimum"]
        self.assertEqual(len(set(minima)), 1, minima)
        for width in self.report["narrowest_widths"]:
            self.assertLessEqual(minima[0], width)
        self.assertEqual(self.report["narrowest"],
                         {"at_window_minimum": True, "stacked": [False, False, False]})


class BridgeFieldsTests(unittest.TestCase):
    """The VR client rows stack in a narrow tab, as the other rows do, and line up with them."""

    def test_client_halves_stack_without_sideways_scroll_and_keep_the_label_column(self):
        with vr_config_session() as session:
            from PySide6.QtCore import QPoint
            from PySide6.QtWidgets import QWidget

            window = session.window
            app = session.app
            window.show()
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
                resize_config_panel(window, app, width, flush_count=6)
                rows.append({
                    "width": width,
                    "stacked": bool(fields.property("stacked")),
                    "sideways": scroll.horizontalScrollBar().maximum(),
                    "tops": [client.y(), endpoint.y()],
                    "widths": [client.width(), endpoint.width()],
                    "field_x": [left(window.inputs[key]) for key in
                                ("VR_APP_DIR", "VR_HOST", "DISTANCE_SCALE")],
                })
        for row in rows:
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
            with vr_config_session(project_root=project) as session:
                window = session.window
                app = session.app
                # The Inputs tab lists its folders as it is built, before its
                # scroll area first measures it, and a combo box keeps that
                # first minimum. The event loop has not run yet.
                listed = [window.cb_hdf5.itemText(i) for i in range(window.cb_hdf5.count())]
                window.show()
                window.tabs.setCurrentIndex(0)
                # The narrowest window, with the report collapsed.
                window.resize(0, 850)
                window.main_split.setSizes([sum(window.main_split.sizes()), 0])
                flush_events(app, 6)
                report = {
                    "listed": listed,
                    "widths": [window.cb_hdf5.minimumSizeHint().width(),
                               window.cb_fasta.minimumSizeHint().width()],
                    "sideways": window.tabs.currentWidget().horizontalScrollBar().maximum(),
                }
        # The test's own folder, not the checkout's.
        self.assertEqual(report["listed"], ["", name])
        # As narrow as the (empty) sequence set list.
        self.assertEqual(report["widths"][0], report["widths"][1])
        self.assertEqual(report["sideways"], 0)


class InterruptedRunFolderTests(unittest.TestCase):
    """The folder an interrupted run left behind is the one the layout generator reuses.

    VR Config passes the sequence file's base name as an allowed name, as the
    desktop Config does, so a folder holding only that file and an unfinished
    ``*.partial`` file counts as free instead of earning a ``_[<id>]`` sibling.
    """

    @classmethod
    def setUpClass(cls):
        with vr_config_session() as session:
            window = session.window
            namespace = session.namespace
            cache_manifest = namespace["cache_manifest"]
            compatibility = cache_manifest.build_compatibility(
                "a" * 64, "b" * 64, "alignment",
                alignment_score="global", normalization="alignment_length", top_edge_percent=5.0,
            )
            with tempfile.TemporaryDirectory() as temp_dir:
                root = pathlib.Path(temp_dir)
                (root / "readable-cache").mkdir()
                (root / "readable-cache" / "set.fasta").write_text("x", encoding="utf-8")
                (root / "readable-cache" / ".cache.h5.abc.partial").write_text("x", encoding="utf-8")
                directory_input = window.inputs["SAVED_LAYOUT_DIR"]
                directory_input.blockSignals(True)
                directory_input.setText(str(root))
                directory_input.blockSignals(False)
                with mock.patch.object(
                    window, "_cache_paths_from_inputs",
                    return_value=(str(root / "set.fasta"), str(root / "network.h5")),
                ), mock.patch.object(
                    cache_manifest, "build_compatibility", return_value=compatibility
                ), mock.patch.object(
                    cache_manifest, "build_canonical_cache_name", return_value="readable-cache"
                ), mock.patch.object(
                    cache_manifest, "find_matching_manifest_folders", return_value=[]
                ):
                    window._apply_cache_discovery({
                        "sequence": {"sha256": "a" * 64},
                        "network": {"sha256": "b" * 64},
                        "network_type": "alignment",
                    })
                cls.report = {
                    "folder": pathlib.Path(window.current_cache_folder).name,
                    "reused": pathlib.Path(window.current_cache_folder) == root / "readable-cache",
                }

    def test_the_folder_holding_only_the_sequence_file_and_a_partial_file_is_reused(self):
        self.assertTrue(self.report["reused"], self.report["folder"])
        self.assertEqual(self.report["folder"], "readable-cache")


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
            with vr_config_session(project_root=root) as session:
                window = session.window
                namespace = session.namespace
                window.cb_fasta.refresh_callback()
                foreign = namespace["_holds_foreign_client"]
                report = {
                    "cwd": os.getcwd(),
                    "project_root": str(namespace["PROJECT_ROOT"]),
                    "opt_vr": str(namespace["OPT_VR_DIR"]),
                    "settings_file": namespace["DEFAULT_SETTINGS_FILE"],
                    "directories": {
                        key: window.inputs[key].text()
                        for key in ("INPUT_FILE_DIR", "CACHE_FILE_DIR", "ANALYSIS_RESULT_DIR", "EMBED_DIR")
                    },
                    "saved_config_root": str(window._saved_config_root()),
                    "fasta": [window.cb_fasta.itemText(i) for i in range(window.cb_fasta.count())],
                    "player_in_opt_vr_is_foreign": foreign(
                        os.path.join(str(namespace["OPT_VR_DIR"]), "player")
                    ),
                    "player_at_root_is_foreign": foreign(
                        os.path.join(str(namespace["PROJECT_ROOT"]), "player")
                    ),
                    # Save & Run starts the viewer or generator in the project root.
                    "launch_root": "script_dir = str(PROJECT_ROOT)" in inspect.getsource(
                        namespace["ConfigGUI"].save_and_run
                    ),
                }
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


if __name__ == "__main__":
    unittest.main()
