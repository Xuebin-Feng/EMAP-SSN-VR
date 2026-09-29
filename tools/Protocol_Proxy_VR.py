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

"""A logging TCP proxy between a VR client and the Python viewer.

Forwards every byte unchanged in both directions and writes a JSON-lines
transcript of the conversation: the handshake's counts, a summary of each
state packet (its global settings and transform, plus a hash of the arrays),
and every client message in full. Client messages are small and are what the
headset's gestures produce, so a transcript of a scripted gesture is a
reference for how a client must report it.

The client dials a fixed endpoint, so the proxy takes that endpoint and the
viewer is moved aside. For example, with the viewer's VR_PORT set to 5006:

    python tools/Protocol_Proxy_VR.py --listen-port 5005 --target-port 5006 --out session.jsonl
"""

from __future__ import annotations

import argparse
import hashlib
import json
import socket
import struct
import threading
import time


class Transcript:
    def __init__(self, path, full_packets):
        self._handle = open(path, "a", encoding="utf-8", newline="\n")
        self._lock = threading.Lock()
        self._start = time.monotonic()
        self.full_packets = full_packets

    def write(self, record):
        record = {"t": round(time.monotonic() - self._start, 4), **record}
        with self._lock:
            self._handle.write(json.dumps(record, separators=(",", ":")) + "\n")
            self._handle.flush()

    def close(self):
        self._handle.close()


class ServerStreamParser:
    """Follow the server -> client stream: six binary blocks, then JSON lines."""

    def __init__(self, transcript, connection):
        self.transcript = transcript
        self.connection = connection
        self.buffer = bytearray()
        self.stage = 0          # 0..5 binary blocks, 6 = JSON lines
        self.counts = {}
        self.need = 4
        self.binary_bytes = 0

    def feed(self, data):
        self.buffer += data
        while True:
            if self.stage < 6:
                if len(self.buffer) < self.need:
                    return
                block = bytes(self.buffer[: self.need])
                del self.buffer[: self.need]
                self.binary_bytes += len(block)
                self._advance(block)
            else:
                index = self.buffer.find(b"\n")
                if index < 0:
                    return
                line = bytes(self.buffer[:index])
                del self.buffer[: index + 1]
                self._packet(line)

    def _advance(self, block):
        # Stages alternate: count, payload, count, payload, count, payload.
        names = ("nodes", "render_edges", "full_edges")
        which = names[self.stage // 2]
        if self.stage % 2 == 0:
            (count,) = struct.unpack("<I", block)
            self.counts[which] = count
            self.need = count * (12 if which == "nodes" else 8)
        self.stage += 1
        if self.stage % 2 == 1 and self.need == 0:
            self.stage += 1  # an empty payload
        if self.stage % 2 == 0:
            self.need = 4
        if self.stage >= 6:
            self.transcript.write({
                "dir": "server", "kind": "handshake", "connection": self.connection,
                **self.counts, "bytes": self.binary_bytes,
            })

    def _packet(self, line):
        record = {"dir": "server", "kind": "packet", "connection": self.connection,
                  "bytes": len(line) + 1}
        try:
            packet = json.loads(line)
        except ValueError as error:
            record["error"] = str(error)
        else:
            if self.transcript.full_packets:
                record["packet"] = packet
            else:
                record["globalSettings"] = packet.get("globalSettings")
                record["transformState"] = packet.get("transformState")
                arrays = json.dumps(
                    [packet.get("colors"), packet.get("sizes"), packet.get("visible")],
                    separators=(",", ":")).encode()
                record["arrays_sha256"] = hashlib.sha256(arrays).hexdigest()
                visible = packet.get("visible") or []
                record["hidden"] = sum(1 for value in visible if not value)
        self.transcript.write(record)


class ClientStreamParser:
    """Client -> server messages are always newline-delimited JSON."""

    def __init__(self, transcript, connection):
        self.transcript = transcript
        self.connection = connection
        self.buffer = bytearray()

    def feed(self, data):
        self.buffer += data
        while True:
            index = self.buffer.find(b"\n")
            if index < 0:
                return
            line = bytes(self.buffer[:index])
            del self.buffer[: index + 1]
            record = {"dir": "client", "connection": self.connection, "raw": line.decode("utf-8", "replace")}
            try:
                record["message"] = json.loads(line)
            except ValueError as error:
                record["error"] = str(error)
            self.transcript.write(record)


def _relay(source, target, parser, done):
    try:
        while True:
            data = source.recv(1 << 16)
            if not data:
                break
            target.sendall(data)
            parser.feed(data)
    except OSError:
        pass
    finally:
        done.set()
        for sock in (source, target):
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--listen-port", type=int, default=5005)
    parser.add_argument("--target-port", type=int, default=5006)
    parser.add_argument("--out", required=True, help="transcript file (JSON lines, appended)")
    parser.add_argument("--full", action="store_true", help="record whole state packets, not summaries")
    args = parser.parse_args(argv)

    transcript = Transcript(args.out, args.full)
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    exclusive = getattr(socket, "SO_EXCLUSIVEADDRUSE", None)
    if exclusive is not None:
        listener.setsockopt(socket.SOL_SOCKET, exclusive, 1)
    listener.bind((args.host, args.listen_port))
    listener.listen(1)
    print(f"Proxy {args.host}:{args.listen_port} -> {args.host}:{args.target_port}; "
          f"transcript {args.out}")

    connection = 0
    try:
        while True:
            client, address = listener.accept()
            connection += 1
            try:
                upstream = socket.create_connection((args.host, args.target_port), timeout=10)
                upstream.settimeout(None)
            except OSError as error:
                transcript.write({"kind": "error", "connection": connection,
                                  "error": f"cannot reach the viewer: {error}"})
                client.close()
                continue
            for sock in (client, upstream):
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            transcript.write({"kind": "connect", "connection": connection, "peer": list(address)})
            done = threading.Event()
            threads = [
                threading.Thread(target=_relay, args=(upstream, client, ServerStreamParser(transcript, connection), done), daemon=True),
                threading.Thread(target=_relay, args=(client, upstream, ClientStreamParser(transcript, connection), done), daemon=True),
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
            transcript.write({"kind": "disconnect", "connection": connection})
            for sock in (client, upstream):
                sock.close()
    except KeyboardInterrupt:
        pass
    finally:
        listener.close()
        transcript.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
