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

"""PaCMAP beside UMAP in the VR viewer: the caches it opens and what it names after them.

The main program's layout generator can lay a network out with PaCMAP (LAYOUT_METHOD pacmap, PACMAP_NEIGHBORS
neighbours per node), 3D for this viewer. Such a cache's manifest says layout_mode pacmap_3d and its edge filter
pacmap_neighbors. The viewer takes the method and the neighbour count from the cache, as it takes the edge filter,
checks them against the files the cache was built from, and draws the strongest PACMAP_NEIGHBORS edges of
every node. Caches written before PaCMAP existed are UMAP or physics caches and open as before.
"""

import atexit
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from types import SimpleNamespace

OPT_VR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VR_SRC = os.path.join(OPT_VR, "src")
if VR_SRC not in sys.path:
    sys.path.insert(0, VR_SRC)

_NEUTRAL = tempfile.TemporaryDirectory(prefix="ssn_vr_neutral_")  # removed when this process exits
atexit.register(_NEUTRAL.cleanup)
_NEUTRAL_SETTINGS = os.path.join(_NEUTRAL.name, "viewer_settings.json")
with open(_NEUTRAL_SETTINGS, "w", encoding="utf-8") as _neutral_file:
    json.dump({}, _neutral_file)
os.environ["SSN_VIEWER_SETTINGS_PATH"] = _NEUTRAL_SETTINGS

import _bootstrap_vr  # noqa: E402
import Settings_VR as cfg  # noqa: E402

_bootstrap_vr.install_settings_alias(cfg)

with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
    import EMAPSSN_Viewer_VR as viewer  # noqa: E402

import Cache_Manifest  # noqa: E402
import Viewer_Utils_VR  # noqa: E402
from tests.cache_fixtures import publish_cache, use_inputs  # noqa: E402


class PaCMAPCacheTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)

    def verify(self, cache, **settings):
        use_inputs(self, cache)
        for name, value in settings.items():
            setattr(cfg, name, value)
        buffer = io.StringIO()
        with redirect_stdout(buffer), redirect_stderr(buffer):
            verified = viewer.verify_layout_cache(cache.path)
        return verified, buffer.getvalue()

    def test_the_method_and_the_neighbours_are_taken_from_the_cache(self):
        headers = tuple(f"sp|P{index:05d}|PROT{index}_TEST" for index in range(8))
        cache = publish_cache(self.root, raw_headers=headers, pacmap_neighbors=2)
        verified, output = self.verify(cache, UMAP_MODE=False, LAYOUT_METHOD="umap", PACMAP_NEIGHBORS=40,
                                       SIMILARITY_THRESHOLD=0.5)
        self.assertIs(cfg.UMAP_MODE, True)
        self.assertEqual(cfg.LAYOUT_METHOD, "pacmap")
        self.assertEqual(cfg.PACMAP_NEIGHBORS, 2)
        self.assertIsNone(cfg.SIMILARITY_THRESHOLD)
        self.assertEqual(verified.dimensions, 3)
        self.assertIn("Edge filter from the cache manifest: PaCMAP topology, 2 neighbours per node.", output)
        # Pair (a, b) scores a + b. Each node keeps its two strongest edges as a source (a < b) and as a target.
        pairs = {tuple(edge) for edge in verified.edges.tolist()}
        expected = set()
        for node in range(8):
            as_source = sorted(((node, other) for other in range(node + 1, 8)), key=lambda e: -sum(e))[:2]
            as_target = sorted(((other, node) for other in range(node)), key=lambda e: -sum(e))[:2]
            expected.update(as_source + as_target)
        self.assertEqual(pairs, expected)
        self.assertLess(len(pairs), 8 * 7 // 2)

    def test_two_dimensions_too(self):
        cache = publish_cache(self.root, dimensions=2, pacmap_neighbors=3)
        verified, _ = self.verify(cache)
        self.assertEqual((verified.dimensions, cfg.LAYOUT_METHOD, cfg.PACMAP_NEIGHBORS), (2, "pacmap", 3))
        degree = {}
        for a, b in verified.edges.tolist():
            degree[a] = degree.get(a, 0) + 1
            degree[b] = degree.get(b, 0) + 1
        self.assertTrue(all(count >= 3 for count in degree.values()))

    def test_a_cache_from_before_pacmap_is_umap(self):
        cache = publish_cache(self.root, umap_neighbors=2)
        self.verify(cache, LAYOUT_METHOD="pacmap")
        self.assertEqual((cfg.UMAP_MODE, cfg.LAYOUT_METHOD, cfg.UMAP_NEIGHBORS), (True, "umap", 2))
        cache = publish_cache(os.path.join(self.root, "again"), similarity_threshold=0.45)
        self.verify(cache, LAYOUT_METHOD="pacmap", UMAP_MODE=True)
        self.assertEqual((cfg.UMAP_MODE, cfg.LAYOUT_METHOD), (False, "umap"))

    def test_the_manifest_is_the_one_the_generator_writes(self):
        cache = publish_cache(self.root, pacmap_neighbors=4)
        with open(os.path.join(cache.folder, Cache_Manifest.MANIFEST_FILENAME), encoding="utf-8") as handle:
            compatibility = json.load(handle)["compatibility"]
        self.assertEqual(compatibility["layout_mode"], "pacmap_3d")
        self.assertEqual(compatibility["edge_filter"], {"mode": "pacmap_neighbors", "value": 4})
        self.assertEqual(compatibility["pacmap_revision"], Cache_Manifest.PACMAP_REVISION)

    def test_provenance_that_names_another_method_is_refused(self):
        import h5py
        import hashlib
        cache = publish_cache(self.root, pacmap_neighbors=2)
        with h5py.File(cache.path, "a") as handle:
            parameters = json.loads(handle.attrs["layout_compatibility_json"])
            parameters["LAYOUT_METHOD"] = "umap"
            text = json.dumps(parameters, sort_keys=True, separators=(",", ":"))
            handle.attrs["layout_compatibility_json"] = text
            handle.attrs["layout_compatibility_id"] = hashlib.sha256(text.encode()).hexdigest()
        use_inputs(self, cache)
        with self.assertRaises(SystemExit) as raised, redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            viewer.verify_layout_cache(cache.path)
        self.assertIn("conflicting LAYOUT_METHOD", str(raised.exception))


class EdgeFilterLabelTests(unittest.TestCase):
    def test_the_label_names_the_method(self):
        label = viewer._edge_filter_label
        self.assertEqual(label(SimpleNamespace(UMAP_MODE=True, UMAP_NEIGHBORS=15)), "UMAP topology, 15 neighbours per node")
        self.assertEqual(label(SimpleNamespace(UMAP_MODE=True, LAYOUT_METHOD="umap", UMAP_NEIGHBORS=7)),
                         "UMAP topology, 7 neighbours per node")
        self.assertEqual(label(SimpleNamespace(UMAP_MODE=True, LAYOUT_METHOD="pacmap", PACMAP_NEIGHBORS=9, UMAP_NEIGHBORS=15)),
                         "PaCMAP topology, 9 neighbours per node")
        self.assertEqual(label(SimpleNamespace(UMAP_MODE=False, LAYOUT_METHOD="pacmap", TOP_EDGE_PERCENT=5)),
                         "top 5.0% of edges")


class ClusterFolderNameTests(unittest.TestCase):
    """The folder of the cluster and alignment output names the layout, as the cache folder does."""

    def name(self, **settings):
        config = SimpleNamespace(
            INPUT_HDF5="Set_[ankh]_network.h5", NODE_FASTA_FILE="set.fasta", NORM_MODE="alignment_length",
            ALIGNMENT_SCORE="global", CLUSTER_ALIGNMENT_DIR="out", **settings)
        previous = Viewer_Utils_VR.cfg
        Viewer_Utils_VR.cfg = config
        try:
            return Viewer_Utils_VR.get_cluster_alignment_dir(SimpleNamespace(last_cluster_params=("leiden", 3)))
        finally:
            Viewer_Utils_VR.cfg = previous

    def test_each_method_has_its_own_folder(self):
        base = os.path.join("out", "set_[ankh]_alignment_length_global")
        self.assertEqual(self.name(UMAP_MODE=True, UMAP_NEIGHBORS=15), os.path.join(base, "_UMAP_k15_leiden_Min3"))
        self.assertEqual(self.name(UMAP_MODE=True, LAYOUT_METHOD="umap", UMAP_NEIGHBORS=8),
                         os.path.join(base, "_UMAP_k8_leiden_Min3"))
        self.assertEqual(self.name(UMAP_MODE=True, LAYOUT_METHOD="pacmap", PACMAP_NEIGHBORS=12, UMAP_NEIGHBORS=15),
                         os.path.join(base, "_PACMAP_k12_leiden_Min3"))
        self.assertEqual(self.name(UMAP_MODE=False, LAYOUT_METHOD="pacmap", SIMILARITY_THRESHOLD=0.5),
                         os.path.join(base, "_Score0.5_leiden_Min3"))


if __name__ == "__main__":
    unittest.main()
