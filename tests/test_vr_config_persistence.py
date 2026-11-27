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

"""Settings persistence, launch handoff, VR endpoint, atomic-write, and load tests for VR Config."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

from tests.vr_config_fixtures import (
    OPT_VR,
    VR_SRC,
    vr_config_session,
)
import _bootstrap_vr  # noqa: E402


class BlastNetworkSaveTests(unittest.TestCase):
    """A BLAST network blanks both modes; Save keeps the alignment choice they hide.

    As in the desktop Config, saving used to fail with "invalid value for
    ALIGNMENT_SCORE" because the blank controls were saved as empty text. The
    case really saves, so it runs in a throwaway project.
    """

    @classmethod
    def setUpClass(cls):
        project = tempfile.mkdtemp()
        cls.addClassCleanup(shutil.rmtree, project, ignore_errors=True)
        with vr_config_session(project_root=project) as session:
            window = session.window
            namespace = session.namespace
            select = namespace["select_combo_value"]
            value = namespace["combo_value"]

            window._set_network_type_controls("alignment")
            select(window.cb_score_mode, "local")
            select(window.cb_norm_mode, "average_sequence")
            window._set_network_type_controls("blast")
            blank = [window.cb_score_mode.currentIndex(), window.cb_norm_mode.currentIndex()]
            saved_ok = window.save_settings()
            tip = window.tip_panel.text()
            window._set_network_type_controls("alignment")
            cls.report = {
                "blank": blank,
                "saved_ok": saved_ok,
                "tip": tip,
                "restored": [value(window.cb_score_mode), value(window.cb_norm_mode)],
            }
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
        with vr_config_session() as session:
            namespace = session.namespace
            captured = {}

            def fake(argv, **kwargs):
                captured["argv"] = [str(a) for a in argv]
                captured["title"] = kwargs.get("title")
                return None

            namespace["_handoff_to_viewer"].__globals__["launch_in_terminal"] = fake
            namespace["_handoff_to_viewer"](
                OPT_VR, {}, settings_path="snap.json", executable="/python"
            )
        script = captured["argv"][2]
        self.assertTrue(
            os.path.samefile(script, os.path.join(VR_SRC, "EMAPSSN_Viewer_VR.py")),
            f"launched {script}",
        )
        self.assertNotIn("EMAPSSN_Viewer.py", script)
        self.assertEqual(captured["title"], "EMAP-SSN VR Viewer")

    def test_generator_still_comes_from_the_parent_checkout(self):
        """opt_vr owns no pipeline; layouts are built by the main program."""
        with vr_config_session() as session:
            namespace = session.namespace
            captured = {}

            def fake(argv, **kwargs):
                captured["argv"] = [str(a) for a in argv]
                return None

            namespace["_handoff_to_layout_generator"].__globals__["launch_in_terminal"] = fake
            namespace["_handoff_to_layout_generator"](
                "ignored", "layout.json", {}, executable="/python", launch_viewer=False
            )
            generator_only = list(captured["argv"])
            namespace["_handoff_to_layout_generator"](
                "ignored", "layout.json", {}, executable="/python", launch_viewer=True
            )
            captured["vr_argv"] = list(captured["argv"])
            captured["argv"] = generator_only
        script = captured["argv"][2]
        self.assertTrue(
            os.path.samefile(
                script,
                os.path.join(_bootstrap_vr.SRC_DIR, "Layout_Cache_Generator.py"),
            ),
            f"generator resolved to {script}",
        )
        self.assertEqual(captured["vr_argv"][2], os.path.join(VR_SRC, "Layout_Launcher_VR.py"))
        self.assertNotIn("--launch-viewer", captured["vr_argv"])


class ConfigPersistenceTests(unittest.TestCase):
    """Saving writes into the submodule and nowhere else.

    Each case really saves, so each runs in a throwaway project whose opt_vr
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
        with vr_config_session(project_root=self.project) as session:
            window = session.window
            namespace = session.namespace
            window.inputs["VR_APP_DIR"].setText("no_such_build")
            window.inputs["VR_PORT"].setValue(5123)
            report = {
                "saved": window.save_settings(),
                "tip": window.tip_panel.text(),
                "settings_file": namespace["SETTINGS_FILE"],
            }
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
        with vr_config_session(project_root=self.project) as session:
            window = session.window
            report = {
                "saved": window.save_settings(),
                "tip": window.tip_panel.text(),
            }
        self.assertTrue(report["saved"], report["tip"])
        self.assertEqual(
            self.fingerprint(desktop), before, "the desktop program's settings were touched"
        )
        # Proof that Save wrote somewhere: otherwise the check above means nothing.
        self.assertTrue(os.path.isfile(self.vr_settings), "Save wrote no VR settings")

    def test_a_saved_file_naming_retired_folders_drops_them_on_save(self):
        """Folder settings nothing reads any more are set aside when VR Config
        loads its file, so a save does not write them back. Everything else
        in the file is kept."""
        retired = sorted({"LOGO_DIR", "CLUSTER_ALIGNMENT_DIR", "CLUSTER_LABEL_DIR"}
                         | _bootstrap_vr.DEPRECATED_DIRECTORY_KEYS)
        os.makedirs(os.path.dirname(self.vr_settings))
        with open(self.vr_settings, "w", encoding="utf-8") as handle:
            json.dump({
                **{key: "$analysis_result$/Old_" + key for key in retired},
                "VR_HOST": "10.0.0.5", "VR_PORT": 6123, "INPUT_FILE_DIR": "My_Inputs",
            }, handle)
        with vr_config_session(project_root=self.project) as session:
            window = session.window
            namespace = session.namespace
            loaded = window._read_custom_settings()
            module_level = [key for key in retired if key in namespace]
            profile = {key: "legacy/path" for key in retired}
            profile["INPUT_FILE_DIR"] = "Profile_Inputs"
            normalized = window._normalize_profile_data("directories", profile)
            folder = window._saved_config_root() / "directories"
            folder.mkdir(parents=True)
            (folder / "old.json").write_text(json.dumps(profile), encoding="utf-8")
            named = window._named_profile_data("directories", "old")
            saved_ok = window.save_settings()
            report = {
                "loaded": sorted(loaded), "module_level": module_level,
                "normalized": sorted(normalized), "profile_dir": normalized["INPUT_FILE_DIR"],
                "named": sorted(named), "named_dir": named["INPUT_FILE_DIR"],
                "saved": saved_ok, "tip": window.tip_panel.text(),
                "custom": sorted(window._custom_settings),
            }
        self.assertTrue(report["saved"], report["tip"])
        # The loader that feeds Save, the module-level one, and both profile readers.
        self.assertEqual(set(report["loaded"]) & set(retired), set())
        self.assertEqual(report["module_level"], [])
        self.assertEqual(set(report["normalized"]) & set(retired), set())
        self.assertEqual(set(report["named"]) & set(retired), set())
        self.assertEqual(report["profile_dir"], "Profile_Inputs")
        self.assertEqual(report["named_dir"], "Profile_Inputs")
        self.assertEqual(set(report["custom"]) & set(retired), set())
        with open(self.vr_settings, encoding="utf-8") as handle:
            saved = json.load(handle)
        self.assertEqual(set(saved) & set(retired), set())
        self.assertEqual(saved["VR_HOST"], "10.0.0.5")
        self.assertIn(str(saved["VR_PORT"]), ("6123", "6123.0"))
        self.assertEqual(saved["INPUT_FILE_DIR"], "My_Inputs")

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

        What follows an alias is written with the platform's own separator,
        so the test holds on Windows (a backslash, as a Windows settings file
        has it) and elsewhere alike: a backslash inside a POSIX path is part
        of a file name, not a separator, and the resolver rightly keeps it.
        """
        relative = {
            "CACHE_FILE_DIR": "Cache_Files_VR",
            "SAVED_LAYOUT_DIR": os.sep.join(("$cache_file$", "Saved_Layouts")),
            "INPUT_FILE_DIR": "Input_Files",
            "ANALYSIS_RESULT_DIR": "Analysis_Results",
            "NODE_FASTA_FILE": os.sep.join(("$input_file$", "Sequence_Sets", "set.fasta")),
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
        }.items():
            with self.subTest(key=key):
                self.assertEqual(os.path.normcase(os.path.normpath(values[key])),
                                 os.path.normcase(os.path.join(root, *parts)))
        self.assertEqual(os.path.normcase(values["VR_APP_DIR"]),
                         os.path.normcase(os.path.join(_bootstrap_vr.OPT_VR_DIR, "player")))

    def test_the_retired_folder_settings_are_not_defaults_any_more(self):
        """LOGO_DIR, CLUSTER_ALIGNMENT_DIR and CLUSTER_LABEL_DIR named folders
        nothing reads: the commands name their own, as module constants."""
        import Settings_VR
        from desktop.Viewer_State import DEFAULTS

        values = self._settings_from({})
        for key in ("LOGO_DIR", "CLUSTER_ALIGNMENT_DIR", "CLUSTER_LABEL_DIR"):
            with self.subTest(key=key):
                self.assertIn(key, _bootstrap_vr.DEPRECATED_DIRECTORY_KEYS)
                self.assertNotIn(key, Settings_VR.VR_DEFAULTS)
                self.assertNotIn(key, values)
        # The one list both loaders drop, so no default can be one of its keys.
        retired = _bootstrap_vr.DEPRECATED_DIRECTORY_KEYS
        self.assertTrue(retired.isdisjoint(DEFAULTS))
        self.assertTrue(retired.isdisjoint(Settings_VR.VR_DEFAULTS))
        self.assertIn("HISTORY_DIR", Settings_VR.VR_DEFAULTS, "the folder that stays")

    def test_a_saved_file_naming_retired_folders_loads_without_them(self):
        """An older settings file still holds them; the viewer neither keeps
        them nor loses what else the file says."""
        retired = {"LOGO_DIR", "CLUSTER_ALIGNMENT_DIR", "CLUSTER_LABEL_DIR"} | _bootstrap_vr.DEPRECATED_DIRECTORY_KEYS
        document = {key: os.path.join("$analysis_result$", "Old_" + key) for key in retired}
        document.update({"VR_PORT": "6123", "HISTORY_DIR": "My_History"})
        values = self._settings_from(document)
        for key in retired:
            with self.subTest(key=key):
                self.assertNotIn(key, values)
        self.assertEqual(values["VR_PORT"], 6123)
        self.assertEqual(os.path.normcase(values["HISTORY_DIR"]),
                         os.path.normcase(os.path.join(_bootstrap_vr.PROJECT_ROOT, "My_History")))
        self.assertEqual(os.path.normcase(values["CACHE_FILE_DIR"]),
                         os.path.normcase(os.path.join(_bootstrap_vr.PROJECT_ROOT, "Cache_Files_VR")))

    def test_absolute_directories_are_left_alone(self):
        """An external data store is a supported choice, not a mistake."""
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
        with vr_config_session() as session:
            window = session.window
            window.inputs["VR_APP_DIR"].setText(build_dir)
            window.inputs["VR_HOST"].setText(host)
            window.inputs["VR_PORT"].setValue(port)
            return {
                "text": window.inputs["VR_APP_DIR"].toolTip(),
                "found": window._bridge_client_found,
                "host": window.inputs["VR_HOST"].text(),
                "port": window.inputs["VR_PORT"].value(),
                "editable": [window.inputs[key].isEnabled() for key in ("VR_HOST", "VR_PORT")],
            }

    def test_note_text_is_decided_without_qt(self):
        """The wording is a pure function, so it is worth pinning directly.

        It is a Message, whose str() is the English the tests pin; the window
        shows it translated.
        """
        foreign = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, foreign, ignore_errors=True)
        open(os.path.join(foreign, "EMAP-SSN-VR.exe"), "w").close()
        with vr_config_session() as session:
            namespace = session.namespace
            decide = namespace["bridge_note_text"]
            player = os.path.join(str(namespace["OPT_VR_DIR"]), "player")
            report = {
                "missing": str(decide(None, "127.0.0.1", 5005)),
                "match": str(decide(("127.0.0.1", 5005), "127.0.0.1", 5005)),
                "differs": str(decide(("127.0.0.1", 5005), "127.0.0.1", 6000)),
                "foreign": str(decide(None, "127.0.0.1", 5005, build_dir=foreign)),
                "player": str(decide(None, "127.0.0.1", 5005, build_dir=player)),
            }
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
        with vr_config_session() as session:
            window = session.window
            namespace = session.namespace
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
            with mock.patch.object(namespace["Player_Build_VR"], "read_endpoint",
                                   side_effect=PermissionError("unreadable build")):
                window._apply_profile_data(tab, profile)
                unreadable = state()
            report = {
                "found": found, "saved": saved, "missing": missing,
                "read_only": read_only, "unreadable": unreadable,
            }
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
        with vr_config_session() as session:
            window = session.window
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
                        reports.append({
                            "port": fresh.inputs["VR_PORT"].value(),
                            "enabled": fresh.inputs["VR_PORT"].isEnabled(),
                            "tooltip": fresh.inputs["VR_APP_DIR"].toolTip(),
                        })
                    finally:
                        fresh._cache_recheck_timer.stop()
                        fresh.close()
                        fresh.deleteLater()
        for item, port in zip(reports, (7001, 7002)):
            with self.subTest(port=port):
                self.assertEqual(item["port"], 6000, "the saved port is the user's")
                self.assertTrue(item["enabled"])
                self.assertIn(f"127.0.0.1:{port}", item["tooltip"])

    def test_choosing_a_folder_describes_its_client(self):
        """Picking a folder is the moment the user says which client they mean."""
        folder = self.client_folder(host="127.0.0.1", port=5005)
        with vr_config_session() as session:
            from PySide6.QtWidgets import QFileDialog, QPushButton

            window = session.window
            window.inputs["VR_HOST"].setText("10.0.0.5")
            window.inputs["VR_PORT"].setValue(6000)
            field = window.inputs["VR_APP_DIR"]
            browse = [b for b in field.parentWidget().findChildren(QPushButton)
                      if b.text() == "Browse"]
            with mock.patch.object(QFileDialog, "getExistingDirectory", return_value=folder):
                browse[0].click()
            report = {
                "browse_buttons": len(browse),
                "host": window.inputs["VR_HOST"].text(),
                "port": window.inputs["VR_PORT"].value(),
                "found": window._bridge_client_found,
                "tooltip": field.toolTip(),
            }
        self.assertEqual(report["browse_buttons"], 1)
        self.assertEqual((report["host"], report["port"]), ("10.0.0.5", 6000))
        self.assertTrue(report["found"])
        self.assertIn("127.0.0.1:5005", report["tooltip"])

    def test_a_unity_era_folder_setting_moves_to_the_installed_client(self):
        """Settings saved before the Godot client name the old unity/ folder."""
        with vr_config_session() as session:
            window = session.window
            namespace = session.namespace
            normalized = window._normalize_profile_data("visual_effects", {"VR_APP_DIR": "unity"})
            custom = window._normalize_profile_data("visual_effects", {"VR_APP_DIR": "E:/elsewhere/unity"})
            report = {
                "migrated": normalized["VR_APP_DIR"],
                "chosen": custom["VR_APP_DIR"],
                "default": namespace["VR_PROFILE_DEFAULTS"]["VR_APP_DIR"],
            }
        self.assertEqual(report["migrated"], "player")
        self.assertEqual(report["chosen"], "E:/elsewhere/unity", "a chosen folder is left alone")
        self.assertEqual(report["default"], "player")


class QuitWithClientTests(unittest.TestCase):
    """The VR-only control for whether the viewer outlives the headset app."""

    def test_it_is_a_switch_with_its_own_label(self):
        with vr_config_session() as session:
            from PySide6.QtWidgets import QPushButton

            window = session.window
            namespace = session.namespace
            widget = window.inputs["EXIT_WITH_UNITY"]
            report = {
                "is_button": isinstance(widget, QPushButton),
                "checkable": widget.isCheckable(),
                "label": window.labels["EXIT_WITH_UNITY"].text(),
                "declared_default": namespace["VR_PROFILE_DEFAULTS"]["EXIT_WITH_UNITY"],
            }
        self.assertTrue(report["is_button"], "asked for a button, not a checkbox")
        self.assertTrue(report["checkable"])
        self.assertEqual(report["label"], "Quit with VR Client:")
        self.assertIs(report["declared_default"], True, "killing is the default")

    def test_both_positions_round_trip(self):
        with vr_config_session() as session:
            window = session.window
            widget = window.inputs["EXIT_WITH_UNITY"]
            readings = {}
            for state in (False, True):
                widget.setChecked(state)
                readings[str(state)] = {
                    "value": window._widget_profile_value("EXIT_WITH_UNITY"),
                    "text": widget.text(),
                }
        self.assertIs(readings["False"]["value"], False)
        self.assertIs(readings["True"]["value"], True)
        # The pill has to say which way it is pointing.
        self.assertEqual(readings["False"]["text"], "OFF")
        self.assertEqual(readings["True"]["text"], "ON")

    def test_launch_snapshot_preserves_client_settings_in_a_fresh_viewer_process(self):
        with vr_config_session() as session:
            window = session.window
            namespace = session.namespace
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
                        "import sys, json; sys.path.insert(0, "
                        + repr(str(namespace["_bootstrap_vr"].VR_SRC_DIR))
                        + "); import EMAPSSN_Viewer_VR as viewer; "
                        "print('@@' + json.dumps({'exit': viewer.should_exit_with_unity(), "
                        "'values': {k: getattr(viewer.cfg, k) for k in "
                        + repr(list(namespace["VR_PROFILE_DEFAULTS"]))
                        + "}}))"
                    )
                    env = os.environ.copy()
                    env.pop("SSN_VIEWER_SETTINGS_PATH", None)
                    result = subprocess.run(
                        [sys.executable, "-c", script, "--settings", path],
                        capture_output=True, text=True, env=env, timeout=120,
                    )
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    reports.append(json.loads(result.stdout.split("@@", 1)[1]))
                finally:
                    os.unlink(path)
        for checked, item in zip((False, True), reports):
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
        with vr_config_session() as session:
            in_profile = "EXIT_WITH_UNITY" in session.namespace["VR_VISUAL_PROFILE_DEFAULTS"]
        self.assertTrue(in_profile)


class VRAtomicWriteTests(unittest.TestCase):
    """_atomic_write_json clears temporary copies an interrupted save left behind."""

    def test_a_save_removes_stale_temporary_copies_but_not_recent_ones(self):
        with vr_config_session() as session:
            namespace = session.namespace
            with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
                folder = Path(tmp)
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
                files = sorted(path.name for path in folder.iterdir())
                saved = json.loads(target.read_text(encoding="utf-8"))
        self.assertEqual(saved, {"NODE_SIZE": 12})
        self.assertEqual(files, sorted([
            "viewer_settings_vr.json",
            ".viewer_settings_vr.json.inprogress.partial",
            ".layout_settings.json.1234.partial",
        ]))


class ModuleSettingsLoadTests(unittest.TestCase):
    """What the module's own load of a saved settings file leaves in its names."""

    @staticmethod
    def _load(document):
        script = (
            "import json, sys; sys.path.insert(0, {src!r}); import {module} as c; "
            "print(json.dumps([c.NODE_FASTA_FILE, c.INPUT_HDF5, c.MSA_FILE, "
            "getattr(c, 'SEQUENCES_FILE', None), getattr(c, 'SEQUENCE_SET', None)]))"
        ).format(src=VR_SRC, module="EMAPSSN_Config_VR")
        with tempfile.TemporaryDirectory() as folder:
            settings = os.path.join(folder, "settings.json")
            with open(settings, "w", encoding="utf-8") as handle:
                json.dump(document, handle)
            env = os.environ.copy()
            env["SSN_VIEWER_SETTINGS_PATH"] = settings
            env["SSN_APP_SETTINGS_PATH"] = os.path.join(folder, "app_settings.json")
            env["SSN_NO_CONSOLE_CAPTURE"] = "1"
            env["QT_QPA_PLATFORM"] = "offscreen"
            env.pop("SSN_VIEWER_EXPLICIT_SETTINGS", None)
            done = subprocess.run(
                [sys.executable, "-c", script], cwd=OPT_VR, env=env,
                capture_output=True, text=True, timeout=120,
            )
        assert done.returncode == 0, done.stderr
        return json.loads(done.stdout.strip().splitlines()[-1])

    def test_an_empty_network_stays_empty(self):
        fasta, network, _, _, _ = self._load({"NODE_FASTA_FILE": "Set_A.fasta", "INPUT_HDF5": ""})
        self.assertEqual(fasta, "Set_A.fasta")
        self.assertEqual(network, "")

    def test_placeholder_names_are_left_as_written(self):
        _, network, msa, _, _ = self._load({
            "NODE_FASTA_FILE": "Set_A.fasta",
            "INPUT_HDF5": "None_[E1_RA]_network.h5",
            "MSA_FILE": "None_[E1_RA]_alignment.fasta",
        })
        self.assertEqual(network, "None_[E1_RA]_network.h5")
        self.assertEqual(msa, "None_[E1_RA]_alignment.fasta")

    def test_the_sequence_names_still_follow_the_fasta(self):
        fasta, _, _, sequences, name = self._load({"NODE_FASTA_FILE": "Set_A.fasta"})
        self.assertEqual(sequences, fasta)
        self.assertEqual(name, "Set_A")


if __name__ == "__main__":
    unittest.main()
