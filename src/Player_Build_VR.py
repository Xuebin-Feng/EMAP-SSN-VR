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

"""Read what an installed VR client build is, from the build itself.

The Godot player ships a small ``vr_client.json`` beside ``EMAP-SSN-VR.exe``,
written by its export script::

    {"client": "EMAP-SSN-VR Godot client", "version": "0.1.0", "protocol": 1,
     "host": "127.0.0.1", "port": 5005, "godot": "4.7.2.stable", "commit": "..."}

The viewer passes the endpoint to the player on its command line, so the two
ends always agree for a launched session; ``host`` and ``port`` here are only
the player's default when it is started by hand. The Config GUI shows that
default, and the viewer compares ``version`` with the release pinned in
``player_release.json`` (which ``install_vr.bat`` installs) to warn about a
stale install.

Every reader is conservative: a missing, unreadable or implausible file reads
as ``None``, and callers fall back to the values the user typed. A build that
cannot be read costs the convenience, never the ability to set things by hand.

Qt-free on purpose: the Config GUI and the headless viewer both read builds.
"""

from __future__ import annotations

import json
import os
import re

#: The sidecar the player's export script writes beside the executable.
MANIFEST_NAME = "vr_client.json"

#: Where install_vr.bat unpacks the client, relative to opt_vr.
DEFAULT_CLIENT_DIR = "player"

#: Folders the Unity client used to live in. A saved VR_APP_DIR still naming
#: one of them predates the Godot client, and means "the installed client".
LEGACY_CLIENT_DIRS = ("unity", "VR_App")

#: The release install_vr.bat installs, at the root of opt_vr.
RELEASE_PIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "player_release.json")

#: Keys the pin must carry, each a non-empty string.
RELEASE_PIN_KEYS = ("version", "tag", "asset", "sha256")

#: Hosts a client can plausibly dial.
_HOST = re.compile(r"^(?:\d{1,3}(?:\.\d{1,3}){3}|localhost)$")

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def migrate_client_dir(value):
    """Point a VR_APP_DIR saved for the Unity client at the Godot client's folder.

    Only the Unity-era defaults move. A folder the user chose themselves is
    left alone, even when no client is installed there yet.
    """
    if isinstance(value, str) and value.strip().replace("\\", "/").strip("/") in LEGACY_CLIENT_DIRS:
        return DEFAULT_CLIENT_DIR
    return value


def read_release_pin(path=RELEASE_PIN):
    """Return ``player_release.json`` when it is complete and plausible, or None."""
    try:
        with open(path, encoding="utf-8") as handle:
            pin = json.load(handle)
    except (OSError, ValueError):
        return None
    if not isinstance(pin, dict):
        return None
    if not all(isinstance(pin.get(key), str) and pin[key] for key in RELEASE_PIN_KEYS):
        return None
    if not _SHA256.match(pin["sha256"]):
        return None
    return pin


def read_client_info(build_dir):
    """Return the parsed ``vr_client.json`` of a build, or None."""
    if not build_dir or not os.path.isdir(build_dir):
        return None
    path = os.path.join(build_dir, MANIFEST_NAME)
    try:
        with open(path, encoding="utf-8") as handle:
            info = json.load(handle)
    except (OSError, ValueError):
        return None
    return info if isinstance(info, dict) else None


def valid_endpoint(host, port):
    """True when ``host`` is an IPv4 address or localhost and ``port`` is a port."""
    if not isinstance(host, str) or not _HOST.match(host):
        return False
    if host != "localhost" and any(int(octet) > 255 for octet in host.split(".")):
        return False
    return isinstance(port, int) and not isinstance(port, bool) and 1 <= port <= 65535


def read_endpoint(build_dir):
    """Return the ``(host, port)`` a build dials by default, or None.

    None covers every inconclusive case alike - no build, no manifest, or one
    whose endpoint is implausible - because a caller can only do one thing
    about any of them: leave the user's own values alone.
    """
    info = read_client_info(build_dir)
    if info is None:
        return None
    host, port = info.get("host"), info.get("port")
    if not valid_endpoint(host, port):
        return None
    return host, port


def describe_endpoint(endpoint):
    """Format an endpoint for display, or say it could not be determined."""
    if endpoint is None:
        return "unknown"
    host, port = endpoint
    return f"{host}:{port}"
