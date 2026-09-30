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

"""Tests for the edge filter and scoring a VR session takes from its cache.

Pinning a cache in the Config GUI leaves both filter fields empty - the cache
has already answered the question - so the viewer once reached
``prepare_network`` with neither a similarity threshold nor a top-edge
percentage and died on ``float >= None``. The user saw only a warning and a
network with no edges.

The viewer now takes every analysis setting from the cache before it checks
the cache against its inputs, as the desktop viewer's resolve_viewer_document
does: the edge filter, the alignment score, the normalization and the UMAP
settings. A filter named in the VR settings no longer overrides the cache's.
The desktop ignores one too, and narrows the view with its edge-threshold
slider instead.
"""

import io
import json
import os
import shutil
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

from tests.cache_fixtures import publish_cache, use_inputs  # noqa: E402


class CacheSettingsAdoptionTests(unittest.TestCase):
    """The cache's own analysis settings are used, as on the desktop."""

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)

    def verify(self, cache, **settings):
        """Run the viewer's cache check with `settings` in place of the saved ones."""
        use_inputs(self, cache)
        for name, value in settings.items():
            setattr(cfg, name, value)
        buffer = io.StringIO()
        with redirect_stdout(buffer), redirect_stderr(buffer):
            verified = viewer.verify_layout_cache(cache.path)
        return verified, buffer.getvalue()

    def test_an_empty_filter_takes_the_cache_threshold(self):
        """Pinning a cache in the Config GUI leaves both filter fields empty."""
        cache = publish_cache(self.root, similarity_threshold=0.45)
        verified, output = self.verify(cache, SIMILARITY_THRESHOLD=None, TOP_EDGE_PERCENT=None)
        self.assertEqual(cfg.SIMILARITY_THRESHOLD, 0.45)
        self.assertIsNone(cfg.TOP_EDGE_PERCENT)
        # The four fixture pairs that score at least 0.45.
        self.assertEqual(len(verified.edges), 4)
        self.assertIn("Edge filter from the cache manifest: score >= 0.45.", output)
        self.assertNotIn("Note:", output)

    def test_the_cache_filter_wins_over_the_settings(self):
        cache = publish_cache(self.root, similarity_threshold=0.45)
        verified, output = self.verify(cache, SIMILARITY_THRESHOLD=0.65, TOP_EDGE_PERCENT=None)
        self.assertEqual(cfg.SIMILARITY_THRESHOLD, 0.45)
        self.assertEqual(len(verified.edges), 4)
        self.assertIn("the settings name score >= 0.65", output)

    def test_a_top_edge_percentage_is_taken_from_the_cache(self):
        cache = publish_cache(self.root, top_edge_percent=30.0)
        verified, _ = self.verify(cache, SIMILARITY_THRESHOLD=0.9, TOP_EDGE_PERCENT=None)
        self.assertEqual(cfg.TOP_EDGE_PERCENT, 30.0)
        # 30% of the 10 possible pairs is 3; the tie at the cutoff keeps a fourth.
        self.assertEqual(len(verified.edges), 4)

    def test_umap_topology_is_taken_from_the_cache(self):
        cache = publish_cache(self.root, umap_neighbors=2)
        self.verify(cache, UMAP_MODE=False, SIMILARITY_THRESHOLD=0.5)
        self.assertIs(cfg.UMAP_MODE, True)
        self.assertEqual(cfg.UMAP_NEIGHBORS, 2)

    def test_score_settings_are_taken_from_the_cache(self):
        cache = publish_cache(self.root)
        self.verify(cache, ALIGNMENT_SCORE="local", NORM_MODE="shorter_sequence")
        self.assertEqual(cfg.ALIGNMENT_SCORE, "global")
        self.assertEqual(cfg.NORM_MODE, "alignment_length")

    def test_a_cache_that_names_no_filter_is_refused_with_the_reason(self):
        """Refused, as on the desktop, instead of dying on `float >= None`."""
        cache = publish_cache(self.root, similarity_threshold=None)
        use_inputs(self, cache)
        buffer = io.StringIO()
        with self.assertRaises(SystemExit) as raised:
            with redirect_stdout(buffer), redirect_stderr(buffer):
                viewer.verify_layout_cache(cache.path)
        self.assertIn("invalid edge filter", str(raised.exception))
        self.assertNotIn("Traceback", buffer.getvalue())


if __name__ == "__main__":
    unittest.main()
