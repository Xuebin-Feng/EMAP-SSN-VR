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

"""Tip panel, consistency report, dropdowns, combo popups, and text-sized control tests for VR Config."""

import json
import os
import re
import shutil
import tempfile
import unittest
from unittest import mock

from tests.vr_config_fixtures import (
    finish_statistics,
    flush_events,
    vr_config_session,
)


class TipPanelStatusLockTests(unittest.TestCase):
    """Hovering never replaces a status message in the tip panel, as in the desktop Config.

    Hovering shows tips only while the panel holds a tip. A left click, or
    focus by Tab, on an element with a tip always shows it and makes hovering
    work again; right clicks and focus Qt moves by itself don't. Tips never
    open Qt's own tooltip popup.
    """

    @classmethod
    def setUpClass(cls):
        with vr_config_session() as session:
            import h5py
            from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
            from PySide6.QtGui import QFocusEvent, QHelpEvent, QMouseEvent, QTextDocumentFragment
            from PySide6.QtWidgets import QToolTip
            from desktop.Tip_Panel import Tip, plain

            window = session.window
            app = session.app

            def panel():
                shown = QTextDocumentFragment.fromHtml(window.tip_panel.text()).toPlainText()
                # A status message's icon is an image: one object-replacement character.
                return shown.replace("\ufffc", "").strip()

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

            with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
                with open(os.path.join(folder, "nodes.fasta"), "w", encoding="utf-8") as handle:
                    handle.write(">a\nMKTA\n>b\nMSEQ\n")
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
            cls.report = steps
            cls.tips = steps["tips"]

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
        with vr_config_session() as session:
            from PySide6.QtCore import QEvent, QObject, QPoint, Qt
            from PySide6.QtGui import QTextDocumentFragment
            from PySide6.QtTest import QTest
            from PySide6.QtWidgets import QTextEdit

            window = session.window
            app = session.app
            window.resize(1000, 650)
            window.show()
            window.activateWindow()
            app.processEvents()
            panel = window.tip_panel
            first_height = panel.height()
            held = lambda: [  # noqa: E731
                panel.height(), window.left_split.sizes(), window.tabs.height(),
                [window.minimumSizeHint().width(), window.minimumSizeHint().height()],
            ]
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
                return text.replace("\ufffc", "").strip().split("\n")[0].strip()

            def real_hover(widget):
                class Spy(QObject):
                    arrived = False

                    def eventFilter(spy, watched, event):
                        if watched is widget and event.type() == QEvent.Type.ToolTip:
                            spy.arrived = True
                        return False

                spy = Spy()
                app.installEventFilter(spy)
                try:
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
                finally:
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
            cls.report = {
                "first_height": first_height, "preferred": panel.preferred_height(),
                "is_scrolling_text_edit": isinstance(panel, QTextEdit),
                "moved": moved, "scrolls": scrolls, "mismatch": mismatch, "tips": tips,
                "horizontal": any(horizontal), "at_top": at_top, "pointer": pointer,
            }

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
        with vr_config_session() as session:
            from PySide6.QtCore import QEvent, QPointF, Qt
            from PySide6.QtGui import QMouseEvent, QTextDocumentFragment
            from desktop.Desktop_App import NAME_ITEM_ROLE
            from desktop.Tip_Panel import FieldTip, Tip, resolve, tip_plain

            window = session.window
            namespace = session.namespace
            app = session.app

            def click(widget):
                app.sendEvent(widget, QMouseEvent(
                    QEvent.Type.MouseButtonPress, QPointF(1, 1), QPointF(1, 1), Qt.MouseButton.LeftButton,
                    Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                ))
                return QTextDocumentFragment.fromHtml(window.tip_panel.text()).toPlainText().replace(chr(0xfffc), "")

            def squash(text):
                return re.sub(r"[ \t\r\n]+", " ", text).strip()

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
            cls.report = report

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
        self.assertIn(os.path.join(folder, "exports"), self.report["export"].replace("\u200b", ""))
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
        with vr_config_session() as session:
            import h5py
            from PySide6.QtGui import QTextCursor, QTextDocument, QTextTable

            window = session.window
            app = session.app
            window.resize(1000, 650)
            window.show()
            app.processEvents()
            first_height = window.tip_panel.height()
            with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
                long_header = "tr" + "A0A0A0_9BACT" * 40
                headers = ["WP_1_alpha", "WP_2_beta", long_header]
                sequences = ["MKTAYIAK", "MSEQNNTE", "MAAAGGGK"]
                with open(os.path.join(folder, "nodes.fasta"), "w", encoding="utf-8") as handle:
                    for header, sequence in zip(headers, sequences):
                        handle.write(">" + header + "\n" + sequence + "\n")
                with open(os.path.join(folder, "alignment.fasta"), "w", encoding="utf-8") as handle:
                    handle.write(">WP_1_alpha\nMKTAYIAK\n>WP_2_beta\nMSEQNNTE\n")
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
                    return cursor.selectedText().replace("\xa0", " ")

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

                cls.report = {
                    "first_height": first_height,
                    "preferred": panel.preferred_height(),
                    "states": states,
                    "rows": [[cell(row, column) for column in (1, 2, 3)] for row in range(table.rows())],
                    "text": document.toPlainText().replace("\u200b", ""),
                    "width_before": width_before,
                    "width_after": window.minimumSizeHint().width(),
                    "long_header": long_header,
                }

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


class DropdownValueTests(unittest.TestCase):
    """Options are read and selected by stored value, as in the desktop Config.

    Every option gets a label that differs from its value first, so code that
    still reads or matches the displayed text fails here.
    """

    @classmethod
    def setUpClass(cls):
        with vr_config_session() as session:
            window = session.window
            namespace = session.namespace
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
            cls.report = {
                "score": data["ALIGNMENT_SCORE"],
                "norm": data["NORM_MODE"],
                "norm_values": norm_values,
                "geometry": data["PACKING_GEOMETRY"],
                "new_cache": new_cache,
                "profile_selection": window._profile_previous_selection["visual_effects"],
                "profile_error": critical.called,
            }

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
        with vr_config_session(project_root=project) as session:
            from desktop.Desktop_App import install_translations
            from desktop.Tip_Panel import resolve

            window = session.window
            namespace = session.namespace
            app = session.app
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
            global_facts = [list(pair) for pair in resolve(window.tip_db[combo]).facts]
            select(window.cb_score_mode, "local")
            local_listing, current_local = listing(), combo.currentText()
            local_facts = [list(pair) for pair in resolve(window.tip_db[combo]).facts]
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
            tip_text = window.tip_panel.text()

            install_translations(app, "zh_CN")
            window.update_norm_mode_options()
            chinese = listing()
            chinese_names = list(namespace["normalization_names"]().values())
            cls.report = {
                "global": global_listing, "current_global": current_global,
                "local": local_listing, "current_local": current_local,
                "tip_rows": tip_rows, "restored": restored,
                "global_facts": global_facts, "local_facts": local_facts,
                "names": [list(names), list(names.values())], "metrics": metrics,
                "saved_ok": saved_ok, "tip": tip_text,
                "chinese": chinese, "chinese_names": chinese_names,
            }
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
                self.assertTrue(any("\u4e00" <= character <= "\u9fff" for character in chinese))


class ComboPopupTests(unittest.TestCase):
    """An open dropdown list scrolls by the wheel, scroll bar and keys, not by the mouse.

    The desktop Config's tests (tests/test_combo_popup.py) cover the behaviour;
    this copy only has to keep every combo box on the shared base class, and
    its own classes steady.
    """

    @classmethod
    def setUpClass(cls):
        with vr_config_session() as session:
            from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
            from PySide6.QtGui import QMouseEvent
            from PySide6.QtWidgets import QApplication, QComboBox, QVBoxLayout, QWidget
            from desktop.Desktop_App import SteadyPopupComboBox

            window = session.window
            namespace = session.namespace
            app = session.app

            def rest_on_the_partly_visible_row(combo):
                # A list cut off by 12 px, as a screen edge cuts a popup.
                combo.addItems(["Entry %d" % number for number in range(60)])
                host = QWidget()
                QVBoxLayout(host).addWidget(combo)
                host.resize(300, 120)
                host.show()
                flush_events(app)
                combo.showPopup()
                flush_events(app)
                view = combo.view()
                container = view.window()
                container.resize(container.width(), container.height() - 12)
                flush_events(app)
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
                    flush_events(app)
                report = {
                    "cut_off": cut_off,
                    "scrolled": view.verticalScrollBar().value(),
                    "current": view.currentIndex().row(),
                    "row": row,
                }
                combo.hidePopup()
                host.close()
                host.deleteLater()
                flush_events(app, 2)
                return report

            combos = window.findChildren(QComboBox)
            cls.report = {
                "combos": len(combos),
                "plain": [
                    type(combo).__name__ for combo in combos
                    if not isinstance(combo, SteadyPopupComboBox)
                ],
                "no_scroll": rest_on_the_partly_visible_row(namespace["NoScrollComboBox"]()),
                "dynamic": rest_on_the_partly_visible_row(
                    namespace["DynamicComboBox"](lambda: None)
                ),
            }

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
        with vr_config_session() as session:
            from PySide6.QtCore import QPoint
            from PySide6.QtGui import QFont, QFontMetrics
            from PySide6.QtWidgets import QTextEdit
            from desktop.Desktop_App import BUTTON_TEXT_PADDING, ToggleSwitch

            window = session.window
            namespace = session.namespace
            app = session.app
            window.show()
            flush_events(app)
            window.tabs.setCurrentIndex(1)  # Visual Effects holds the client block
            flush_events(app)
            page = window.tabs.currentWidget().widget()

            def x(widget):
                return widget.mapTo(page, QPoint()).x()

            switches = []
            for button in window.findChildren(namespace["QPushButton"]):
                # The high contrast button is an icon with no text to fit.
                if not button.isCheckable() or button.objectName() == "highContrastButton":
                    continue
                bold = QFont(button.font())
                bold.setBold(True)
                sizes, texts = set(), []
                for _ in range(2):
                    button.toggle()
                    flush_events(app)
                    sizes.add((button.width(), button.height()))
                    texts.append(button.text())
                needed = max(QFontMetrics(bold).horizontalAdvance(text) for text in texts)
                switches.append({
                    "texts": texts,
                    "toggle_switch": isinstance(button, ToggleSwitch),
                    "sizes": [list(pair) for pair in sorted(sizes)],
                    "needed": needed + 2 * BUTTON_TEXT_PADDING,
                })
            client_keys = ("VR_APP_DIR", "ENABLE_EDGE_FILTERING")
            report_box = window.stat_display
            hint = report_box.findChild(namespace["QLabel"], "wrappedPlaceholder")
            cls.report = {
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
            }

    def test_client_block_labels_join_the_label_column(self):
        report = self.report
        self.assertEqual(report["column_labels"], [report["column"]] * 2)
        self.assertEqual(report["client_fields"], [report["visual_field"]] * 2)

    def test_every_switch_fits_both_texts_and_keeps_its_size(self):
        switches = self.report["switches"]
        # Layout Method is a dropdown, no switch, so there is one fewer than before it replaced
        # the Plot Manifold Instead switch.
        self.assertEqual(len(switches), 4)
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
        with vr_config_session() as session:
            from PySide6.QtWidgets import QLabel

            namespace = session.namespace
            app = session.app

            class OverhangLabel(QLabel):
                def __init__(self, *args, **kwargs):
                    super().__init__(*args, **kwargs)
                    self.setContentsMargins(0, 0, 1, 0)

            # The window was built on import; build another whose labels overhang.
            gui = namespace["ConfigGUI"]
            with mock.patch.dict(gui.__init__.__globals__, {"QLabel": OverhangLabel}):
                overhang = gui()
            try:
                overhang.show()
                rows = []
                for width in (1600, 700):
                    overhang.resize(width + 360, 850)
                    flush_events(app, 6)
                    rows += [
                        {
                            "width": width, "text": label.text(), "fixed": label.width(),
                            "hint": label.sizeHint().width(),
                            "drop": label is overhang.labels["PERCENTAGE_DROP_THRESHOLD"],
                        }
                        for label in overhang.findChildren(OverhangLabel)
                        if label.text() and label.minimumWidth() == label.maximumWidth()
                    ]
            finally:
                overhang.close()
                overhang.deleteLater()
                flush_events(app, 2)
        self.assertEqual(sum(row["drop"] for row in rows), 2)
        for row in rows:
            with self.subTest(width=row["width"], label=row["text"]):
                # QLabel's size hint is at least its minimum width, so this
                # fails only when the fixed width is narrower than the text.
                self.assertGreaterEqual(row["fixed"], row["hint"])


if __name__ == "__main__":
    unittest.main()
