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

"""Serve a random network to the VR client, for development and benchmarks.

No layout cache, HDF5 network or alignment is needed: nodes are drawn in
Gaussian clusters, and edges mostly join nodes of the same cluster, which is
roughly how a sequence similarity network looks. The network is served through
the production ``unity_server_loop``, so the client sees exactly what the real
viewer would send it.

    python tools/Synthetic_Server_VR.py --nodes 13000 --edges 500000 --full-edges 4180000

A small prompt then pushes state packets, the way terminal commands do:

    recolor [random|cluster|default]   hide <fraction>   show
    size <value|random>                alpha <edge alpha>  thickness <edge width>
    boundary <width>                   transform           status   quit
"""

from __future__ import annotations

import argparse
import io
import json
import os
import queue
import socket
import sys
import tempfile
import time

_NEUTRAL = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
json.dump({}, _NEUTRAL)
_NEUTRAL.close()
os.environ["SSN_VIEWER_SETTINGS_PATH"] = _NEUTRAL.name

import numpy as np  # noqa: E402

import Protocol_V1_VR as protocol  # noqa: E402


def generate_network(n_nodes, n_edges, n_full, clusters, radius, seed):
    """Positions (float32, N x 3), edge lists (int32, E x 2 and F x 2), clusters.

    ``n_full`` edges are drawn first, as the "unfiltered" connectivity; the
    rendered set is a random subset of them, the way the real viewer
    downsamples. 90% of edges stay inside one cluster.
    """
    rng = np.random.default_rng(seed)
    clusters = max(1, min(clusters, n_nodes))
    centres = rng.normal(0.0, radius * 0.45, size=(clusters, 3))
    membership = rng.integers(0, clusters, size=n_nodes)
    spread = radius * 0.08
    positions = (centres[membership] + rng.normal(0.0, spread, size=(n_nodes, 3))).astype(np.float32)

    n_full = max(n_full, n_edges)
    if n_nodes < 2 or n_full == 0:
        empty = np.zeros((0, 2), dtype=np.int32)
        return positions, empty, empty, membership

    order = np.argsort(membership, kind="stable")
    starts = np.searchsorted(membership[order], np.arange(clusters))
    counts = np.bincount(membership, minlength=clusters)

    first = rng.integers(0, n_nodes, size=n_full)
    second = rng.integers(0, n_nodes, size=n_full)
    local = rng.random(n_full) < 0.9
    home = membership[first[local]]
    offsets = (rng.random(local.sum()) * counts[home]).astype(np.int64)
    second[local] = order[starts[home] + offsets]
    keep = first != second
    full = np.stack([first[keep], second[keep]], axis=1).astype(np.int32)

    if n_edges >= len(full):
        render = full
    else:
        render = full[rng.choice(len(full), size=n_edges, replace=False)]
    return positions, np.ascontiguousarray(render), np.ascontiguousarray(full), membership


class SyntheticViewer:
    """Exactly the viewer surface ``unity_server_loop`` and its reader use."""

    def __init__(self, n_nodes, module, membership_colors):
        self._module = module
        self.n_nodes = n_nodes
        self.running = True
        self.is_connected = False
        self.update_queue = queue.Queue()
        self.default_color = [0.2667, 0.5333, 1.0, 1.0]
        self.cluster_colors = membership_colors
        self.current_colors = np.tile(np.float32(self.default_color), (n_nodes, 1))
        self.current_sizes = np.full(n_nodes, 10.0, dtype=np.float32)
        self.visible_mask = np.ones(n_nodes, dtype=bool)
        self.transform_position = [0.0, 0.0, 0.0]
        self.transform_rotation = [0.0, 0.0, 0.0, 1.0]
        self.transform_scale = [1.0, 1.0, 1.0]
        self.distance_scale = 1.0
        self.settings = {
            "nodeScale": 10.0, "edgeThickness": 1.0, "edgeAlpha": 0.1,
            "nodeBoundaryWidth": 0.5, "neighborColor": "#4488ff",
            "hoverColor": "#ffaa00", "connectedNodeColor": "#ff0000",
            "edgeColor": "#000000", "nodeBoundaryColor": "#000000",
        }

    def get_global_settings(self):
        return dict(self.settings)

    def get_transform_state(self):
        return self._module.HeadlessViewer.get_transform_state(self)

    def update_nodes(self):
        # The production packet builder, run against this object.
        self._module.HeadlessViewer.update_nodes(self)


def _command(viewer, line, rng):
    words = line.split()
    if not words:
        return True
    verb, args = words[0].lower(), words[1:]
    if verb in ("quit", "exit"):
        return False
    if verb == "recolor":
        mode = (args or ["random"])[0]
        if mode == "random":
            viewer.current_colors[:, :3] = rng.random((viewer.n_nodes, 3), dtype=np.float32)
            viewer.current_colors[:, 3] = 1.0
        elif mode == "cluster":
            viewer.current_colors[:] = viewer.cluster_colors
        else:
            viewer.current_colors[:] = viewer.default_color
    elif verb == "hide":
        fraction = float(args[0]) if args else 0.5
        viewer.visible_mask[:] = rng.random(viewer.n_nodes) >= fraction
    elif verb == "show":
        viewer.visible_mask[:] = True
    elif verb == "size":
        if args and args[0] == "random":
            viewer.current_sizes[:] = rng.uniform(4.0, 20.0, viewer.n_nodes)
        else:
            viewer.current_sizes[:] = float(args[0]) if args else 10.0
    elif verb == "alpha":
        viewer.settings["edgeAlpha"] = float(args[0])
    elif verb == "thickness":
        viewer.settings["edgeThickness"] = float(args[0])
    elif verb == "boundary":
        viewer.settings["nodeBoundaryWidth"] = float(args[0])
    elif verb == "transform":
        viewer.transform_position = [0.0, 0.0, 0.0]
        viewer.transform_rotation = [0.0, 0.0, 0.0, 1.0]
        viewer.transform_scale = [1.0, 1.0, 1.0]
        viewer.distance_scale = 1.0
    elif verb == "status":
        print(json.dumps({
            "connected": viewer.is_connected, **viewer.get_transform_state(),
        }))
        return True
    else:
        print(f"unknown command {verb!r}; see the module docstring")
        return True
    viewer.update_nodes()
    return True


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--nodes", type=int, default=13000)
    parser.add_argument("--edges", type=int, default=500000, help="rendered edges (E)")
    parser.add_argument("--full-edges", type=int, default=None, help="full edge list (F); defaults to E")
    parser.add_argument("--clusters", type=int, default=60)
    parser.add_argument("--radius", type=float, default=80.0,
                        help="network radius in cache units; the client shows it at 1/10 in metres")
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5005)
    parser.add_argument("--no-prompt", action="store_true", help="serve until interrupted, without a prompt")
    parser.add_argument("--commands", default="",
                        help="prompt commands to run once a client connects, separated by ';'")
    parser.add_argument("--command-delay", type=float, default=1.0,
                        help="seconds between scripted commands")
    parser.add_argument("--pid-file", default="",
                        help="write this process's id here, so a harness can stop it directly")
    args = parser.parse_args(argv)
    if args.pid_file:
        with open(args.pid_file, "w", encoding="utf-8") as handle:
            handle.write(str(os.getpid()))

    module = protocol.import_viewer_module()
    module.cfg.EXIT_WITH_UNITY = False  # keep serving across client restarts

    started = time.perf_counter()
    positions, render, full, membership = generate_network(
        args.nodes, args.edges, args.full_edges or args.edges,
        args.clusters, args.radius, args.seed)
    rng = np.random.default_rng(args.seed + 1)
    palette = rng.random((max(1, args.clusters), 4)).astype(np.float32)
    palette[:, 3] = 1.0
    viewer = SyntheticViewer(args.nodes, module, palette[membership % len(palette)])
    print(
        f"{args.nodes} nodes, {len(render)} rendered edges, {len(full)} full edges "
        f"generated in {time.perf_counter() - started:.1f} s"
    )

    server = protocol.LoopbackServer(viewer, positions, render, full, host=args.host, port=args.port)
    print(f"Serving on {server.host}:{server.port}. Start the client; type 'quit' to stop.")
    try:
        scripted = [command.strip() for command in args.commands.split(";") if command.strip()]
        if scripted:
            while not viewer.is_connected:
                time.sleep(0.05)
            for command in scripted:
                time.sleep(args.command_delay)
                print(f"scripted: {command}")
                _command(viewer, command, rng)
        if args.no_prompt:
            while True:
                time.sleep(1.0)
        while True:
            try:
                line = input("synthetic> ")
            except EOFError:
                break
            try:
                if not _command(viewer, line, rng):
                    break
            except (ValueError, IndexError) as error:
                print(f"error: {error}")
    except KeyboardInterrupt:
        pass
    finally:
        server.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
