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

"""The VR viewer refuses a cache its inputs did not build, as the desktop does.

The desktop viewer takes a cache's analysis settings from the cache, rebuilds
the folder manifest from the current FASTA and network and requires it to
match, then requires the cache's node order to equal the network filtered by
the sanitised FASTA. The VR viewer used to open whatever cache it found: an
edited FASTA or a different network paired with an older layout, `export`
wrote sequences the layout was never built from, and the edges came from
whichever network the settings named.
"""

import importlib
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

_bootstrap_vr.install_settings_alias(cfg)

from tests.cache_fixtures import publish_cache, use_inputs  # noqa: E402


def quietly(function, *args, **kwargs):
    """Call `function`, returning its result and everything it printed."""
    buffer = io.StringIO()
    with redirect_stdout(buffer), redirect_stderr(buffer):
        result = function(*args, **kwargs)
    return result, buffer.getvalue()


class CacheValidationTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)

    def open(self, cache):
        use_inputs(self, cache)
        return quietly(vr_viewer.open_layout_session)

    def refusal(self, cache):
        """Open `cache`, which must be refused, and return the reason given."""
        use_inputs(self, cache)
        with self.assertRaises(SystemExit) as raised:
            quietly(vr_viewer.open_layout_session)
        return str(raised.exception)

    def test_a_published_cache_opens_with_its_own_network_edges(self):
        cache = publish_cache(self.root)
        viewer, _ = self.open(cache)
        self.assertEqual(viewer.full_headers, cache.headers)
        # The four pairs that score at least 0.45 in the fixture network.
        self.assertEqual(len(viewer.edges), 4)
        self.assertEqual(viewer.edges.dtype, np.int32)
        self.assertEqual(viewer.cache_manifest_id, cache.manifest_id)

    def test_an_edited_fasta_is_refused(self):
        cache = publish_cache(self.root)
        with open(cache.fasta, "a", encoding="utf-8", newline="\n") as handle:
            handle.write(">added_later\nMKTAYIAKQR\n")
        reason = self.refusal(cache)
        self.assertIn("NODE_FASTA_FILE", reason)
        self.assertIn("set.fasta", reason)

    def test_an_edited_network_is_refused(self):
        cache = publish_cache(self.root)
        with h5py.File(cache.network, "a") as handle:
            handle["g_score"][0] = 9.0
        reason = self.refusal(cache)
        self.assertIn("INPUT_HDF5", reason)
        self.assertIn("network.h5", reason)

    def test_a_missing_network_is_refused_not_drawn_without_edges(self):
        cache = publish_cache(self.root)
        os.remove(cache.network)
        reason = self.refusal(cache)
        self.assertIn("INPUT_HDF5", reason)
        self.assertIn("does not exist", reason)

    def test_a_missing_fasta_is_refused(self):
        cache = publish_cache(self.root)
        os.remove(cache.fasta)
        reason = self.refusal(cache)
        self.assertIn("NODE_FASTA_FILE", reason)
        self.assertIn("does not exist", reason)

    def test_a_cache_from_another_folder_is_refused(self):
        cache = publish_cache(self.root)
        other = publish_cache(os.path.join(self.root, "other"), similarity_threshold=0.6)
        shutil.copyfile(other.path, cache.path)
        reason = self.refusal(cache)
        self.assertIn("version_00.h5", reason)
        self.assertIn("manifest", reason.lower())

    def test_a_node_order_that_differs_from_the_network_is_refused(self):
        cache = publish_cache(self.root)
        with h5py.File(cache.path, "a") as handle:
            del handle["headers"]
            handle.create_dataset(
                "headers",
                data=np.asarray(cache.headers[::-1], dtype=object),
                dtype=h5py.string_dtype(encoding="utf-8"),
            )
        self.assertIn("node order", self.refusal(cache))

    def test_saved_state_for_a_different_node_count_is_refused(self):
        cache = publish_cache(self.root)
        with h5py.File(cache.path, "a") as handle:
            handle.create_dataset("colors", data=np.ones((len(cache.headers) + 1, 4)))
        self.assertIn("does not match the node count", self.refusal(cache))

    def test_a_2d_cache_is_checked_as_one_and_lifted(self):
        cache = publish_cache(self.root, dimensions=2)
        viewer, output = self.open(cache)
        self.assertEqual(viewer.pos.shape, (len(cache.headers), 3))
        self.assertIn("2D layout cache", output)
        self.assertIn("save is unavailable for a 2D cache", output)

    def test_headers_that_sanitising_changes_still_match_and_export(self):
        raw = [
            "WP_012345678.1 hypothetical protein [Escherichia coli]",
            "sp|P69905|HBA_HUMAN Hemoglobin subunit alpha",
            "plain_header",
        ]
        cache = publish_cache(self.root, raw_headers=raw)
        self.assertNotEqual(cache.headers[0], raw[0])
        viewer, _ = self.open(cache)
        export = importlib.import_module("commands.export")
        records = export._get_in_memory_sequence_records(viewer)
        self.assertEqual(sorted(records), sorted(cache.headers))


if __name__ == "__main__":
    unittest.main()
