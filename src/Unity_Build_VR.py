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

"""Read the endpoint a built Unity player dials out of the build itself.

The client opens the TCP connection, so it has to know the address before
anything else exists - which means the address is compiled into the build, and
the Python server has to be told the same one by hand. Getting that wrong
produces no error at all: Python listens on one port, the player dials another,
and the headset simply never fills in.

The address is recoverable, so the GUI does not have to ask. In the shipped
build it is an Inspector-set field on a MonoBehaviour, serialized into the
scene as a length-prefixed string followed by the port::

    09 00 00 00  "127.0.0.1"  00 00 00   8d 13 00 00
    |- length 9  |- utf-8     |- pad     |- int32 5005

Unity aligns each field to four bytes, so the port is the next int32 after the
string is padded out. That is the whole format this module relies on.

This is a *heuristic over a serialized asset*, not a documented API. It is
deliberately conservative: a candidate only counts when the preceding int32 is
exactly the string's length and the following int32 is a plausible port, and
two conflicting endpoints in one build are reported as ambiguous rather than
guessed at. Every caller must handle ``None`` by falling back to the value the
user typed - a build that stores its endpoint some other way is a missing
convenience, never a failure.

Qt-free on purpose: the Config GUI and the headless viewer both read builds.
"""

from __future__ import annotations

import os
import re
import struct

#: Scene and asset files worth scanning, in the order they are tried.
_SCAN_PATTERNS = (
    re.compile(r"^level\d+$"),
    re.compile(r"^globalgamemanagers$"),
    re.compile(r"^sharedassets\d*\.assets$"),
)

#: Hosts a client can plausibly dial. A general hostname pattern matches far
#: too much inside a binary asset to be worth the extra reach.
_HOST = re.compile(rb"(?:\d{1,3}(?:\.\d{1,3}){3}|localhost)")

#: Skip anything implausibly large; the endpoint lives in a small scene file.
_MAX_SCAN_BYTES = 64 * 1024 * 1024


def data_directory(build_dir):
    """Return the ``*_Data`` folder inside a Unity build, or None."""
    if not build_dir or not os.path.isdir(build_dir):
        return None
    for name in sorted(os.listdir(build_dir)):
        path = os.path.join(build_dir, name)
        if name.endswith("_Data") and os.path.isdir(path):
            return path
    return None


def scan_files(build_dir):
    """Serialized files in a build that may carry the endpoint, best first."""
    data_dir = data_directory(build_dir)
    if data_dir is None:
        return []
    names = sorted(os.listdir(data_dir))
    ordered = []
    for pattern in _SCAN_PATTERNS:
        for name in names:
            path = os.path.join(data_dir, name)
            if not pattern.match(name) or not os.path.isfile(path):
                continue
            try:
                if os.path.getsize(path) > _MAX_SCAN_BYTES:
                    continue
            except OSError:
                continue
            ordered.append(path)
    return ordered


def endpoints_in(payload):
    """Every ``(host, port)`` the serialized ``payload`` plausibly encodes."""
    found = []
    for match in _HOST.finditer(payload):
        start, end = match.span()
        length = end - start
        # The four bytes before the text must be its own length, or this is
        # some other string that merely contains an address.
        if start < 4:
            continue
        (declared,) = struct.unpack_from("<i", payload, start - 4)
        if declared != length:
            continue
        # Unity pads each field out to a four byte boundary, so the port is
        # the next int32 after the padding.
        port_at = end + (-length % 4)
        if port_at + 4 > len(payload):
            continue
        (port,) = struct.unpack_from("<i", payload, port_at)
        if not 1 <= port <= 65535:
            continue
        host = match.group().decode("ascii")
        if host != "localhost" and any(
            int(octet) > 255 for octet in host.split(".")
        ):
            continue
        found.append((host, port))
    return found


def read_endpoint(build_dir):
    """Return the ``(host, port)`` a build dials, or None if it cannot be read.

    None covers every inconclusive case alike - no build, no scene file, no
    recognisable endpoint, or two that disagree - because a caller can only do
    one thing about any of them: leave the user's own values alone.
    """
    for path in scan_files(build_dir):
        try:
            with open(path, "rb") as handle:
                payload = handle.read()
        except OSError:
            continue
        found = endpoints_in(payload)
        if not found:
            continue
        unique = set(found)
        if len(unique) > 1:
            # Two different endpoints in one build: reporting neither is
            # better than picking the one that happened to serialize first.
            return None
        return found[0]
    return None


def describe_endpoint(endpoint):
    """Format an endpoint for display, or say it could not be determined."""
    if endpoint is None:
        return "unknown"
    host, port = endpoint
    return f"{host}:{port}"
