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

"""Cache discovery races, score-kind cache discovery, and network statistics worker tests for VR Config."""

import os
from pathlib import Path
import shutil
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest import mock

from tests.vr_config_fixtures import vr_config_session


class CacheDiscoveryRaceTests(unittest.TestCase):
    """Hashing left running for earlier inputs never decides the target cache.

    The desktop Config's CacheDiscoveryRaceTests
    (tests/test_emapssn_config_cache_dropdown.py), run against this copy's
    code. Each CacheHashWorker hashes only when the test finishes it, on the
    test's thread, so every interleaving is deterministic; each case gets a
    fresh window. So are its Save & Run pause tests, and its tests of the
    next look for caches published after the check.
    """

    @classmethod
    def setUpClass(cls):
        with vr_config_session() as session:
            import h5py
            import numpy as np
            from PySide6.QtCore import Qt
            from PySide6.QtTest import QTest

            window = session.window
            namespace = session.namespace
            app = session.app
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
                (work / "a.fasta").write_text(">a1\nMKTAYIAK\n>a2\nMKTAYIAR\n", encoding="utf-8")
                (work / "b.fasta").write_text(">b1\nMSDNELKQ\n>b2\nMSDNELKE\n", encoding="utf-8")
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
                gui._cache_recheck_timer.stop()
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
            # The pause ends when the test says, not on a clock.
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
            cls.report = report

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


class ScoreKindCacheDiscoveryTests(unittest.TestCase):
    """The window looks for the cache folder the generator makes, EFI networks included.

    A BLAST network of EFI alignment scores records score_kind, and the
    generator's manifest (Cache_Manifest.build_manifest_for_files) carries it
    in its compatibility fields; a network without it holds E-values and
    keeps the identity it always had. Each CacheHashWorker hashes only when
    the test finishes it, as in CacheDiscoveryRaceTests.
    """

    @classmethod
    def setUpClass(cls):
        with vr_config_session() as session:
            import h5py
            import numpy as np

            window = session.window
            namespace = session.namespace
            app = session.app
            cache_manifest = namespace["cache_manifest"]
            window_globals = window._request_cache_discovery.__globals__
            workers = []

            class DeferredHashWorker(window_globals["CacheHashWorker"]):
                def start(self):
                    workers.append(self)

            window_globals["CacheHashWorker"] = DeferredHashWorker

            work = Path(tempfile.mkdtemp(dir=os.getcwd()))
            (work / "a.fasta").write_text(">a1\nMKTAYIAK\n>a2\nMKTAYIAR\n", encoding="utf-8")
            # The same network twice; only the second says its scores are EFI alignment scores.
            for name, score_kind in (("evalue.h5", None), ("efi.h5", "efi_alignment_score")):
                with h5py.File(work / name, "w") as network:
                    network.attrs["model_name"] = "BLAST"
                    if score_kind:
                        network.attrs["score_kind"] = score_kind
                    network.create_dataset("headers", data=[b"a1", b"a2"])
                    network.create_dataset("i", data=np.asarray([0], dtype=np.uint16))
                    network.create_dataset("j", data=np.asarray([1], dtype=np.uint16))
                    network.create_dataset("score", data=np.asarray([1e-30]))

            gui = namespace["ConfigGUI"]()
            settings = gui._cache_setting_values()
            layouts = work / "layouts"
            # What the generator publishes for each network: one folder each.
            generated = {}
            for name, folder in (("evalue.h5", "as_evalue"), ("efi.h5", "as_efi")):
                manifest = cache_manifest.build_manifest_for_files(
                    work / "a.fasta", work / name, **settings
                )
                cache_manifest.write_manifest_atomic(layouts / folder, manifest)
                generated[name] = manifest
            gui.inputs["SAVED_LAYOUT_DIR"].setText(str(layouts))
            gui.inputs["FASTA_DIR"].setText(str(work))
            gui.inputs["HDF5_DIR"].setText(str(work))
            gui.cb_fasta.setCurrentText("a.fasta")
            assert gui.cb_fasta.currentText() == "a.fasta"

            build_compatibility = cache_manifest.build_compatibility
            sequence_hash = cache_manifest.fingerprint_file(work / "a.fasta")["sha256"]
            report = {}
            for name in ("evalue.h5", "efi.h5"):
                asked = []

                def recording(*args, **kwargs):
                    asked.append(build_compatibility(*args, **kwargs))
                    return asked[-1]

                gui.cb_hdf5.setCurrentText(name)
                assert gui.cb_hdf5.currentText() == name, name
                with mock.patch.object(
                    cache_manifest, "build_compatibility", side_effect=recording
                ):
                    # Hash and report on this thread, as the worker's own would.
                    workers[-1].run()
                    app.processEvents()
                network_hash = cache_manifest.fingerprint_file(work / name)["sha256"]
                report[name] = {
                    "asked": len(asked),
                    "window_id": cache_manifest.calculate_manifest_id(asked[-1]),
                    "generator_id": generated[name]["manifest_id"],
                    # The id with no score kind passed: every E-value network's, before EFI.
                    "unkinded_id": cache_manifest.calculate_manifest_id(
                        build_compatibility(sequence_hash, network_hash, "blast", **settings)
                    ),
                    "records_kind": "score_kind" in generated[name]["compatibility"],
                    "tracker": gui.lbl_cache_tracker.text(),
                    "folder": os.path.basename(gui.current_cache_folder or ""),
                }
            # Both networks are hashed now, so choosing either again needs no worker.
            for name in ("evalue.h5", "efi.h5"):
                hashing = len(workers)
                gui.cb_hdf5.setCurrentText(name)
                assert gui.cb_hdf5.currentText() == name, name
                report[name]["again"] = {
                    "started": len(workers) - hashing,
                    "tracker": gui.lbl_cache_tracker.text(),
                    "folder": os.path.basename(gui.current_cache_folder or ""),
                }
                stats_worker = namespace["StatisticsWorker"](
                    1, str(work / name), str(work / "a.fasta"), "global", "alignment_length"
                )
                stats_report = stats_worker._report()
                stats_summary, _stats_headings = namespace["statistics_report_text"](stats_report)
                report[name]["stats_score_kind"] = stats_report.get("score_kind")
                report[name]["stats_metric"] = stats_summary[3]
            gui._cache_recheck_timer.stop()
            gui.close()
            gui.deleteLater()
            app.processEvents()
            cls.report = report

    def test_an_efi_network_gets_the_manifest_id_its_generator_gives_it(self):
        case = self.report["efi.h5"]
        self.assertTrue(case["asked"], "the window built no identity for the network")
        self.assertEqual(case["window_id"], case["generator_id"])
        self.assertTrue(case["records_kind"])
        # Not the id it would have as an E-value network.
        self.assertNotEqual(case["window_id"], case["unkinded_id"])

    def test_the_window_finds_the_folder_made_for_an_efi_network(self):
        case = self.report["efi.h5"]
        self.assertEqual(case["tracker"], "Compatible Folder: as_efi")
        self.assertEqual(case["folder"], "as_efi")

    def test_the_folder_is_found_again_from_the_hashes_already_taken(self):
        for name, folder in (("evalue.h5", "as_evalue"), ("efi.h5", "as_efi")):
            with self.subTest(name):
                self.assertEqual(self.report[name]["again"], {
                    "started": 0, "tracker": f"Compatible Folder: {folder}", "folder": folder,
                })

    def test_an_evalue_network_keeps_the_manifest_id_it_always_had(self):
        case = self.report["evalue.h5"]
        self.assertTrue(case["asked"], "the window built no identity for the network")
        self.assertEqual(case["window_id"], case["generator_id"])
        self.assertEqual(case["window_id"], case["unkinded_id"])
        self.assertFalse(case["records_kind"])
        self.assertEqual(case["tracker"], "Compatible Folder: as_evalue")
        self.assertEqual(case["folder"], "as_evalue")

    def test_statistics_report_names_efi_and_evalue_metrics(self):
        self.assertEqual(self.report["efi.h5"]["stats_score_kind"], "efi_alignment_score")
        self.assertEqual(self.report["efi.h5"]["stats_metric"], "Metric: EFI alignment score")
        self.assertEqual(self.report["evalue.h5"]["stats_score_kind"], "evalue")
        self.assertEqual(self.report["evalue.h5"]["stats_metric"], "Metric: Log10(E-Value)")


class StatisticsWindowTests(unittest.TestCase):
    """Compute Network Statistics works on a thread, keeps the window usable and never reports stale inputs.

    The desktop Config's tests (test_emapssn_config_statistics) hold the details; the VR copy of
    the code is held to the same behaviour. The worker starts deferred (start() only records) and
    the test runs it on its own thread when it chooses, so every interleaving is deterministic.
    """

    @classmethod
    def setUpClass(cls):
        with vr_config_session() as session:
            import h5py
            import numpy as np
            from PySide6.QtGui import QTextDocumentFragment
            from utilities import Network_Score_Statistics as scores

            window = session.window
            app = session.app
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
            with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as work:
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
                        # Every record has a sequence of its own (sanitization merges records that share one).
                        handle.write("".join(">n%d\nACDE%s\n" % (index, "K" * (index + 1)) for index in nodes))

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
                    release_timer = threading.Timer(0.3, release.set)
                    release_timer.start()
                    try:
                        window.close()
                        steps["thread finished on closing"] = running.isFinished()
                    finally:
                        release.set()
                        release_timer.cancel()
            cls.report = steps

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
