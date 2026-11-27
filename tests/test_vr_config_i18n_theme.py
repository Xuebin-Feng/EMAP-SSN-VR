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

"""Translation, language switching, theme colour, and catalog tests for VR Config."""

import ast
import importlib.util
import json
import os
import shutil
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from tests.vr_config_fixtures import (
    VR_SRC,
    finish_statistics,
    flush_events,
    load_translation_fixtures,
    vr_config_session,
)


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
        with vr_config_session(pseudo_translation=True) as session:
            from desktop.Desktop_App import installed_language
            from utilities.Localization import is_pseudo_translated

            window = session.window
            app = session.app
            fixtures = load_translation_fixtures()
            window.resize(1800, 1000)
            window.show()
            flush_events(app)
            texts = fixtures.visible_texts(window)
            cls.report = {
                "language": installed_language(),
                "texts": len(texts),
                "unmarked": [[where, text] for where, text in texts if not is_pseudo_translated(text)],
                "cut_off": fixtures.cut_off_texts(window),
            }

    def test_startup_installs_the_language_before_building_the_window(self):
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
        with vr_config_session() as session:
            from PySide6.QtWidgets import QSplitter, QTabWidget
            from desktop.Desktop_App import LanguageSelector, installed_language

            window = session.window
            app = session.app
            window.show()
            flush_events(app)
            window.resize(1300, 800)
            window.move(40, 60)
            window.tabs.setCurrentIndex(1)
            window.inputs["NODE_SIZE"].setValue(window.inputs["NODE_SIZE"].value() + 1)
            flush_events(app)

            def view(shown):
                return {
                    "geometry": list(shown.geometry().getRect()),
                    "splitters": [splitter.sizes() for splitter in shown.findChildren(QSplitter)],
                    "tabs": [tabs.currentIndex() for tabs in shown.findChildren(QTabWidget)],
                }

            before = view(window)
            values = window.language_carry_over()["values"]
            selectors = window.findChildren(LanguageSelector)
            replacement = window.switch_language("pseudo")
            flush_events(app)
            cls.report = {
                "selectors": len(selectors),
                "items": [selectors[0].itemData(i) for i in range(selectors[0].count())],
                "language": installed_language(),
                "replaced": replacement is not window and not window.isVisible(),
                "before": before,
                "after": view(replacement),
                "values_kept": replacement.language_carry_over()["values"] == values,
                "first_item": replacement.language_selector.itemText(0),
                "title": replacement.windowTitle(),
            }

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
        with vr_config_session() as session:
            from PySide6.QtWidgets import QWidget
            from desktop import Desktop_App
            from desktop.Desktop_App import installed_language
            from utilities.App_Settings import save_app_setting

            window = session.window
            app = session.app
            window.show()
            flush_events(app, 6)
            window.inputs["NODE_SIZE"].setValue(window.inputs["NODE_SIZE"].value() + 1)  # unsaved
            values = window.language_carry_over()["values"]
            elsewhere = QWidget()
            elsewhere.show()
            flush_events(app, 6)
            save_app_setting("LANGUAGE", "zh_CN")  # as Config or Tools saves it
            flush_events(app, 6)
            waited = window.isVisible() and installed_language() is None
            window.activateWindow()
            flush_events(app, 6)
            replacement = Desktop_App._redrawn_windows[-1] if Desktop_App._redrawn_windows else window
            installed = Desktop_App._installed_translations
            cls.report = {
                "waited": waited,
                "replaced": replacement is not window,
                "language": installed_language(),
                "extra_catalogs": [name for _, name in installed.extra_catalogs] if installed else [],
                "title": replacement.windowTitle(),
                "setting": replacement.language_selector.setting(),
                "values_kept": replacement.language_carry_over()["values"] == values,
            }
            elsewhere.close()
            elsewhere.deleteLater()

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
        with vr_config_session(project_root=folder.name) as session:
            from PySide6.QtCore import QPoint
            from PySide6.QtWidgets import QFrame
            from desktop import Desktop_App
            from desktop.Studio_Theme import theme_color, theme_tokens
            from utilities.App_Settings import read_app_settings

            window = session.window
            app = session.app

            def section_lines(shown):
                lines = [frame for frame in shown.findChildren(QFrame)
                         if frame.property("role") == "separator" and frame.isVisible()]
                images = [line.grab().toImage() for line in lines]
                return {
                    "count": len(lines),
                    "heights": sorted({line.height() for line in lines}),
                    "colours": sorted({
                        image.pixelColor(image.width() // 2, y).name()
                        for image in images for y in range(image.height())
                    }),
                }

            window.show()
            flush_events(app)
            switch, language = window.theme_switch, window.language_selector
            started = {"window": theme_color(), "switch": switch.color(), "setting": switch.theme_setting}
            lines_before = section_lines(window)
            after_language = (switch.mapTo(window, QPoint(0, 0)).x()
                              > language.mapTo(window, QPoint(language.width(), 0)).x())
            values = window.language_carry_over()["values"]
            switch.color_chosen.emit("orange")
            flush_events(app)
            replacement = Desktop_App._redrawn_windows[-1]
            cls.report = {
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
            }

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
        with vr_config_session(pseudo_translation=True) as session:
            import h5py
            import numpy
            from PySide6.QtGui import QTextDocumentFragment
            from desktop.Tip_Panel import Tip
            from utilities.Localization import display_text, is_pseudo_translated

            window = session.window
            namespace = session.namespace
            fixtures = load_translation_fixtures()
            checked, left = [], {}

            def check(name, text):
                checked.append(name)
                if not text or fixtures.outside_the_catalog(text):
                    left[name] = text

            def plain(html_text):
                return QTextDocumentFragment.fromHtml(html_text).toPlainText()

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
                ("foreign", decide(None, "127.0.0.1", 5005, build_dir=foreign)),
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
            for tab_id, data in (("visual_effects", []), ("visual_effects", {"BOGUS": 1}),
                                 ("visual_effects", {"NODE_SIZE": 10.5}),
                                 ("visual_effects", {"NODE_SIZE": 1e999}),
                                 ("visual_effects", {"EDGE_COLOR": "nocolor"}),
                                 ("inputs_outputs", {"ALIGNMENT_SCORE": "local",
                                                     "NORM_MODE": "alignment_length"})):
                try:
                    window._normalize_profile_data(tab_id, data)
                    left["no profile data error " + repr(data)] = ""
                except ValueError as error:
                    check("profile data " + repr(data), display_text(error))

            with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
                with open(os.path.join(folder, "subset.fasta"), "w", encoding="utf-8") as handle:
                    handle.write(">WP_1_alpha\nMKTA\n>WP_2_beta\nMSEQ\n>Other\nMAAA\n")
                with open(os.path.join(folder, "alignment.fasta"), "w", encoding="utf-8") as handle:
                    handle.write(">WP_1_alpha\nMKTA\n")

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
                blast = SimpleNamespace(network_type="blast", model_name="BLAST", score_kind=None)
                cache_manifest = window.run_statistics.__globals__["cache_manifest"]
                with mock.patch.object(cache_manifest, "validate_network_schema", return_value=blast):
                    window.run_statistics()
                    finish_statistics(window)
                check("statistics report", window.stat_display.toPlainText())
                check("statistics tip", plain(window.tip_panel.text()))
            cls.report = {"checked": checked, "left": left}

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
        with vr_config_session(pseudo_translation=True) as session:
            from desktop import Desktop_App

            installed = Desktop_App._installed_translations
            report = {
                "language": installed.language,
                "extra": [[str(directory), name] for directory, name in installed.extra_catalogs],
                "title": session.window.windowTitle(),
            }
        self.assertEqual(report["language"], "pseudo")
        same_path = os.path.normcase(os.path.normpath(os.path.join(VR_SRC, "resources", "languages")))
        self.assertEqual(
            [[os.path.normcase(os.path.normpath(directory)), name] for directory, name in report["extra"]],
            [[same_path, "emapssn_vr"]],
        )
        # Its title is VR Config's own text, so it comes from opt_vr's catalog.
        self.assertTrue(report["title"].startswith("["), report["title"])


if __name__ == "__main__":
    unittest.main()
