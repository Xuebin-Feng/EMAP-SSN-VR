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

"""A reference client for version 1 of the Python <-> VR client protocol.

Written from ``docs/PROTOCOL.md``, not from the server, so that the
conformance tests, the fixture generator and the logging proxy all check the
server against the document rather than against itself. The Godot client
implements the same reading in GDScript; the byte-stream fixtures produced by
``Protocol_Fixtures_VR.py`` hold the two to the same stream.

Qt-free and headless, like the viewer it talks to.
"""

from __future__ import annotations

import json
import os
import socket
import struct
import sys
import threading
from dataclasses import dataclass
from typing import Optional

import numpy as np

#: Wire version this module speaks. Version 1 has no version field on the
#: wire; the number exists so a future hello can name it.
PROTOCOL_VERSION = 1

#: Fields every server -> client state packet carries.
PACKET_KEYS = ("colors", "sizes", "visible", "globalSettings", "transformState")

#: Keys of ``globalSettings`` and the JSON type each must have.
GLOBAL_SETTINGS_TYPES = {
    "nodeScale": float,
    "edgeThickness": float,
    "edgeAlpha": float,
    "nodeBoundaryWidth": float,
    "neighborColor": str,
    "hoverColor": str,
    "connectedNodeColor": str,
    "edgeColor": str,
    "nodeBoundaryColor": str,
}


@dataclass
class Handshake:
    """The binary phase, decoded: six blocks, in wire order."""

    n_nodes: int
    positions: np.ndarray      # (N, 3) float32
    render_edges: np.ndarray   # (E, 2) int32, the downsampled set that is drawn
    full_edges: np.ndarray     # (F, 2) int32, the complete connectivity

    @property
    def byte_length(self) -> int:
        """Bytes the binary phase occupies on the wire."""
        return (
            4 + 12 * self.n_nodes
            + 4 + 8 * len(self.render_edges)
            + 4 + 8 * len(self.full_edges)
        )


def read_exact(sock: socket.socket, count: int) -> bytes:
    """Read exactly ``count`` bytes; a single recv only returns what has arrived."""
    chunks = bytearray()
    while len(chunks) < count:
        chunk = sock.recv(min(count - len(chunks), 1 << 20))
        if not chunk:
            raise ConnectionError(
                f"peer closed after {len(chunks)} of {count} expected bytes"
            )
        chunks += chunk
    return bytes(chunks)


def decode_handshake(read) -> Handshake:
    """Decode the binary phase from ``read(count) -> bytes``.

    Taking a reader rather than a socket lets the same code parse a live
    connection, a captured byte stream, and the proxy's tee.
    """
    (n_nodes,) = struct.unpack("<I", read(4))
    positions = np.frombuffer(read(12 * n_nodes), dtype="<f4").reshape(n_nodes, 3)
    (n_render,) = struct.unpack("<I", read(4))
    render = np.frombuffer(read(8 * n_render), dtype="<i4").reshape(n_render, 2)
    (n_full,) = struct.unpack("<I", read(4))
    full = np.frombuffer(read(8 * n_full), dtype="<i4").reshape(n_full, 2)
    return Handshake(int(n_nodes), positions, render, full)


def read_handshake(sock: socket.socket) -> Handshake:
    """Read the binary phase from a connected socket."""
    return decode_handshake(lambda count: read_exact(sock, count))


class LineReader:
    """Newline-delimited JSON over a socket, keeping bytes that arrived early.

    The server writes the first JSON packet immediately after binary block 6,
    so a reader must start exactly at the first byte after the handshake and
    must not discard whatever part of the next line a recv returned.
    """

    def __init__(self, sock: socket.socket, initial: bytes = b""):
        self._sock = sock
        self._buffer = bytearray(initial)
        self._scanned = 0

    def read_line(self) -> bytes:
        """Return the next line without its terminating newline."""
        while True:
            index = self._buffer.find(b"\n", self._scanned)
            if index >= 0:
                line = bytes(self._buffer[:index])
                del self._buffer[: index + 1]
                self._scanned = 0
                return line
            # Resume the search where the last one stopped; rescanning a
            # megabyte-long line on every recv would be quadratic.
            self._scanned = len(self._buffer)
            chunk = self._sock.recv(1 << 20)
            if not chunk:
                raise ConnectionError("peer closed in the middle of a JSON line")
            self._buffer += chunk

    def read_packet(self) -> dict:
        """Read and decode the next JSON line."""
        return json.loads(self.read_line().decode("utf-8"))


def transform_message(position, rotation, scale, distance_scale) -> bytes:
    """A client -> server transform message, byte-for-byte as clients send it.

    Four decimals in invariant formatting, and the stray space before the
    closing brace that the original Unity client emitted. Keeping the exact
    spelling means the conformance tests exercise what the server really
    receives.
    """
    values = [*position, *rotation, *scale, distance_scale]
    if len(values) != 11:
        raise ValueError("position, rotation, scale must have 3, 4 and 3 values")
    f = [f"{float(value):.4f}" for value in values]
    return (
        '{"type":"transform",'
        f'"position":[{f[0]},{f[1]},{f[2]}],'
        f'"rotation":[{f[3]},{f[4]},{f[5]},{f[6]}],'
        f'"scale":[{f[7]},{f[8]},{f[9]}],'
        f'"distanceScale":{f[10]} }}\n'
    ).encode("utf-8")


def hello_message(client="reference", version="0") -> bytes:
    """The optional hello a client may send first. v1 servers ignore it."""
    body = {"type": "hello", "client": client, "version": version,
            "protocol": PROTOCOL_VERSION}
    return (json.dumps(body, separators=(",", ":")) + "\n").encode("utf-8")


def packet_problems(packet: dict, n_nodes: int) -> list:
    """Every way ``packet`` departs from the documented state-packet schema."""
    problems = []
    for key in PACKET_KEYS:
        if key not in packet:
            problems.append(f"missing {key!r}")
    if problems:
        return problems
    if len(packet["colors"]) != 4 * n_nodes:
        problems.append(f"colors has {len(packet['colors'])} values, expected {4 * n_nodes}")
    if len(packet["sizes"]) != n_nodes:
        problems.append(f"sizes has {len(packet['sizes'])} values, expected {n_nodes}")
    if len(packet["visible"]) != n_nodes:
        problems.append(f"visible has {len(packet['visible'])} values, expected {n_nodes}")
    if not all(isinstance(value, bool) for value in packet["visible"]):
        problems.append("visible holds a non-boolean")
    settings = packet["globalSettings"]
    for key, kind in GLOBAL_SETTINGS_TYPES.items():
        if key not in settings:
            problems.append(f"globalSettings is missing {key!r}")
        elif kind is float and not isinstance(settings[key], (int, float)):
            problems.append(f"globalSettings.{key} is not a number")
        elif kind is str and not isinstance(settings[key], str):
            problems.append(f"globalSettings.{key} is not a string")
    state = packet["transformState"]
    for key, length in (("position", 3), ("rotation", 4), ("scale", 3)):
        if len(state.get(key) or ()) != length:
            problems.append(f"transformState.{key} does not have {length} values")
    if not isinstance(state.get("distanceScale"), (int, float)):
        problems.append("transformState.distanceScale is not a number")
    return problems


# ---------------------------------------------------------------------------
# Serving: the production server loop on a real socket
# ---------------------------------------------------------------------------

OPT_VR_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VR_SRC_DIR = os.path.join(OPT_VR_DIR, "src")


def import_viewer_module():
    """Import ``EMAPSSN_Viewer_VR`` the way the viewer's own tests do."""
    if VR_SRC_DIR not in sys.path:
        sys.path.insert(0, VR_SRC_DIR)
    import EMAPSSN_Viewer_VR  # noqa: WPS433 (deliberately late)

    return EMAPSSN_Viewer_VR


class LoopbackServer:
    """Run the real ``unity_server_loop`` on an ephemeral loopback port.

    The loop is production code; only the listening socket is created here.
    ``EXIT_WITH_UNITY`` must be off so a disconnect returns to ``accept()``
    instead of interrupting the main thread. Call ``close()`` to stop it.
    """

    def __init__(self, viewer, positions, render_edges, full_edges,
                 host="127.0.0.1", port=0):
        self.module = import_viewer_module()
        self.listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        exclusive = getattr(socket, "SO_EXCLUSIVEADDRUSE", None)
        if exclusive is not None:
            self.listener.setsockopt(socket.SOL_SOCKET, exclusive, 1)
        self.listener.bind((host, port))
        self.listener.listen(1)
        self.host, self.port = self.listener.getsockname()[:2]
        self.thread = threading.Thread(
            target=self.module.unity_server_loop,
            args=(
                self.listener, viewer,
                np.ascontiguousarray(positions, dtype=np.float32),
                np.ascontiguousarray(render_edges, dtype=np.int32).reshape(-1, 2),
                len(positions),
                len(np.asarray(render_edges).reshape(-1, 2)),
                np.ascontiguousarray(full_edges, dtype=np.int32).reshape(-1, 2),
            ),
            daemon=True,
        )
        self.thread.start()

    def connect(self, timeout: Optional[float] = 10.0) -> socket.socket:
        client = socket.create_connection((self.host, self.port), timeout=timeout)
        client.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        return client

    def close(self):
        try:
            self.listener.close()
        except OSError:
            pass
        self.thread.join(timeout=5)
