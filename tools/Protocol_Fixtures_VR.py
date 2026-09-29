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

"""Record protocol v1 byte streams from the real server, for client tests.

Each scenario serves a small deterministic network through the production
``unity_server_loop``, captures every byte the client receives, and writes:

``<scenario>.bin``
    The exact server -> client stream: the binary phase, then the JSON lines.
``<scenario>.json``
    What a correct client must decode from it: counts, positions, both edge
    lists, the binary phase's length, and every JSON packet.

``transform_messages.json`` lists client -> server transform messages in the
exact spelling clients send, so a client's writer can be checked byte for byte.

A client's tests replay these streams at arbitrary chunk boundaries. Because
the bytes come from the production server rather than from a model of it, a
client that passes them speaks the protocol the server actually implements.

    python tools/Protocol_Fixtures_VR.py --out <client>/tests/fixtures/protocol_v1
"""

from __future__ import annotations

import argparse
import io
import json
import os
import sys
import tempfile
from contextlib import redirect_stderr, redirect_stdout

# Neutral settings, so a user's saved viewer_settings_vr.json cannot leak into
# the fixtures. Must precede every import that reads settings.
_NEUTRAL = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
json.dump({}, _NEUTRAL)
_NEUTRAL.close()
os.environ["SSN_VIEWER_SETTINGS_PATH"] = _NEUTRAL.name

import numpy as np  # noqa: E402

import Protocol_V1_VR as protocol  # noqa: E402

vr_viewer = None  # imported lazily in main(), behind the neutral settings


def _viewer(n_nodes, seed):
    rng = np.random.default_rng(seed)
    headers = [f"fixture|{index:04d}" for index in range(n_nodes)]
    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
        viewer = vr_viewer.HeadlessViewer(n_nodes, headers, list(headers), {})
    viewer.pos = ((rng.random((n_nodes, 3)) - 0.5) * 200.0).astype(np.float32)
    return viewer


def _pairs(values):
    return np.asarray(values, dtype=np.int32).reshape(-1, 2)


def _scenarios():
    """(name, n_nodes, render_edges, full_edges, mutate) for each fixture."""

    def recolour(viewer):
        # The kind of change a terminal command makes: one colour, one hidden
        # node, one size, and a new edge alpha.
        viewer.current_colors[0] = [1.0, 0.0, 0.0, 1.0]
        viewer.visible_mask[min(2, viewer.n_nodes - 1)] = False
        viewer.current_sizes[-1] = 17.5

    return [
        ("basic", 6, _pairs([(0, 1), (2, 3), (4, 5)]),
         _pairs([(0, 1), (1, 2), (2, 3), (3, 4), (4, 5), (5, 0), (0, 3)]), recolour),
        ("same_edges", 4, _pairs([(0, 1), (1, 2), (2, 3), (3, 0)]),
         _pairs([(0, 1), (1, 2), (2, 3), (3, 0)]), recolour),
        ("no_edges", 5, _pairs([]), _pairs([]), recolour),
        ("single_node", 1, _pairs([]), _pairs([]), None),
    ]


def _capture(name, n_nodes, render, full, mutate, seed):
    viewer = _viewer(n_nodes, seed)
    server = protocol.LoopbackServer(viewer, viewer.pos, render, full)
    try:
        client = server.connect()
        try:
            stream = bytearray()

            def read(count):
                data = protocol.read_exact(client, count)
                stream.extend(data)
                return data

            handshake = protocol.decode_handshake(read)
            lines = protocol.LineReader(client)
            packets = [lines.read_line()]
            if mutate is not None:
                mutate(viewer)
                viewer.update_nodes()
                packets.append(lines.read_line())
            for line in packets:
                stream.extend(line + b"\n")
        finally:
            client.close()
    finally:
        server.close()

    expected = {
        "scenario": name,
        "protocol": protocol.PROTOCOL_VERSION,
        "n_nodes": handshake.n_nodes,
        "positions": handshake.positions.astype(float).tolist(),
        "render_edges": handshake.render_edges.tolist(),
        "full_edges": handshake.full_edges.tolist(),
        "binary_length": handshake.byte_length,
        "stream_length": len(stream),
        "packets": [json.loads(line) for line in packets],
    }
    return bytes(stream), expected


def _transform_examples():
    cases = [
        ((0, 0, 0), (0, 0, 0, 1), (1, 1, 1), 1),
        ((1.25, 2.5, -3.75), (0, 0.7071068, 0, 0.7071068), (2, 2, 2), 1.5),
        ((-0.00004, 123.45678, 0.5), (0.1, -0.2, 0.3, 0.9273618), (0.05, 0.05, 0.05), 10),
    ]
    return [
        {
            "position": list(position), "rotation": list(rotation),
            "scale": list(scale), "distanceScale": distance,
            "message": protocol.transform_message(position, rotation, scale, distance).decode(),
        }
        for position, rotation, scale, distance in cases
    ]


def main(argv=None):
    global vr_viewer
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", required=True, help="directory to write fixtures into")
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args(argv)

    vr_viewer = protocol.import_viewer_module()
    # The loop only returns to accept() between scenarios when quitting with
    # the client is off; it is a per-process setting, never saved.
    vr_viewer.cfg.EXIT_WITH_UNITY = False
    vr_viewer.CONSOLE._stream = io.StringIO()

    os.makedirs(args.out, exist_ok=True)
    for name, n_nodes, render, full, mutate in _scenarios():
        stream, expected = _capture(name, n_nodes, render, full, mutate, args.seed)
        with open(os.path.join(args.out, f"{name}.bin"), "wb") as handle:
            handle.write(stream)
        with open(os.path.join(args.out, f"{name}.json"), "w", encoding="utf-8", newline="\n") as handle:
            json.dump(expected, handle, indent=1)
            handle.write("\n")
        print(f"{name}: {len(stream)} bytes, {len(expected['packets'])} packet(s)")

    with open(os.path.join(args.out, "transform_messages.json"), "w", encoding="utf-8", newline="\n") as handle:
        json.dump(_transform_examples(), handle, indent=1)
        handle.write("\n")
    print("transform_messages.json written")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
