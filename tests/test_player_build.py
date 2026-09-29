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

"""Tests for reading an installed VR client build's manifest.

What matters is not only that a good ``vr_client.json`` reads, but that
everything else declines rather than guesses: a wrong endpoint would lock the
Config GUI to an address the player never dials.
"""

import json
import os
import sys
import tempfile
import unittest

OPT_VR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VR_SRC = os.path.join(OPT_VR, "src")
if VR_SRC not in sys.path:
    sys.path.insert(0, VR_SRC)

import Player_Build_VR as build  # noqa: E402

INSTALLED_PLAYER = os.path.join(OPT_VR, "player")


def build_with(manifest):
    """A throwaway build directory holding `manifest` as vr_client.json."""
    root = tempfile.mkdtemp()
    with open(os.path.join(root, build.MANIFEST_NAME), "w", encoding="utf-8") as handle:
        if isinstance(manifest, str):
            handle.write(manifest)
        else:
            json.dump(manifest, handle)
    return root


GOOD = {"client": "EMAP-SSN-VR Godot client", "version": "0.1.0", "protocol": 1,
        "host": "127.0.0.1", "port": 5005, "godot": "4.7.2.stable", "commit": "abc"}


class ReadEndpointTests(unittest.TestCase):
    def test_the_manifest_endpoint_is_read(self):
        self.assertEqual(build.read_endpoint(build_with(GOOD)), ("127.0.0.1", 5005))

    def test_localhost_is_accepted(self):
        self.assertEqual(
            build.read_endpoint(build_with({**GOOD, "host": "localhost", "port": 7777})),
            ("localhost", 7777))

    def test_a_missing_build_reads_as_unknown(self):
        self.assertIsNone(build.read_endpoint(""))
        self.assertIsNone(build.read_endpoint(os.path.join(OPT_VR, "no_such_build")))

    def test_a_build_without_a_manifest_reads_as_unknown(self):
        self.assertIsNone(build.read_endpoint(tempfile.mkdtemp()))

    def test_an_unreadable_manifest_reads_as_unknown(self):
        self.assertIsNone(build.read_endpoint(build_with("{not json")))
        self.assertIsNone(build.read_endpoint(build_with("[1, 2, 3]")))

    def test_implausible_endpoints_read_as_unknown(self):
        for host, port in (("999.1.1.1", 5005), ("example.com", 5005), ("127.0.0.1", 0),
                           ("127.0.0.1", 70000), ("127.0.0.1", "5005"), ("127.0.0.1", True),
                           (None, 5005)):
            with self.subTest(host=host, port=port):
                self.assertIsNone(build.read_endpoint(build_with({**GOOD, "host": host, "port": port})))

    def test_client_info_carries_the_version(self):
        self.assertEqual(build.read_client_info(build_with(GOOD))["version"], "0.1.0")

    def test_describe_endpoint_is_readable_either_way(self):
        self.assertEqual(build.describe_endpoint(("127.0.0.1", 5005)), "127.0.0.1:5005")
        self.assertEqual(build.describe_endpoint(None), "unknown")

    @unittest.skipUnless(os.path.isfile(os.path.join(INSTALLED_PLAYER, build.MANIFEST_NAME)),
                         "no VR client is installed in player/")
    def test_the_installed_player_reports_its_default_endpoint(self):
        self.assertEqual(build.read_endpoint(INSTALLED_PLAYER), ("127.0.0.1", 5005))


if __name__ == "__main__":
    unittest.main()
