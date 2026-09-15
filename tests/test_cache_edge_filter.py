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

"""Tests for falling back to the edge filter a cache was built with.

Pinning a cache in the Config GUI leaves both filter fields empty - the cache
has already answered the question - so the viewer reached ``prepare_network``
with neither a similarity threshold nor a top-edge percentage and died on
``float >= None``. The user saw only a warning and a network with no edges.

What matters is the precedence: a filter named in the settings must still win,
so narrowing the view without regenerating the cache keeps working, and the
manifest is consulted only where there was no answer at all.
"""

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

OPT_VR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VR_SRC = os.path.join(OPT_VR, "src")
if VR_SRC not in sys.path:
    sys.path.insert(0, VR_SRC)

_NEUTRAL = tempfile.NamedTemporaryFile(
    "w", suffix=".json", delete=False, encoding="utf-8"
)
json.dump({}, _NEUTRAL)
_NEUTRAL.close()
os.environ["SSN_VIEWER_SETTINGS_PATH"] = _NEUTRAL.name

import _bootstrap_vr  # noqa: E402
import Settings_VR as cfg  # noqa: E402

_bootstrap_vr.install_settings_alias(cfg)

with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
    import EMAPSSN_Viewer_VR as viewer  # noqa: E402

import Cache_Manifest as cache_manifest  # noqa: E402

DIGEST = "a" * 64
OTHER_DIGEST = "b" * 64


def cache_folder(**filter_settings):
    """Write a valid manifest describing `filter_settings` and return its folder."""
    compatibility = cache_manifest.build_compatibility(
        DIGEST,
        OTHER_DIGEST,
        "alignment",
        alignment_score="global",
        normalization="alignment_length",
        layout_dimensions=3,
        **filter_settings,
    )
    manifest = cache_manifest.build_manifest(
        {"basename": "seq.fasta", "size_bytes": 1, "sha256": DIGEST},
        {"basename": "net.h5", "size_bytes": 1, "sha256": OTHER_DIGEST},
        compatibility,
    )
    folder = tempfile.mkdtemp()
    with open(
        os.path.join(folder, cache_manifest.MANIFEST_FILENAME), "w", encoding="utf-8"
    ) as handle:
        json.dump(manifest, handle)
    return folder


def cache_file(**filter_settings):
    return os.path.join(cache_folder(**filter_settings), "version_00.h5")


class ReadFilterTests(unittest.TestCase):
    def setUp(self):
        self._stdout = redirect_stdout(io.StringIO())
        self._stdout.__enter__()
        self.addCleanup(lambda: self._stdout.__exit__(None, None, None))

    def test_no_cache_path_reads_as_nothing(self):
        self.assertIsNone(viewer._cache_edge_filter(None))
        self.assertIsNone(viewer._cache_edge_filter(""))

    def test_a_folder_without_a_manifest_reads_as_nothing(self):
        missing = os.path.join(tempfile.mkdtemp(), "version_00.h5")
        self.assertIsNone(viewer._cache_edge_filter(missing))

    def test_a_corrupt_manifest_reads_as_nothing_rather_than_raising(self):
        folder = tempfile.mkdtemp()
        with open(
            os.path.join(folder, cache_manifest.MANIFEST_FILENAME), "w",
            encoding="utf-8",
        ) as handle:
            handle.write("{ not json")
        self.assertIsNone(
            viewer._cache_edge_filter(os.path.join(folder, "version_00.h5"))
        )

    def test_the_recorded_filter_is_returned(self):
        found = viewer._cache_edge_filter(cache_file(top_edge_percent=5.0))
        self.assertEqual(found, {"mode": "top_edge_percent", "value": 5.0})


class AdoptFilterTests(unittest.TestCase):
    """Precedence: the settings answer first, the manifest only fills a gap."""

    FILTER_KEYS = (
        "TOP_EDGE_PERCENT",
        "SIMILARITY_THRESHOLD",
        "UMAP_MODE",
        "UMAP_NEIGHBORS",
    )

    def setUp(self):
        self._saved = {key: getattr(cfg, key, None) for key in self.FILTER_KEYS}
        cfg.TOP_EDGE_PERCENT = None
        cfg.SIMILARITY_THRESHOLD = None
        cfg.UMAP_MODE = False
        self.addCleanup(self._restore)
        self._stdout = redirect_stdout(io.StringIO())
        self._stdout.__enter__()
        self.addCleanup(lambda: self._stdout.__exit__(None, None, None))

    def _restore(self):
        for key, value in self._saved.items():
            setattr(cfg, key, value)

    def test_top_edge_percent_is_adopted(self):
        viewer._adopt_cache_edge_filter(cache_file(top_edge_percent=5.0))
        self.assertEqual(cfg.TOP_EDGE_PERCENT, 5.0)
        self.assertIsNone(cfg.SIMILARITY_THRESHOLD)

    def test_similarity_threshold_is_adopted(self):
        viewer._adopt_cache_edge_filter(cache_file(similarity_threshold=42.5))
        self.assertEqual(cfg.SIMILARITY_THRESHOLD, 42.5)
        self.assertIsNone(cfg.TOP_EDGE_PERCENT)

    def test_umap_topology_is_adopted(self):
        viewer._adopt_cache_edge_filter(
            cache_file(umap_mode=True, umap_neighbors=25)
        )
        self.assertTrue(cfg.UMAP_MODE)
        self.assertEqual(cfg.UMAP_NEIGHBORS, 25)

    def test_a_filter_in_the_settings_wins(self):
        """Narrowing the view without regenerating the cache must keep working."""
        cfg.TOP_EDGE_PERCENT = 1.0
        viewer._adopt_cache_edge_filter(cache_file(top_edge_percent=5.0))
        self.assertEqual(cfg.TOP_EDGE_PERCENT, 1.0)

    def test_a_threshold_in_the_settings_wins(self):
        cfg.SIMILARITY_THRESHOLD = 9.0
        viewer._adopt_cache_edge_filter(cache_file(top_edge_percent=5.0))
        self.assertEqual(cfg.SIMILARITY_THRESHOLD, 9.0)
        self.assertIsNone(cfg.TOP_EDGE_PERCENT)

    def test_umap_mode_in_the_settings_is_not_overridden(self):
        cfg.UMAP_MODE = True
        viewer._adopt_cache_edge_filter(cache_file(top_edge_percent=5.0))
        self.assertIsNone(cfg.TOP_EDGE_PERCENT)

    def test_a_filter_with_no_value_adopts_nothing(self):
        # build_compatibility records similarity_threshold: None when a cache
        # was generated without either control set.
        viewer._adopt_cache_edge_filter(cache_file())
        self.assertIsNone(cfg.TOP_EDGE_PERCENT)
        self.assertIsNone(cfg.SIMILARITY_THRESHOLD)

    def test_an_unreadable_manifest_adopts_nothing(self):
        viewer._adopt_cache_edge_filter(None)
        self.assertIsNone(cfg.TOP_EDGE_PERCENT)
        self.assertIsNone(cfg.SIMILARITY_THRESHOLD)


class EdgeRebuildGuardTests(unittest.TestCase):
    """With no filter anywhere, say so instead of dying on `float >= None`."""

    def setUp(self):
        self._saved = (
            getattr(cfg, "TOP_EDGE_PERCENT", None),
            getattr(cfg, "SIMILARITY_THRESHOLD", None),
            getattr(cfg, "UMAP_MODE", False),
            getattr(cfg, "INPUT_HDF5", None),
        )
        cfg.TOP_EDGE_PERCENT = None
        cfg.SIMILARITY_THRESHOLD = None
        cfg.UMAP_MODE = False
        self.addCleanup(self._restore)

    def _restore(self):
        (
            cfg.TOP_EDGE_PERCENT,
            cfg.SIMILARITY_THRESHOLD,
            cfg.UMAP_MODE,
            cfg.INPUT_HDF5,
        ) = self._saved

    def test_the_message_names_the_controls_that_would_fix_it(self):
        network = tempfile.NamedTemporaryFile(suffix=".h5", delete=False)
        network.close()
        self.addCleanup(lambda: os.path.exists(network.name) and os.unlink(network.name))
        cfg.INPUT_HDF5 = network.name

        buffer = io.StringIO()
        with redirect_stdout(buffer):
            edges, scores = viewer._edges_for(["a", "b"], cache_file())

        self.assertEqual(len(edges), 0)
        self.assertEqual(len(scores), 0)
        message = buffer.getvalue()
        self.assertIn("no edge filter is set", message)
        self.assertIn("Top Edge Percent", message)
        self.assertNotIn("Traceback", message)


if __name__ == "__main__":
    unittest.main()
