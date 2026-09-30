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

"""The VR viewer opens a layout cache the way the desktop viewer does.

These lock in what the desktop viewer's load path does and the VR one used to
skip: the alignment offset, the source FASTA read through the sanitising
loader, metadata taken from the cache as it is, the saved session state, the
saved Distance Scale and the initial node colour.
"""

import hashlib
import importlib
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

OPT_VR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VR_SRC = os.path.join(OPT_VR, "src")
if VR_SRC not in sys.path:
    sys.path.insert(0, VR_SRC)

# A neutral settings file keeps these tests independent of whatever the user
# last saved; the first test module imported sets it for the whole run.
_NEUTRAL = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
json.dump({}, _NEUTRAL)
_NEUTRAL.close()
os.environ.setdefault("SSN_VIEWER_SETTINGS_PATH", _NEUTRAL.name)

import h5py  # noqa: E402
import numpy as np  # noqa: E402

import _bootstrap_vr  # noqa: E402
import Settings_VR as cfg  # noqa: E402

with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
    import EMAPSSN_Viewer_VR as vr_viewer  # noqa: E402
    import Viewer_Utils_VR  # noqa: E402

_bootstrap_vr.install_settings_alias(cfg)


def quietly(function, *args, **kwargs):
    """Call `function`, returning its result and everything it printed."""
    buffer = io.StringIO()
    with redirect_stdout(buffer), redirect_stderr(buffer):
        result = function(*args, **kwargs)
    return result, buffer.getvalue()


def make_viewer(n_nodes=4, metadata=None, full_headers=None):
    headers = full_headers or [f"node_{index}" for index in range(n_nodes)]
    viewer, _ = quietly(vr_viewer.HeadlessViewer, len(headers), headers, list(headers), metadata)
    return viewer


def run_command(viewer, command):
    return quietly(viewer.process_command, command, record_history=False)[1]


class SettingsPatch:
    """Set cfg attributes for one test and restore them afterwards."""

    def __init__(self, test, **values):
        for name, value in values.items():
            patcher = mock.patch.object(cfg, name, value, create=True)
            patcher.start()
            test.addCleanup(patcher.stop)


class AlignmentOffsetTests(unittest.TestCase):
    """ALIGNMENT_OFFSET numbers every reference-anchored position, as on the desktop."""

    def test_the_configured_offset_reaches_the_alignment(self):
        SettingsPatch(self, ALIGNMENT_OFFSET=7)
        with mock.patch.object(vr_viewer.Alignment_Manager, "Alignment_Manager") as manager:
            viewer = make_viewer()
            self.assertEqual(viewer.alignment_offset, 7)
            self.assertEqual(manager.call_args.kwargs["alignment_offset"], 7)

            # `reference` reloads through load_global_alignment, and `offset`
            # sets viewer.alignment_offset; the reload must keep it.
            viewer.alignment_offset = 3
            quietly(viewer.load_global_alignment)
            self.assertEqual(manager.call_args.kwargs["alignment_offset"], 3)

    def test_an_unusable_offset_reads_as_zero(self):
        for value in ("abc", None):
            with self.subTest(value=value):
                SettingsPatch(self, ALIGNMENT_OFFSET=value)
                with mock.patch.object(vr_viewer.Alignment_Manager, "Alignment_Manager") as manager:
                    viewer = make_viewer()
                self.assertEqual(viewer.alignment_offset, 0)
                self.assertEqual(manager.call_args.kwargs["alignment_offset"], 0)


class ViewerDefaultsTests(unittest.TestCase):
    def test_a_named_initial_colour_is_parsed_like_the_desktop(self):
        SettingsPatch(self, INITIAL_NODE_COLOR="red", NEIGHBOR_COLOR="red")
        viewer = make_viewer()
        np.testing.assert_allclose(viewer.current_colors[0], [1.0, 0.0, 0.0, 1.0])

    def test_the_saved_distance_scale_seeds_the_viewer(self):
        SettingsPatch(self, DISTANCE_SCALE=2.5)
        viewer = make_viewer()
        self.assertEqual(viewer.distance_scale, 2.5)
        self.assertEqual(viewer.get_transform_state()["distanceScale"], 2.5)

    def test_an_unusable_distance_scale_falls_back_to_one(self):
        for value in ("far", 0, -1.0, float("nan"), float("inf")):
            with self.subTest(value=value):
                SettingsPatch(self, DISTANCE_SCALE=value)
                viewer = make_viewer()
                self.assertEqual(viewer.distance_scale, 1.0)

    def test_metadata_is_taken_from_the_cache_as_it_is(self):
        """A group without Length is a deliberate deletion; nothing recreates it."""
        kda = {"type": "number", "values": np.array([10.0, 11.0, 12.0, 13.0])}
        viewer = make_viewer(metadata={"kDa": kda})
        self.assertEqual(list(viewer.metadata), ["kDa"])

    def test_length_is_ordered_first(self):
        values = {"type": "number", "values": np.arange(4, dtype=np.float64)}
        viewer = make_viewer(metadata={"pI": dict(values), "Length": dict(values)})
        self.assertEqual(list(viewer.metadata), ["Length", "pI"])

    def test_the_cache_filename_is_a_path(self):
        SettingsPatch(self, TARGET_CACHE_FILE=os.path.join("folder", "version_00.h5"))
        self.assertEqual(
            Viewer_Utils_VR.get_cache_filename(), os.path.join("folder", "version_00.h5")
        )


class SourceFastaTests(unittest.TestCase):
    """Sequences come from the sanitising loader every pipeline stage uses."""

    RAW_HEADER = "WP_012345678.1 hypothetical protein [Escherichia coli]"

    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(self.folder, ignore_errors=True))
        self.fasta = os.path.join(self.folder, "raw.fasta")
        with open(self.fasta, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(f">{self.RAW_HEADER}\nmkvlaagll*\n>P12345_clean\nMKTAYIAK\n")
        from utilities.Sequence_Utils import load_sanitized_fasta

        (self.canonical, _clean, _stats), _ = quietly(load_sanitized_fasta, self.fasta)

    def test_an_unsanitised_fasta_matches_the_cache_headers(self):
        SettingsPatch(self, NODE_FASTA_FILE=self.fasta)
        viewer = make_viewer(full_headers=list(self.canonical))
        self.assertNotEqual(self.canonical[0], self.RAW_HEADER)
        self.assertEqual(viewer.sequences_map[self.canonical[0]], "MKVLAAGLL")
        self.assertEqual(viewer._selected_fasta_records[0], (self.canonical[0], "MKVLAAGLL"))

        export = importlib.import_module("commands.export")
        records = export._get_in_memory_sequence_records(viewer)
        self.assertEqual(records[self.canonical[0]], "MKVLAAGLL")
        self.assertEqual(records["P12345_clean"], "MKTAYIAK")

    def test_a_missing_fasta_leaves_no_sequences(self):
        SettingsPatch(self, NODE_FASTA_FILE=os.path.join(self.folder, "absent.fasta"))
        viewer = make_viewer()
        self.assertEqual(viewer._selected_fasta_records, [])
        self.assertEqual(viewer.sequences_map, {})


class SessionRestoreTests(unittest.TestCase):
    """A version `save` wrote reopens with the session it saved."""

    N_NODES = 5

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(self.root, ignore_errors=True))
        SettingsPatch(self, NODE_SIZE=10.0)

    def publish(self, folder):
        """A 3D cache folder as the layout generator publishes one."""
        import Cache_Manifest

        compatibility = Cache_Manifest.build_compatibility(
            "a" * 64, "b" * 64, "alignment",
            alignment_score="global", normalization="alignment_length",
            similarity_threshold=0.4, layout_dimensions=3,
        )
        manifest = Cache_Manifest.build_manifest(
            {"basename": "set.fasta", "size_bytes": 10, "sha256": "a" * 64},
            {"basename": "network.h5", "size_bytes": 20, "sha256": "b" * 64},
            compatibility,
        )
        Cache_Manifest.write_manifest_atomic(folder, manifest)
        path = os.path.join(folder, "version_00.h5")
        headers = [f"node_{index}" for index in range(self.N_NODES)]
        with h5py.File(path, "w") as handle:
            handle.attrs["layout_dimensions"] = 3
            handle.attrs["cache_manifest_id"] = manifest["manifest_id"]
            handle.attrs["layout_compatibility_json"] = "{}"
            handle.attrs["layout_compatibility_id"] = hashlib.sha256(b"{}").hexdigest()
            handle.create_dataset(
                "headers", data=np.asarray(headers, dtype=object),
                dtype=h5py.string_dtype(encoding="utf-8"),
            )
            handle.create_dataset(
                "positions", data=np.arange(self.N_NODES * 3, dtype=np.float32).reshape(-1, 3)
            )
        return path

    def pinned(self, path):
        """Pin `path` for the rest of the test, as Save & Run pins a cache.

        open_layout_session rewrites both keys, and `save` resolves its folder
        from them, so they stay patched until the test ends.
        """
        for name, value in (("TARGET_CACHE_FILE", path), ("TARGET_CACHE_PATH", None)):
            patcher = mock.patch.object(cfg, name, value, create=True)
            patcher.start()
            self.addCleanup(patcher.stop)

    def open(self, path):
        self.pinned(path)
        return quietly(vr_viewer.open_layout_session)

    def write_state(self, path, **overrides):
        n = self.N_NODES
        state = {
            "colors": np.tile([1.0, 0.0, 0.0, 1.0], (n, 1)).astype(np.float32),
            "sizes": np.full(n, 20.0, dtype=np.float32),
            "shapes": ["square"] * n,
            "visible_mask": np.array([True, False, True, True, False]),
            "node_render_order": np.array([4, 3, 2, 1, 0], dtype=np.int32),
            "cluster_labels": np.array([0, 0, 1, 1, -1]),
        }
        state.update(overrides)
        with h5py.File(path, "a") as handle:
            for name, value in state.items():
                if name == "shapes":
                    handle.create_dataset(name, data=np.asarray(value, dtype=object),
                                          dtype=h5py.string_dtype(encoding="utf-8"))
                else:
                    handle.create_dataset(name, data=value)
            handle.attrs["base_node_size"] = 10.0
            handle.create_dataset("group_labels", data=json.dumps([["kinase"], [], [], ["kinase", "x"], []]))
            handle.attrs["last_cluster_params"] = json.dumps(["leiden", 1.0, 10])
            handle.create_dataset("custom_scores", data=np.arange(n, dtype=np.float64))
            notes = handle.create_dataset("custom_notes", data=json.dumps({"note": "kept"}))
            notes.attrs["is_json"] = True

    def test_the_saved_session_is_restored(self):
        folder = os.path.join(self.root, "Network_Score0.4_3D")
        os.makedirs(folder)
        path = self.publish(folder)
        self.write_state(path)
        viewer, _ = self.open(path)

        np.testing.assert_allclose(viewer.current_colors[:, 0], 1.0)
        np.testing.assert_allclose(viewer.current_sizes, 20.0)
        self.assertEqual(list(viewer.current_shapes), ["square"] * self.N_NODES)
        np.testing.assert_array_equal(viewer.visible_mask, [True, False, True, True, False])
        np.testing.assert_array_equal(viewer.node_render_order, [4, 3, 2, 1, 0])
        np.testing.assert_array_equal(viewer.cluster_labels, [0, 0, 1, 1, -1])
        self.assertEqual(viewer.group_labels[3], {"kinase", "x"})
        self.assertEqual(viewer.last_cluster_params, ("leiden", 1.0, 10))
        np.testing.assert_array_equal(viewer.custom_scores, np.arange(self.N_NODES))
        self.assertEqual(viewer.custom_notes, {"note": "kept"})
        self.assertLessEqual({"custom_scores", "custom_notes"}, viewer._cacheable_attrs)

    def test_saved_sizes_follow_the_current_node_size(self):
        folder = os.path.join(self.root, "Network_Score0.4_3D")
        os.makedirs(folder)
        path = self.publish(folder)
        self.write_state(path)
        SettingsPatch(self, NODE_SIZE=5.0)
        viewer, _ = self.open(path)
        np.testing.assert_allclose(viewer.current_sizes, 10.0)

    def test_a_mismatched_entry_is_skipped_not_half_applied(self):
        folder = os.path.join(self.root, "Network_Score0.4_3D")
        os.makedirs(folder)
        path = self.publish(folder)
        self.write_state(path, colors=np.ones((self.N_NODES + 1, 4), dtype=np.float32))
        viewer, output = self.open(path)
        self.assertIn("ignoring the cache's saved colours", output)
        self.assertEqual(viewer.current_colors.shape, (self.N_NODES, 4))
        np.testing.assert_allclose(viewer.current_sizes, 20.0)

    def test_a_dataset_cannot_replace_live_viewer_state(self):
        folder = os.path.join(self.root, "Network_Score0.4_3D")
        os.makedirs(folder)
        path = self.publish(folder)
        with h5py.File(path, "a") as handle:
            handle.create_dataset("running", data=np.zeros(1))
        viewer, output = self.open(path)
        self.assertIs(viewer.running, True)
        self.assertIn("'running'", output)
        self.assertNotIn("running", viewer._cacheable_attrs)

    def test_save_then_reopen_round_trips_the_session(self):
        folder = os.path.join(self.root, "Network_Score0.4_3D")
        os.makedirs(folder)
        viewer, _ = self.open(self.publish(folder))
        viewer.current_colors[0] = [0.0, 1.0, 0.0, 1.0]
        viewer.current_sizes[1] = 30.0
        viewer.visible_mask[2] = False
        viewer.group_labels[3].add("kinase")
        viewer.cluster_labels = np.array([1, 1, 2, 2, 2])
        viewer.last_cluster_params = ("mcl", 2.0, 5)
        output = run_command(viewer, "save")

        saved = sorted(name for name in os.listdir(folder)
                       if name.endswith(".h5") and name != "version_00.h5")
        self.assertEqual(len(saved), 1, output)
        reopened, _ = self.open(os.path.join(folder, saved[0]))
        np.testing.assert_allclose(reopened.current_colors[0], [0.0, 1.0, 0.0, 1.0])
        self.assertEqual(float(reopened.current_sizes[1]), 30.0)
        self.assertFalse(reopened.visible_mask[2])
        self.assertEqual(reopened.group_labels[3], {"kinase"})
        np.testing.assert_array_equal(reopened.cluster_labels, [1, 1, 2, 2, 2])
        self.assertEqual(reopened.last_cluster_params, ("mcl", 2.0, 5))

    def test_a_fresh_cache_keeps_the_defaults(self):
        folder = os.path.join(self.root, "Network_Score0.4_3D")
        os.makedirs(folder)
        viewer, _ = self.open(self.publish(folder))
        np.testing.assert_array_equal(viewer.visible_mask, np.ones(self.N_NODES, dtype=bool))
        np.testing.assert_array_equal(viewer.node_render_order, np.arange(self.N_NODES))
        self.assertIsNone(viewer.cluster_labels)
        self.assertIsNone(viewer.last_cluster_params)


class HelpTextTests(unittest.TestCase):
    def test_a_stub_is_summarised_for_users(self):
        output = run_command(make_viewer(), "help")
        for name in ("agent", "esmfold", "print", "zoom"):
            with self.subTest(command=name):
                # Local commands are listed as "    <name>  <summary>".
                line = next(row for row in output.splitlines() if row.split()[:1] == [name])
                self.assertIn("Not available in the VR viewer", line)
                self.assertNotIn("instead of crashing", line)

    def test_an_override_points_at_its_own_usage(self):
        output = run_command(make_viewer(), "help meta")
        self.assertIn("Run 'meta help' for its usage in this viewer.", output)


if __name__ == "__main__":
    unittest.main()
