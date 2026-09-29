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

"""Conformance tests for version 1 of the Python <-> VR client protocol.

``docs/PROTOCOL.md`` is the contract and ``unity_server_loop`` its reference
implementation. A client written from the document (``tools/Protocol_V1_VR.py``)
drives the real server loop over a real loopback socket, so drift between the
document and the server fails here instead of desynchronising a headset. The
protocol has no framing, magic number or version field, which is exactly why
every byte count is pinned down.
"""

import io
import json
import os
import socket
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

OPT_VR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VR_SRC = os.path.join(OPT_VR, "src")
TOOLS = os.path.join(OPT_VR, "tools")
for _path in (TOOLS, VR_SRC):
    if _path not in sys.path:
        sys.path.insert(0, _path)

_NEUTRAL = tempfile.NamedTemporaryFile(
    "w", suffix=".json", delete=False, encoding="utf-8"
)
json.dump({}, _NEUTRAL)
_NEUTRAL.close()
os.environ["SSN_VIEWER_SETTINGS_PATH"] = _NEUTRAL.name

import numpy as np  # noqa: E402

import _bootstrap_vr  # noqa: E402
import Settings_VR as cfg  # noqa: E402

_bootstrap_vr.install_settings_alias(cfg)

with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
    import EMAPSSN_Viewer_VR as vr_viewer  # noqa: E402

import Protocol_V1_VR as protocol  # noqa: E402


def build_viewer(n_nodes, seed=0):
    """A HeadlessViewer on synthetic data, with no cache, socket or player."""
    rng = np.random.default_rng(seed)
    headers = [f"sp|P{index:05d}|PROT{index}_TEST" for index in range(n_nodes)]
    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
        viewer = vr_viewer.HeadlessViewer(n_nodes, headers, list(headers), {})
    viewer.pos = ((rng.random((n_nodes, 3)) - 0.5) * 200.0).astype(np.float32)
    return viewer


def wait_for(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


class ProtocolTestCase(unittest.TestCase):
    """Starts the production server loop for one viewer and network."""

    def setUp(self):
        saved = getattr(cfg, "EXIT_WITH_UNITY", True)
        cfg.EXIT_WITH_UNITY = False
        self.addCleanup(setattr, cfg, "EXIT_WITH_UNITY", saved)
        console = mock.patch.object(vr_viewer.CONSOLE, "message")
        self.console = console.start()
        self.addCleanup(console.stop)
        interrupt = mock.patch.object(vr_viewer._thread, "interrupt_main")
        interrupt.start()
        self.addCleanup(interrupt.stop)

    def serve(self, viewer, render_edges, full_edges):
        server = protocol.LoopbackServer(viewer, viewer.pos, render_edges, full_edges)
        self.addCleanup(server.close)
        return server

    def connect(self, server):
        client = server.connect()
        self.addCleanup(client.close)
        return client


class BinaryPhaseTests(ProtocolTestCase):
    def test_the_six_blocks_arrive_in_documented_order_and_layout(self):
        viewer = build_viewer(7)
        render = np.array([(0, 1), (2, 3), (4, 6)], dtype=np.int32)
        full = np.array([(i, (i + 1) % 7) for i in range(7)], dtype=np.int32)
        client = self.connect(self.serve(viewer, render, full))

        handshake = protocol.read_handshake(client)

        self.assertEqual(handshake.n_nodes, 7)
        self.assertEqual(
            handshake.positions.tobytes(), viewer.pos.astype("<f4").tobytes(),
            "positions must be little-endian float32 x, y, z, row-major",
        )
        np.testing.assert_array_equal(handshake.render_edges, render)
        np.testing.assert_array_equal(handshake.full_edges, full)
        self.assertEqual(handshake.byte_length, 4 + 84 + 4 + 24 + 4 + 56)

    def test_the_first_json_packet_follows_block_six_with_no_separator(self):
        viewer = build_viewer(3)
        edges = np.array([(0, 1)], dtype=np.int32)
        client = self.connect(self.serve(viewer, edges, edges))

        protocol.read_handshake(client)

        self.assertEqual(protocol.read_exact(client, 1), b"{")

    def test_render_and_full_edges_may_be_the_same_list(self):
        viewer = build_viewer(4)
        edges = np.array([(0, 1), (1, 2), (2, 3)], dtype=np.int32)
        client = self.connect(self.serve(viewer, edges, edges))

        handshake = protocol.read_handshake(client)

        np.testing.assert_array_equal(handshake.render_edges, handshake.full_edges)

    def test_a_network_without_edges_still_sends_both_counts(self):
        viewer = build_viewer(5)
        none = np.zeros((0, 2), dtype=np.int32)
        client = self.connect(self.serve(viewer, none, none))

        handshake = protocol.read_handshake(client)

        self.assertEqual(len(handshake.render_edges), 0)
        self.assertEqual(len(handshake.full_edges), 0)
        self.assertEqual(protocol.read_exact(client, 1), b"{")

    def test_a_single_node(self):
        viewer = build_viewer(1)
        none = np.zeros((0, 2), dtype=np.int32)
        client = self.connect(self.serve(viewer, none, none))

        handshake = protocol.read_handshake(client)
        packet = protocol.LineReader(client).read_packet()

        self.assertEqual(handshake.n_nodes, 1)
        self.assertEqual(protocol.packet_problems(packet, 1), [])


class StatePacketTests(ProtocolTestCase):
    def setUp(self):
        super().setUp()
        self.viewer = build_viewer(6, seed=3)
        edges = np.array([(0, 1), (2, 5)], dtype=np.int32)
        self.client = self.connect(self.serve(self.viewer, edges, edges))
        protocol.read_handshake(self.client)
        self.lines = protocol.LineReader(self.client)

    def test_the_initial_packet_matches_the_documented_schema(self):
        packet = self.lines.read_packet()

        self.assertEqual(protocol.packet_problems(packet, 6), [])
        np.testing.assert_allclose(packet["colors"], self.viewer.current_colors.ravel())
        np.testing.assert_allclose(packet["sizes"], self.viewer.current_sizes)
        self.assertEqual(packet["visible"], [True] * 6)
        self.assertEqual(packet["transformState"], {
            "position": [0.0, 0.0, 0.0], "rotation": [0.0, 0.0, 0.0, 1.0],
            "scale": [1.0, 1.0, 1.0], "distanceScale": 1.0,
        })

    def test_later_packets_are_further_lines_with_the_whole_state(self):
        self.lines.read_packet()
        self.viewer.current_colors[0] = [1.0, 0.0, 0.0, 1.0]
        self.viewer.visible_mask[4] = False
        self.viewer.current_sizes[2] = 17.0

        self.viewer.update_nodes()
        packet = self.lines.read_packet()

        self.assertEqual(protocol.packet_problems(packet, 6), [])
        self.assertEqual(packet["colors"][0:4], [1.0, 0.0, 0.0, 1.0])
        self.assertIs(packet["visible"][4], False)
        self.assertEqual(packet["sizes"][2], 17.0)


class ClientMessageTests(ProtocolTestCase):
    def setUp(self):
        super().setUp()
        self.viewer = build_viewer(4)
        edges = np.array([(0, 1)], dtype=np.int32)
        self.client = self.connect(self.serve(self.viewer, edges, edges))
        protocol.read_handshake(self.client)
        protocol.LineReader(self.client).read_packet()
        self.assertTrue(wait_for(lambda: self.viewer.is_connected))

    def transform_arrived(self, position):
        return wait_for(lambda: self.viewer.transform_position == position)

    def test_a_transform_updates_the_viewer_state(self):
        self.client.sendall(protocol.transform_message(
            (1.25, 2.5, -3.75), (0.0, 0.7071, 0.0, 0.7071), (2.0, 2.0, 2.0), 1.5))

        self.assertTrue(self.transform_arrived([1.25, 2.5, -3.75]))
        self.assertEqual(self.viewer.transform_rotation, [0.0, 0.7071, 0.0, 0.7071])
        self.assertEqual(self.viewer.transform_scale, [2.0, 2.0, 2.0])
        self.assertEqual(self.viewer.distance_scale, 1.5)

    def test_the_next_state_packet_echoes_the_client_transform(self):
        self.client.sendall(protocol.transform_message(
            (0.5, 0.0, 0.0), (0.0, 0.0, 0.0, 1.0), (1.0, 1.0, 1.0), 2.0))
        self.assertTrue(self.transform_arrived([0.5, 0.0, 0.0]))

        self.viewer.update_nodes()
        packet = protocol.LineReader(self.client).read_packet()

        self.assertEqual(packet["transformState"]["position"], [0.5, 0.0, 0.0])
        self.assertEqual(packet["transformState"]["distanceScale"], 2.0)

    def test_a_message_split_across_writes_still_parses(self):
        message = protocol.transform_message(
            (9.0, 8.0, 7.0), (0.0, 0.0, 0.0, 1.0), (1.0, 1.0, 1.0), 1.0)
        self.client.sendall(message[:17])
        time.sleep(0.1)
        self.client.sendall(message[17:])

        self.assertTrue(self.transform_arrived([9.0, 8.0, 7.0]))

    def test_unknown_message_types_are_ignored_silently(self):
        self.client.sendall(protocol.hello_message("conformance-test", "1.0"))
        self.client.sendall(protocol.transform_message(
            (4.0, 0.0, 0.0), (0.0, 0.0, 0.0, 1.0), (1.0, 1.0, 1.0), 1.0))

        self.assertTrue(self.transform_arrived([4.0, 0.0, 0.0]))
        warnings = [call for call in self.console.call_args_list
                    if "Warning" in str(call)]
        self.assertEqual(warnings, [], "a hello must not be reported as an error")


class ConnectionLifecycleTests(ProtocolTestCase):
    def test_the_server_listens_again_after_a_disconnect(self):
        viewer = build_viewer(3)
        edges = np.array([(0, 2)], dtype=np.int32)
        server = self.serve(viewer, edges, edges)

        first = server.connect()
        protocol.read_handshake(first)
        protocol.LineReader(first).read_packet()
        first.close()
        self.assertTrue(wait_for(lambda: not viewer.is_connected))

        second = self.connect(server)
        handshake = protocol.read_handshake(second)

        self.assertEqual(handshake.n_nodes, 3)


class MessageSpellingTests(unittest.TestCase):
    def test_the_transform_message_keeps_the_original_client_spelling(self):
        message = protocol.transform_message(
            (1, 2, 3), (0, 0, 0, 1), (1, 1, 1), 1)
        self.assertEqual(
            message,
            b'{"type":"transform","position":[1.0000,2.0000,3.0000],'
            b'"rotation":[0.0000,0.0000,0.0000,1.0000],'
            b'"scale":[1.0000,1.0000,1.0000],"distanceScale":1.0000 }\n',
        )
        self.assertEqual(json.loads(message)["type"], "transform")

    def test_the_hello_message_is_one_json_line(self):
        message = protocol.hello_message("godot", "0.1.0")
        self.assertTrue(message.endswith(b"\n"))
        self.assertEqual(message.count(b"\n"), 1)
        self.assertEqual(json.loads(message)["protocol"], 1)


if __name__ == "__main__":
    unittest.main()
