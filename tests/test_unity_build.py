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

"""Tests for reading a Unity build's endpoint out of the build.

The parser is a heuristic over a serialized scene, so what matters is not only
that it finds the right endpoint in the shipped build, but that it declines
rather than guesses everywhere else: an address that is merely embedded in a
longer string, an implausible port, or two endpoints that disagree. A wrong
answer here is worse than no answer, because it would overwrite a working
configuration with one that silently never connects.
"""

import os
import struct
import sys
import tempfile
import unittest

OPT_VR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VR_SRC = os.path.join(OPT_VR, "src")
if VR_SRC not in sys.path:
    sys.path.insert(0, VR_SRC)

import Unity_Build_VR as unity  # noqa: E402

SHIPPED_BUILD = os.path.join(OPT_VR, "unity")


def field(host, port):
    """Serialize a host/port pair the way Unity lays them out in a scene."""
    raw = host.encode("ascii")
    return (
        struct.pack("<i", len(raw))
        + raw
        + b"\x00" * (-len(raw) % 4)
        + struct.pack("<i", port)
    )


def build_with(payload, name="Player"):
    """Create a throwaway build directory whose level0 holds `payload`."""
    root = tempfile.mkdtemp()
    data_dir = os.path.join(root, f"{name}_Data")
    os.makedirs(data_dir)
    with open(os.path.join(data_dir, "level0"), "wb") as handle:
        handle.write(payload)
    return root


class ScanTests(unittest.TestCase):
    def test_endpoint_is_read_from_an_adjacent_string_and_int(self):
        self.assertEqual(
            unity.endpoints_in(b"\x00" * 8 + field("127.0.0.1", 5005)),
            [("127.0.0.1", 5005)],
        )

    def test_localhost_is_recognised(self):
        self.assertEqual(
            unity.endpoints_in(b"\x00" * 8 + field("localhost", 7777)),
            [("localhost", 7777)],
        )

    def test_hosts_of_every_padding_alignment_round_trip(self):
        # Unity pads each field to four bytes, so the port's offset depends on
        # the host's length modulo four. All four cases must land.
        for host in ("10.0.0.1", "127.0.0.1", "192.168.0.11", "172.16.0.100"):
            with self.subTest(host=host, pad=-len(host) % 4):
                self.assertEqual(
                    unity.endpoints_in(b"\x00" * 8 + field(host, 5005)),
                    [(host, 5005)],
                )

    def test_address_inside_a_longer_string_is_ignored(self):
        # A log line or URL that merely contains an address is not an endpoint:
        # the int32 before it is the whole string's length, not the address's.
        text = b"connecting to 127.0.0.1 now"
        payload = (
            b"\x00" * 8
            + struct.pack("<i", len(text))
            + text
            + b"\x00" * (-len(text) % 4)
            + struct.pack("<i", 5005)
        )
        self.assertEqual(unity.endpoints_in(payload), [])

    def test_implausible_port_is_ignored(self):
        for port in (0, -1, 70000):
            with self.subTest(port=port):
                self.assertEqual(
                    unity.endpoints_in(b"\x00" * 8 + field("127.0.0.1", port)), []
                )

    def test_impossible_octet_is_ignored(self):
        self.assertEqual(
            unity.endpoints_in(b"\x00" * 8 + field("999.1.1.1", 5005)), []
        )

    def test_a_match_at_the_very_start_is_ignored(self):
        # There is no length prefix to verify against, so it cannot be trusted.
        self.assertEqual(unity.endpoints_in(field("127.0.0.1", 5005)[4:]), [])


class ReadEndpointTests(unittest.TestCase):
    def test_missing_build_reads_as_unknown(self):
        self.assertIsNone(unity.read_endpoint(""))
        self.assertIsNone(unity.read_endpoint(os.path.join(OPT_VR, "no_such_build")))

    def test_build_without_a_data_directory_reads_as_unknown(self):
        self.assertIsNone(unity.read_endpoint(tempfile.mkdtemp()))

    def test_build_without_an_endpoint_reads_as_unknown(self):
        self.assertIsNone(unity.read_endpoint(build_with(b"\x00" * 512)))

    def test_conflicting_endpoints_read_as_unknown(self):
        # Picking whichever serialized first would be a guess, and a wrong
        # guess overwrites a working configuration.
        payload = (
            b"\x00" * 8 + field("127.0.0.1", 5005) + b"\x00" * 8 + field("10.0.0.5", 6000)
        )
        self.assertIsNone(unity.read_endpoint(build_with(payload)))

    def test_the_same_endpoint_twice_still_reads(self):
        payload = (
            b"\x00" * 8 + field("127.0.0.1", 5005) + b"\x00" * 8 + field("127.0.0.1", 5005)
        )
        self.assertEqual(unity.read_endpoint(build_with(payload)), ("127.0.0.1", 5005))

    @unittest.skipUnless(os.path.isdir(SHIPPED_BUILD), "unity/ is not checked out")
    def test_the_shipped_build_reports_its_baked_endpoint(self):
        """The whole point: the GUI never has to ask for this."""
        self.assertEqual(unity.read_endpoint(SHIPPED_BUILD), ("127.0.0.1", 5005))

    @unittest.skipUnless(os.path.isdir(SHIPPED_BUILD), "unity/ is not checked out")
    def test_the_shipped_build_exposes_a_scene_to_scan(self):
        names = [os.path.basename(path) for path in unity.scan_files(SHIPPED_BUILD)]
        self.assertIn("level0", names)
        # Scene files are tried before the bulkier shared assets.
        self.assertEqual(names[0], "level0")

    def test_describe_endpoint_is_readable_either_way(self):
        self.assertEqual(unity.describe_endpoint(("127.0.0.1", 5005)), "127.0.0.1:5005")
        self.assertEqual(unity.describe_endpoint(None), "unknown")


if __name__ == "__main__":
    unittest.main()
