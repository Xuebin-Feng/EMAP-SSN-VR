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

"""Regression tests for the VR viewer.

Run from the opt_vr directory:

    ../.venv/Scripts/python.exe -m unittest discover -s tests -t .

These lock in the behaviours that are easy to break silently: the settings
layer's alias resolution and type coercion, sys.path precedence between
opt_vr and the main program, the command package's override/fall-through, the
shared Command_Engine API upstream commands depend on, and the load-only
layout cache consumer.
"""

import io
import json
import os
import pathlib
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

#: The submodule root; VR_SRC is its module tree, mirroring the main
#: program's project-root/src split.
OPT_VR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VR_SRC = os.path.join(OPT_VR, "src")
if VR_SRC not in sys.path:
    sys.path.insert(0, VR_SRC)

# A neutral settings file keeps these tests independent of whatever the user
# last saved in the project's viewer_settings.json.
_NEUTRAL = tempfile.NamedTemporaryFile(
    "w", suffix=".json", delete=False, encoding="utf-8"
)
json.dump({}, _NEUTRAL)
_NEUTRAL.close()
os.environ["SSN_VIEWER_SETTINGS_PATH"] = _NEUTRAL.name

import numpy as np  # noqa: E402

import _bootstrap_vr  # noqa: E402
import Command_Engine  # noqa: E402
import Settings_VR as cfg  # noqa: E402

with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
    import EMAPSSN_Viewer_VR as vr_viewer  # noqa: E402

_bootstrap_vr.install_settings_alias(cfg)


def build_viewer(n_nodes=12, seed=0):
    """A populated HeadlessViewer, with no socket and no Unity process."""
    rng = np.random.default_rng(seed)
    headers = [f"sp|P{index:05d}|PROT{index}_TEST" for index in range(n_nodes)]
    full_headers = [f"{h} Test protein {i}" for i, h in enumerate(headers)]
    metadata = {
        "Length": {
            "type": "number",
            "values": rng.integers(100, 500, n_nodes).astype(np.int32),
        },
    }
    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
        viewer = vr_viewer.HeadlessViewer(n_nodes, headers, full_headers, metadata)
    viewer.pos = (rng.random((n_nodes, 3)).astype(np.float32) - 0.5) * 50.0
    viewer.original_pos = viewer.pos.copy()
    viewer.edges = np.array(
        [(i, (i + 1) % n_nodes) for i in range(n_nodes)], dtype=np.int32
    )
    viewer.edge_scores = np.ones(len(viewer.edges), dtype=np.float32)
    viewer.selected_indices = []
    return viewer


def run_command(viewer, command_string):
    buffer = io.StringIO()
    with redirect_stdout(buffer), redirect_stderr(buffer):
        viewer.process_command(command_string, record_history=False)
    return buffer.getvalue()


class BootstrapTests(unittest.TestCase):
    def test_opt_vr_precedes_the_main_program_on_sys_path(self):
        """opt_vr/src must win, or every local override is ignored."""
        self.assertIn(_bootstrap_vr.VR_SRC_DIR, sys.path)
        self.assertIn(_bootstrap_vr.SRC_DIR, sys.path)
        # First occurrence is what import resolution actually uses.
        self.assertLess(
            sys.path.index(_bootstrap_vr.VR_SRC_DIR),
            sys.path.index(_bootstrap_vr.SRC_DIR),
        )
        # And it must appear exactly once, or a stale duplicate could shadow it.
        self.assertEqual(sys.path.count(_bootstrap_vr.VR_SRC_DIR), 1)

    def test_settings_alias_is_registered_for_upstream_modules(self):
        """Importing Settings_VR must be enough to register the alias.

        Upstream modules do `import EMAPSSN_Config as cfg`. If the real one
        loads first it drags PySide6 into this headless process, so the alias
        must not depend on any caller getting its import order right.
        """
        self.assertIs(sys.modules.get("EMAPSSN_Config"), cfg)

    def test_alignment_manager_comes_from_the_main_program(self):
        """The local fork was deleted; a stale copy must not come back."""
        import Alignment_Manager

        self.assertIn("src", Alignment_Manager.__file__)
        self.assertFalse(
            os.path.exists(os.path.join(VR_SRC, "Alignment_Manager.py")),
            "opt_vr must not carry its own Alignment_Manager fork",
        )


class SettingsTests(unittest.TestCase):
    def test_file_paths_resolve_directory_aliases(self):
        """INPUT_HDF5 and friends are stored as "$input_file$/..." strings."""
        values = {
            "INPUT_FILE_DIR": os.path.join("X:", os.sep, "data"),
            "INPUT_HDF5": "$input_file$/Networks_EValues/net.h5",
            "MSA_FILE": "$input_file$/Multiple_Alignments/msa_sparse.h5",
        }
        resolved = cfg._resolve_alias(values["INPUT_HDF5"], values)
        self.assertNotIn("$input_file$", resolved)
        self.assertTrue(resolved.endswith("net.h5"))

    def test_values_are_coerced_to_their_upstream_types(self):
        """viewer_settings.json round-trips through Qt widgets, so ints arrive
        as strings and a null threshold arrives as the text "None"."""
        self.assertEqual(cfg._coerce("NODE_SIZE", "15"), 15)
        self.assertIsInstance(cfg._coerce("NODE_SIZE", "15"), int)
        self.assertEqual(cfg._coerce("EDGE_WIDTH", "1.5"), 1.5)
        self.assertIs(cfg._coerce("UMAP_MODE", "false"), False)
        self.assertIsNone(cfg._coerce("SIMILARITY_THRESHOLD", "None"))
        self.assertEqual(cfg._coerce("TOP_EDGE_PERCENT", "5.0"), 5.0)

    def test_renamed_upstream_key_is_republished(self):
        """The VR code and Unity client still use NEIGHBOR_COLOR."""
        self.assertIn("NEIGHBOR_COLOR", cfg.LEGACY_KEY_SOURCES)
        self.assertEqual(cfg.LEGACY_KEY_SOURCES["NEIGHBOR_COLOR"], "INITIAL_NODE_COLOR")

    def test_no_qt_is_imported(self):
        self.assertFalse(any(name.startswith("PySide6") for name in sys.modules))
        self.assertFalse(any(name.startswith("vispy") for name in sys.modules))


class CommandPackageTests(unittest.TestCase):
    def test_local_commands_win_and_upstream_falls_through(self):
        import importlib

        import commands

        self.assertGreaterEqual(len(commands.__path__), 2)
        local = importlib.import_module("commands.color")
        self.assertIn("opt_vr", local.__file__)

    def test_every_local_command_exposes_run(self):
        import importlib

        directory = os.path.join(VR_SRC, "commands")
        names = sorted(
            name[:-3]
            for name in os.listdir(directory)
            if name.endswith(".py") and not name.startswith("_")
        )
        self.assertTrue(names)
        for name in names:
            with self.subTest(command=name):
                module = importlib.import_module(f"commands.{name}")
                self.assertTrue(
                    callable(getattr(module, "run", None)),
                    f"commands/{name}.py must expose run(viewer, args)",
                )

    def test_unknown_command_is_reported_as_unknown(self):
        viewer = build_viewer()
        self.assertIn("Unknown command", run_command(viewer, "definitelynotacommand"))

    def test_help_lists_commands(self):
        viewer = build_viewer()
        output = run_command(viewer, "help")
        self.assertIn("EMAP-SSN VR viewer commands", output)
        self.assertIn("color", output)

    def test_help_prefers_a_local_override_description(self):
        """A shadowed command must not advertise upstream's behaviour."""
        viewer = build_viewer()
        output = run_command(viewer, "help zoom")
        self.assertIn("headset", output.lower())
        self.assertNotIn("canvas aspect ratio", output)


class CommandEngineAPITests(unittest.TestCase):
    """The surface upstream commands call unconditionally."""

    def test_outcome_reporting_is_a_safe_no_op(self):
        viewer = build_viewer()
        self.assertIsNone(Command_Engine.command_succeeded(viewer, "done"))
        self.assertIsNone(Command_Engine.command_failed(viewer, "nope"))
        self.assertIsNone(Command_Engine.command_cancelled(viewer, "stopped"))
        self.assertIsNone(Command_Engine.command_artifact(viewer, "file.txt"))

    def test_print_help_accepts_upstream_keywords_and_prints_all_lines(self):
        viewer = build_viewer()
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            Command_Engine.print_help(viewer, "line one\nline two")
        printed = buffer.getvalue()
        self.assertIn("line one", printed)
        self.assertIn("line two", printed)

        buffer = io.StringIO()
        with redirect_stdout(buffer):
            Command_Engine.print_help(
                viewer, "shown", terminal_msg="override", report_message=False
            )
        self.assertIn("override", buffer.getvalue())

    def test_get_selected_mask(self):
        viewer = build_viewer()
        viewer.selected_indices = [1, 3, 5]
        mask = Command_Engine.get_selected_mask(viewer)
        self.assertEqual(mask.dtype, np.dtype(bool))
        self.assertEqual(sorted(np.flatnonzero(mask).tolist()), [1, 3, 5])

    def test_get_selected_mask_ignores_out_of_range_indices(self):
        viewer = build_viewer(n_nodes=4)
        viewer.selected_indices = [0, 99, -1, "bad"]
        mask = Command_Engine.get_selected_mask(viewer)
        self.assertEqual(np.flatnonzero(mask).tolist(), [0])

    def test_get_alignment_mapping_shape(self):
        viewer = build_viewer()
        mapping, valid = Command_Engine.get_alignment_mapping(viewer)
        self.assertEqual(mapping.shape, (viewer.n_nodes,))
        self.assertEqual(valid.ndim, 1)

    def test_selection_token_in_expressions(self):
        viewer = build_viewer()
        viewer.selected_indices = [2, 4, 6]
        mapping, valid = Command_Engine.get_alignment_mapping(viewer)
        mask = Command_Engine.parse_advanced_expression(
            "$sele$", mapping, valid, viewer.full_headers,
            selection_mask=Command_Engine.get_selected_mask(viewer),
        )
        self.assertEqual(sorted(np.flatnonzero(mask).tolist()), [2, 4, 6])

        negated = Command_Engine.parse_advanced_expression(
            "!$sele$", mapping, valid, viewer.full_headers,
            selection_mask=Command_Engine.get_selected_mask(viewer),
        )
        self.assertEqual(int(negated.sum()), viewer.n_nodes - 3)

    def test_no_command_spills_the_selection_to_disk(self):
        """$sele$ must resolve in memory.

        Seven commands used to write every selected header to
        HEADER_LIST_DIR/_sele.txt and read it back as @_sele.txt@, which wrote
        into the user's shared header-list directory on every invocation.
        """
        import Settings_VR as settings

        original = getattr(settings, "HEADER_LIST_DIR", None)
        with tempfile.TemporaryDirectory() as folder:
            settings.HEADER_LIST_DIR = folder
            try:
                for command in (
                    "color red $sele$",
                    "hide $sele$",
                    "spectrum $sele$ prop:Length",
                    "group $sele$ g1",
                    "select $sele$",
                ):
                    viewer = build_viewer()
                    viewer.selected_indices = [1, 2, 3]
                    run_command(viewer, command)
                    self.assertEqual(
                        os.listdir(folder), [],
                        f"'{command}' wrote into the header-list directory",
                    )
            finally:
                if original is not None:
                    settings.HEADER_LIST_DIR = original

    def test_selection_token_targets_exactly_the_selection(self):
        viewer = build_viewer()
        viewer.selected_indices = [0, 1]
        run_command(viewer, "color red $sele$")
        red = np.all(
            np.isclose(viewer.current_colors[:, :3], [1.0, 0.0, 0.0]), axis=1
        )
        self.assertEqual(sorted(np.flatnonzero(red).tolist()), [0, 1])

    def test_selection_token_without_a_mask_is_empty_not_an_error(self):
        viewer = build_viewer()
        mapping, valid = Command_Engine.get_alignment_mapping(viewer)
        mask = Command_Engine.parse_advanced_expression(
            "$sele$", mapping, valid, viewer.full_headers
        )
        self.assertEqual(int(mask.sum()), 0)


class LayoutCacheConsumerTests(unittest.TestCase):
    """opt_vr consumes a cache; it must never generate one."""

    def _write_cache(self, path, dimensions, n_nodes=4):
        import h5py

        headers = [f"sp|P{i:05d}|PROT{i}_TEST" for i in range(n_nodes)]
        positions = np.arange(n_nodes * dimensions, dtype=np.float32).reshape(
            n_nodes, dimensions
        )
        with h5py.File(path, "w") as handle:
            handle.attrs["layout_dimensions"] = dimensions
            handle.create_dataset(
                "headers",
                data=np.asarray(headers, dtype=object),
                dtype=h5py.string_dtype(encoding="utf-8"),
            )
            handle.create_dataset("positions", data=positions)
        return headers

    def test_three_dimensional_cache_loads(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "version_00.h5")
            headers = self._write_cache(path, 3)
            original = cfg.TARGET_CACHE_FILE
            try:
                cfg.TARGET_CACHE_FILE = path
                with redirect_stdout(io.StringIO()):
                    result = vr_viewer.load_layout_cache()
            finally:
                cfg.TARGET_CACHE_FILE = original
            positions, _, _, n_nodes, loaded_headers = result[:5]
            self.assertEqual(positions.shape, (len(headers), 3))
            self.assertEqual(n_nodes, len(headers))
            self.assertEqual(loaded_headers, headers)

    def test_two_dimensional_cache_is_lifted_to_the_z_plane(self):
        """Unity needs three floats per node, so a 2D cache must not crash."""
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "version_00.h5")
            self._write_cache(path, 2)
            original = cfg.TARGET_CACHE_FILE
            try:
                cfg.TARGET_CACHE_FILE = path
                buffer = io.StringIO()
                with redirect_stdout(buffer):
                    result = vr_viewer.load_layout_cache()
            finally:
                cfg.TARGET_CACHE_FILE = original
            positions = result[0]
            self.assertEqual(positions.shape[1], 3)
            self.assertTrue(np.all(positions[:, 2] == 0.0))
            self.assertIn("2D layout cache", buffer.getvalue())

    def test_positions_serialise_to_the_unity_payload_size(self):
        viewer = build_viewer(n_nodes=7)
        payload = viewer.pos.astype("<f4").tobytes()
        self.assertEqual(len(payload), 12 * viewer.n_nodes)

    def test_missing_cache_selection_explains_how_to_generate_one(self):
        original = cfg.TARGET_CACHE_FILE
        try:
            cfg.TARGET_CACHE_FILE = None
            with self.assertRaises(SystemExit) as raised:
                with redirect_stdout(io.StringIO()):
                    vr_viewer.load_layout_cache()
        finally:
            cfg.TARGET_CACHE_FILE = original
        self.assertIn("Layout_Cache_Generator", str(raised.exception))

    def test_unpinned_cache_is_resolved_from_the_shared_settings(self):
        """With nothing pinned, defer to the resolver the desktop viewer uses.

        opt_vr used to demand an explicit TARGET_CACHE_PATH and refuse to start
        without one, even though the Config GUI already describes the network.
        """
        import tempfile
        import unittest.mock as mock

        original = cfg.TARGET_CACHE_FILE
        with tempfile.TemporaryDirectory() as folder:
            cache = os.path.join(folder, "version_00.h5")
            open(cache, "w").close()
            try:
                cfg.TARGET_CACHE_FILE = None
                with mock.patch.object(
                    vr_viewer, "resolve_selected_cache", return_value=(cache, None)
                ):
                    self.assertEqual(vr_viewer._resolve_cache_path(), cache)
            finally:
                cfg.TARGET_CACHE_FILE = original

    def test_three_dimensional_layouts_prefer_the_3d_folder(self):
        """The generator appends _3D; the shared resolver does not add it."""
        import tempfile
        import unittest.mock as mock

        original_target = cfg.TARGET_CACHE_FILE
        original_dims = getattr(cfg, "LAYOUT_DIMENSIONS", 2)
        with tempfile.TemporaryDirectory() as root:
            flat = os.path.join(root, "Network_Top5.0Pct")
            solid = flat + "_3D"
            for folder in (flat, solid):
                os.makedirs(folder)
                open(os.path.join(folder, "version_00.h5"), "w").close()
            try:
                cfg.TARGET_CACHE_FILE = None
                cfg.LAYOUT_DIMENSIONS = 3
                with mock.patch.object(
                    vr_viewer,
                    "resolve_selected_cache",
                    return_value=(os.path.join(flat, "version_00.h5"), None),
                ):
                    resolved = vr_viewer._resolve_cache_path()
                self.assertEqual(os.path.dirname(resolved), solid)
            finally:
                cfg.TARGET_CACHE_FILE = original_target
                cfg.LAYOUT_DIMENSIONS = original_dims

    def test_bracketed_cache_folders_are_found(self):
        """Cache folders embed the model tag in brackets, which glob eats."""
        import tempfile

        original = cfg.TARGET_CACHE_FILE
        with tempfile.TemporaryDirectory() as root:
            folder = os.path.join(root, "Network_[E1_RA]_Top5.0Pct")
            os.makedirs(folder)
            cache = os.path.join(folder, "version_00.h5")
            open(cache, "w").close()
            try:
                cfg.TARGET_CACHE_FILE = folder
                self.assertEqual(vr_viewer._resolve_cache_path(), cache)
            finally:
                cfg.TARGET_CACHE_FILE = original


class LaunchHandoffTests(unittest.TestCase):
    """The GUI hands each launch a private settings snapshot on the argv.

    opt_vr implements the same --settings contract as the desktop viewer, which
    is what lets EMAPSSN_Config's --viewer option point at either front end
    without special-casing one of them.
    """

    def setUp(self):
        self._saved = os.environ.get("SSN_VIEWER_SETTINGS_PATH")

    def tearDown(self):
        if self._saved is None:
            os.environ.pop("SSN_VIEWER_SETTINGS_PATH", None)
        else:
            os.environ["SSN_VIEWER_SETTINGS_PATH"] = self._saved

    def test_settings_argument_sets_the_path_settings_reads(self):
        _bootstrap_vr.apply_settings_argument(["EMAPSSN_Viewer_VR.py", "--settings", "snap.json"])
        self.assertEqual(os.environ["SSN_VIEWER_SETTINGS_PATH"], "snap.json")

    def test_equals_form_is_accepted(self):
        _bootstrap_vr.apply_settings_argument(["EMAPSSN_Viewer_VR.py", "--settings=snap.json"])
        self.assertEqual(os.environ["SSN_VIEWER_SETTINGS_PATH"], "snap.json")

    def test_snapshot_is_only_scheduled_for_deletion_when_asked(self):
        kept = _bootstrap_vr.apply_settings_argument(["EMAPSSN_Viewer_VR.py", "--settings", "a.json"])
        self.assertIsNone(kept)
        doomed = _bootstrap_vr.apply_settings_argument(
            ["EMAPSSN_Viewer_VR.py", "--settings", "b.json", "--delete-settings"]
        )
        self.assertEqual(doomed, "b.json")

    def test_plain_launch_touches_nothing(self):
        os.environ.pop("SSN_VIEWER_SETTINGS_PATH", None)
        self.assertIsNone(_bootstrap_vr.apply_settings_argument(["EMAPSSN_Viewer_VR.py"]))
        self.assertNotIn("SSN_VIEWER_SETTINGS_PATH", os.environ)

    def test_snapshot_is_deleted_once(self):
        import tempfile

        handle = tempfile.NamedTemporaryFile(
            "w", suffix=".json", delete=False, encoding="utf-8"
        )
        handle.close()
        previous = _bootstrap_vr.SETTINGS_SNAPSHOT_TO_DELETE
        try:
            _bootstrap_vr.SETTINGS_SNAPSHOT_TO_DELETE = handle.name
            vr_viewer._consume_launch_snapshot()
            self.assertFalse(os.path.exists(handle.name))
            # Idempotent: a second call must not raise or delete anything else.
            vr_viewer._consume_launch_snapshot()
        finally:
            _bootstrap_vr.SETTINGS_SNAPSHOT_TO_DELETE = previous

    def test_gui_settings_document_is_decoded(self):
        """The GUI snapshot is encode_document output, not a flat mapping."""
        import tempfile

        from desktop.Viewer_State import DEFAULTS, encode_document

        document = encode_document("viewer", {**DEFAULTS, "NODE_SIZE": 17})
        handle = tempfile.NamedTemporaryFile(
            "w", suffix=".json", delete=False, encoding="utf-8"
        )
        json.dump(document, handle)
        handle.close()
        self.addCleanup(lambda: os.path.exists(handle.name) and os.unlink(handle.name))

        import Settings_VR

        self.assertEqual(Settings_VR._read_json(handle.name).get("NODE_SIZE"), 17)



class ViewerStateTests(unittest.TestCase):
    def test_viewer_exposes_positions_for_commands(self):
        """viewer.pos used to be missing, so `save` raised AttributeError."""
        viewer = build_viewer()
        self.assertTrue(hasattr(viewer, "pos"))
        self.assertEqual(viewer.pos.shape[1], 3)

    def test_terminal_run_flag_is_independent_of_the_unity_connection(self):
        viewer = build_viewer()
        self.assertTrue(viewer.running)
        self.assertFalse(getattr(viewer, "is_connected", False))

    def test_non_windows_terminal_fallback_exists(self):
        self.assertTrue(callable(getattr(vr_viewer, "_simple_terminal_loop", None)))


if __name__ == "__main__":
    unittest.main()
