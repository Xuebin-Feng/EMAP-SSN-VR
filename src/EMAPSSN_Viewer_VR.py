import collections
import copy
import socket
import struct
import math
import numpy as np
import time
import os
import h5py
import sys
import threading
import json
import importlib
import traceback
import queue
import subprocess
import glob

# _bootstrap_vr owns sys.path: it puts this directory ahead of the main
# program's src/ so local command overrides win. Appending the directory
# again here would add a second, lower-priority entry.

# Importing _bootstrap_vr also applies any --settings argument the Config GUI
# passed, which must happen before Settings_VR reads its file below.
import _bootstrap_vr
import Single_Instance_VR
import _thread
import Settings_VR as cfg

# Upstream modules do `import EMAPSSN_Config as cfg`, which would pull PySide6
# into this headless process. Publish the Qt-free settings module under that
# name so they can be reused verbatim instead of forked.
#
# This MUST precede any import that reaches an upstream module. Alignment_Manager
# below is the main program's own, so installing the alias afterwards would let
# the real, Qt-importing EMAPSSN_Config load first.
_bootstrap_vr.install_settings_alias(cfg)

import Viewer_Utils_VR as utils
import Player_Build_VR
import Background_Job_Scheduler_VR
import Alignment_Manager
from desktop.Viewer_State import resolve_selected_cache


def _initial_node_rgba():
    """The default node colour, parsed as the desktop viewer parses it.

    Matplotlib accepts named colours as well as hex, so INITIAL_NODE_COLOR =
    "red" colours the nodes red here too. Settings_VR also republishes it as
    NEIGHBOR_COLOR, the name the VR client reads.
    """
    import matplotlib.colors as mcolors

    value = (
        getattr(cfg, 'INITIAL_NODE_COLOR', None)
        or getattr(cfg, 'NEIGHBOR_COLOR', None)
        or '#4488ff'
    )
    try:
        return mcolors.to_rgba(value)
    except (TypeError, ValueError):
        print(f"Warning: {value!r} is not a colour; nodes start #4488ff.")
        return mcolors.to_rgba('#4488ff')


def _initial_edge_threshold():
    """The edge threshold `hide single` applies, as the desktop slider starts.

    The desktop slider starts at the cache's SIMILARITY_THRESHOLD; a cache
    that has none (UMAP topology, a top-percentage filter) starts it at the
    lowest edge score, so every edge counts. -inf means the same here.
    """
    threshold = getattr(cfg, 'SIMILARITY_THRESHOLD', None)
    if threshold is None:
        return float('-inf')
    try:
        return float(threshold)
    except (TypeError, ValueError):
        return float('-inf')


def _console_message(text):
    """Print from a background thread without landing on the prompt."""
    CONSOLE.message(text)


def _discard_queued_packets(update_queue):
    """Drop every queued state packet; each one carries the whole state."""
    while True:
        try:
            update_queue.get_nowait()
        except queue.Empty:
            return


def _sequence_lookup(records):
    """Index canonical FASTA records by full header and by first token.

    The same index the desktop viewer builds (its _build_sequence_lookup).
    """
    lookup = {}
    for header, sequence in records:
        lookup[header] = sequence
        parts = header.split()
        if parts:
            lookup[parts[0]] = sequence
    return lookup


def _saved_distance_scale():
    """The saved Distance Scale, or 1.0 when it is not a positive number."""
    value = getattr(cfg, 'DISTANCE_SCALE', 1.0)
    try:
        scale = float(value)
    except (TypeError, ValueError):
        scale = float('nan')
    if math.isfinite(scale) and scale > 0:
        return scale
    if value not in (None, ""):
        print(f"Warning: Distance Scale {value!r} is not a positive number; using 1.0.")
    return 1.0


def _rescaled_sizes(sizes, base_node_size):
    """Saved node sizes, rescaled to the current NODE_SIZE as the desktop does.

    `save` records the NODE_SIZE its sizes were drawn at as base_node_size.
    Caches written before that attribute existed are read the desktop viewer's
    way: uniform sizes follow NODE_SIZE, varied ones assume a base of 10.
    """
    new_base = float(cfg.NODE_SIZE)
    if base_node_size is not None:
        try:
            old_base = float(base_node_size)
            if old_base > 0 and old_base != new_base:
                return sizes * (new_base / old_base)
        except (TypeError, ValueError) as error:
            print(f"Warning: Failed to rescale cached node sizes: {error}")
        return sizes
    if len(sizes) and np.allclose(sizes, sizes[0]):
        return np.full_like(sizes, new_base)
    return sizes * (new_base / 10.0)


class DummyText:
    def __init__(self):
        self.text = ""

class HeadlessViewer:
    def __init__(self, n_nodes, headers, full_headers, metadata=None, source_records=None):
        self.n_nodes = n_nodes
        self.headers = headers
        self.full_headers = full_headers

        # State arrays, with the desktop viewer's defaults (its _init_colors).
        # A cache that carries a saved session replaces them through
        # restore_cached_state.
        self.current_colors = np.tile(
            _initial_node_rgba(), (n_nodes, 1)
        ).astype(np.float32)
        self.current_sizes = np.full(n_nodes, cfg.NODE_SIZE, dtype=np.float32)
        self.current_shapes = np.full(n_nodes, 'disc', dtype=object)
        self.visible_mask = np.ones(n_nodes, dtype=bool)
        self.node_render_order = np.arange(n_nodes, dtype=np.int32)

        # The terminal runs until the user exits, not until the VR client drops.
        self.running = True
        self.cluster_labels = None
        self.group_labels = [set() for _ in range(n_nodes)]
        self.last_cluster_params = None
        #: Extra root-level cache datasets, which `save` writes back.
        self._cacheable_attrs = set()

        #: The canonical records of the FASTA this layout was built from, and
        #: a header -> sequence index over them. 'export' writes straight from
        #: these, as upstream does, rather than re-reading the file per run.
        #: open_layout_session passes the records verify_layout_cache read.
        if source_records is None:
            source_records = self._load_source_records()
        self._selected_fasta_records = list(source_records)
        self.sequences_map = _sequence_lookup(self._selected_fasta_records)

        # Layout generation writes the initial metadata group (Length, kDa, pI
        # and GRAVY), so the viewer only orders what the cache provides, as the
        # desktop viewer does. A saved group without Length is a deliberate
        # column deletion and stays deleted.
        self.metadata = metadata if metadata is not None else {}
        if self.metadata and "Length" in self.metadata:
            ordered_metadata = {"Length": self.metadata["Length"]}
            for k, v in self.metadata.items():
                if k != "Length":
                    ordered_metadata[k] = v
            self.metadata = ordered_metadata
            
        # Dummy properties for Command compatibility
        self.console_text = DummyText()
        self.tooltip = DummyText()
        self.selected_indices = []
        
        # Undo/Redo Stacks
        self.undo_stack = []
        self.redo_stack = []
        self.max_history = 20
        self.hovered_node_idx = None
        self.selected_node_idx = None
        
        # ---> Persistent Command History (Per Layout) <---
        self.command_history = []
        try:
            cache_path = utils.get_cache_filename()
            folder_name = os.path.basename(os.path.dirname(cache_path))
            history_filename = f"{folder_name}.txt"
            
            history_dir = getattr(cfg, 'HISTORY_DIR', os.path.join("Cache_Files", "History"))
            self.history_file = os.path.join(history_dir, history_filename)
            
            if os.path.exists(self.history_file):
                with open(self.history_file, "r", encoding="utf-8") as f:
                    self.command_history = [line.strip() for line in f if line.strip()]
        except Exception as e:
            print(f"Warning: Could not bind specific history file ({e}). Defaulting format.")
            history_dir = getattr(cfg, 'HISTORY_DIR', os.path.join("Cache_Files", "History"))
            self.history_file = os.path.join(history_dir, "command_history.txt")
            
        self.history_index = len(self.command_history)
        self.update_queue = queue.Queue()
        #: The visibility the newest state packet carried, or that a client
        #: receives on connect; update_selection_visual compares against it.
        self._packet_visible = self.visible_mask.copy()
        self.edges = None  # Full edge list retained for commands
        #: The edge threshold `hide single` applies (the desktop's slider).
        self.current_slider_threshold = _initial_edge_threshold()
        #: Runs `label` and `logo` artifacts, as the desktop's scheduler does.
        self.background_job_scheduler = Background_Job_Scheduler_VR.BackgroundJobScheduler(
            say=_console_message
        )
        
        self.transform_position = [0.0, 0.0, 0.0]
        self.transform_rotation = [0.0, 0.0, 0.0, 1.0]
        self.transform_scale = [1.0, 1.0, 1.0]
        #: Spacing between nodes in the headset. It starts at the saved
        #: Distance Scale; the client's two-hand gesture changes it later.
        self.distance_scale = _saved_distance_scale()
        self.is_connected = False

        # Load the alignment. The offset shifts every reference-anchored
        # position, read and applied exactly as the desktop viewer does, so
        # `query`, `logo`, `label` and residue expressions number alike.
        self.active_reference = getattr(cfg, 'ALIGNMENT_REFERENCE', None)
        try:
            self.alignment_offset = int(getattr(cfg, 'ALIGNMENT_OFFSET', 0))
        except (TypeError, ValueError):
            self.alignment_offset = 0
        self.load_global_alignment()

    def _get_current_state(self):
        """Package the state undo restores: what the desktop's helper covers.

        Besides the visuals, that is the positions, the render order, the
        clustering parameters, the metadata (`meta delete` and `meta upload`
        save their undo step here) and the cache's extra datasets; `save`
        writes all of them, and `export` names its folder after the
        clustering parameters.
        """
        return {
            "pos": self.pos.copy() if hasattr(self, "pos") else None,
            "colors": self.current_colors.copy(),
            "sizes": self.current_sizes.copy(),
            "shapes": self.current_shapes.copy(),
            "visible": self.visible_mask.copy(),
            "node_render_order": self.node_render_order.copy(),
            "cluster_labels": self.cluster_labels.copy() if self.cluster_labels is not None else None,
            "group_labels": [s.copy() for s in self.group_labels],
            "last_cluster_params": self.last_cluster_params,
            "metadata": {
                name: {"type": entry["type"], "values": entry["values"].copy()}
                for name, entry in self.metadata.items()
            },
            "custom": {
                name: copy.deepcopy(getattr(self, name, None))
                for name in self._cacheable_attrs
            },
        }

    def _apply_state(self, snapshot):
        """Restore a _get_current_state snapshot, as the desktop's _apply_state does."""
        if snapshot["pos"] is not None:
            self.pos = snapshot["pos"]
        self.current_colors = snapshot["colors"]
        self.current_sizes = snapshot["sizes"]
        self.current_shapes = snapshot["shapes"]
        self.visible_mask = snapshot["visible"]
        self.node_render_order = snapshot["node_render_order"]
        self.cluster_labels = snapshot["cluster_labels"]
        # The desktop drops the parameters along with the clusters.
        self.last_cluster_params = (
            snapshot["last_cluster_params"] if snapshot["cluster_labels"] is not None else None
        )
        self.group_labels = snapshot["group_labels"]
        self.metadata = snapshot["metadata"]
        for name, value in snapshot["custom"].items():
            setattr(self, name, value)
            self._cacheable_attrs.add(name)
        # A node the restored state hides cannot stay selected.
        self.selected_indices = [i for i in self.selected_indices if self.visible_mask[i]]

    def _save_state(self):
        self.undo_stack.append(self._get_current_state())
        if len(self.undo_stack) > self.max_history:
            self.undo_stack.pop(0)
        self.redo_stack.clear()
        
    def _do_undo(self):
        """Restore the previous state; True when there was one, as on the desktop."""
        if not self.undo_stack:
            print("Nothing to undo.")
            self.console_text.text = "Nothing to undo."
            return False

        snapshot = self.undo_stack.pop()
        self.redo_stack.append(self._get_current_state())
        self._apply_state(snapshot)

        self.update_nodes()
        self.update_edges()

        print("Undo successful.")
        self.console_text.text = "Undo successful."
        return True

    def _do_redo(self):
        """Reapply an undone state; True when there was one, as on the desktop."""
        if not self.redo_stack:
            print("Nothing to redo.")
            self.console_text.text = "Nothing to redo."
            return False

        snapshot = self.redo_stack.pop()
        self.undo_stack.append(self._get_current_state())
        self._apply_state(snapshot)

        self.update_nodes()
        self.update_edges()

        print("Redo successful.")
        self.console_text.text = "Redo successful."
        return True

    def load_global_alignment(self):
        # `reference` reloads through here, so the offset must travel with it,
        # as it does in the desktop viewer.
        try:
            self.alignment = Alignment_Manager.Alignment_Manager(
                cfg.MSA_FILE,
                full_headers=self.full_headers,
                active_reference=self.active_reference,
                alignment_offset=self.alignment_offset,
            )
            # With no MSA, or one that failed to load, the manager has already
            # said why and holds no alignment.
            if getattr(self.alignment, "aln", None) is not None:
                print("Alignment Manager successfully loaded.")
        except Exception as e:
            print(f"Warning: Failed to load Alignment Manager: {e}")
            self.alignment = None
        
    def get_global_settings(self):
        return {
             "nodeScale": float(getattr(cfg, 'NODE_SIZE', 10.0)),
             "edgeThickness": float(getattr(cfg, 'EDGE_WIDTH', 1.0)),
             "edgeAlpha": float(getattr(cfg, 'EDGE_ALPHA', 0.1)),
             "nodeBoundaryWidth": float(getattr(cfg, 'NODE_BOUNDARY_WIDTH', 0.5)),
             "neighborColor": getattr(cfg, 'NEIGHBOR_COLOR', '#4488ff'),
             "hoverColor": getattr(cfg, 'HOVER_COLOR', '#ffaa00'),
             "connectedNodeColor": getattr(cfg, 'CONNECTED_NODE_COLOR', '#ff0000'),
             "edgeColor": getattr(cfg, 'EDGE_COLOR', '#000000'),
             "nodeBoundaryColor": getattr(cfg, 'NODE_BOUNDARY_COLOR', '#000000')
        }

    def get_transform_state(self):
        return {
            "position": self.transform_position,
            "rotation": self.transform_rotation,
            "scale": self.transform_scale,
            "distanceScale": self.distance_scale
        }

    def _load_source_records(self):
        """Canonical (header, sequence) records of the layout's source FASTA.

        The file is read through the main program's load_sanitized_fasta,
        exactly as the desktop viewer and the layout generator read it. Every
        stage of the pipeline sanitizes in memory, so the file itself may never
        have been sanitized; reading it raw would miss every record whose
        header the cache stores in canonical form. A missing or unreadable
        file is not fatal: 'export' then says it has no sequences.
        """
        path = _input_path(
            getattr(cfg, 'NODE_FASTA_FILE', None)
            or getattr(cfg, 'SEQUENCES_FILE', '')
        )
        if not path or not os.path.exists(path):
            return []

        try:
            from utilities.Sequence_Utils import load_sanitized_fasta

            headers, sequences, _ = load_sanitized_fasta(path)
        except Exception as error:
            print(f"Warning: Failed to read the source FASTA ({error}).")
            return []
        return list(zip(headers, sequences))

    def restore_cached_state(self, state):
        """Apply the session state a layout cache carries, as the desktop does.

        `save` writes colours, sizes, shapes, visibility, the render order,
        clusters, groups, the last clustering parameters and any extra
        datasets into every version it writes; the desktop viewer reads all of
        them back when it opens a cache, and so does this. Anything the cache
        lacks keeps the default from __init__. An entry whose length does not
        match the network is skipped with a warning rather than half-applied.
        """
        n_nodes = self.n_nodes

        def fits(name, values, width=None):
            shape = getattr(values, "shape", (len(values),))
            if shape[0] == n_nodes and (width is None or (len(shape) == 2 and shape[1] == width)):
                return True
            print(f"Warning: ignoring the cache's saved {name}: it does not match "
                  f"the {n_nodes} nodes of this network.")
            return False

        colors = state.get("colors")
        if colors is not None and fits("colours", colors, 4):
            self.current_colors = np.asarray(colors, dtype=np.float32)
        sizes = state.get("sizes")
        if sizes is not None and fits("sizes", sizes):
            self.current_sizes = _rescaled_sizes(
                np.asarray(sizes, dtype=np.float32), state.get("base_node_size")
            )
        shapes = state.get("shapes")
        if shapes is not None and fits("shapes", shapes):
            self.current_shapes = np.array(shapes, dtype=object)
        visible = state.get("visible_mask")
        if visible is not None and fits("visibility", visible):
            self.visible_mask = np.asarray(visible, dtype=bool)
            # A client connecting later receives this in its initial packet.
            self._packet_visible = self.visible_mask.copy()
        order = state.get("node_render_order")
        if order is not None:
            import Cache_Manifest as cache_manifest

            try:
                self.node_render_order = cache_manifest.validate_node_render_order(
                    order, n_nodes
                ).copy()
            except ValueError as error:
                print(f"Warning: ignoring the cache's saved render order: {error}")
        clusters = state.get("cluster_labels")
        if clusters is not None and fits("clusters", clusters):
            self.cluster_labels = np.asarray(clusters)
        groups = state.get("group_labels")
        if groups is not None and fits("groups", groups):
            self.group_labels = [set(group) for group in groups]
        if state.get("last_cluster_params") is not None:
            self.last_cluster_params = state["last_cluster_params"]
        for name, value in (state.get("custom") or {}).items():
            # The desktop viewer sets every extra dataset as an attribute.
            # Here one must not replace live viewer state of the same name.
            if hasattr(self, name) and name not in self._cacheable_attrs:
                print(f"Warning: ignoring the cache's dataset {name!r}: it would "
                      "replace viewer state of the same name.")
                continue
            setattr(self, name, value)
            self._cacheable_attrs.add(name)

    def promote_nodes(self, indices):
        """Move one node group to the top of the persistent render order.

        Nothing in the headset changes: the VR client places nodes in 3D, its
        depth buffer decides what occludes what, and ``update_nodes`` never
        sends an order. The desktop viewer's logic is mirrored exactly anyway,
        because ``save`` writes ``node_render_order`` into the layout cache and
        reopening the cache restores it: the saved order must be the one the
        same commands produce in the desktop viewer. A no-op would silently
        flatten it.
        """
        import Cache_Manifest as cache_manifest

        values = np.asarray(indices)
        if values.dtype == np.bool_:
            if values.ndim != 1 or len(values) != self.n_nodes:
                raise ValueError("Node promotion mask must match the node count.")
            promoted = np.flatnonzero(values)
        else:
            promoted = values.astype(np.int64, copy=False).reshape(-1)

        promoted = np.unique(promoted)
        if promoted.size == 0:
            return False
        if np.any(promoted < 0) or np.any(promoted >= self.n_nodes):
            raise ValueError("Node promotion indices are outside the network.")

        current_order = getattr(self, 'node_render_order', None)
        if current_order is None:
            current_order = np.arange(self.n_nodes, dtype=np.int32)
        else:
            current_order = cache_manifest.validate_node_render_order(
                current_order, self.n_nodes
            )

        keep_mask = ~np.isin(current_order, promoted)
        new_order = np.concatenate(
            (current_order[keep_mask], np.sort(promoted))
        ).astype(np.int32, copy=False)
        changed = not np.array_equal(new_order, current_order)
        self.node_render_order = new_order
        return changed

    def update_nodes(self):
        # Package state into JSON, flattened as docs/PROTOCOL.md specifies
        packet = {
            "colors": self.current_colors.flatten().tolist(),
            "sizes": self.current_sizes.tolist(),
            "visible": self.visible_mask.tolist(),
            "globalSettings": self.get_global_settings(),
            "transformState": self.get_transform_state()
        }
        self._packet_visible = self.visible_mask.copy()
        if not self.is_connected:
            # Every packet carries the whole state, so with no client to send
            # them to only the newest matters; ~2 MB each at 13k nodes, they
            # would otherwise pile up until a client connects.
            _discard_queued_packets(self.update_queue)
        self.update_queue.put(packet)
        
    def update_edges(self):
        pass # Handled implicitly by the VR client when nodes update

    def update_selection_visual(self):
        """Send the nodes when their visibility changed, as the desktop redraws them.

        Selection highlighting is handled locally by the VR client, but `hide`
        changes the visibility and then calls only this and update_edges; the
        desktop's version redraws the nodes, and so this sends them. A command
        that only selects, or one that already called update_nodes, leaves the
        visibility as the last packet carried it, and sends nothing more.
        """
        if not np.array_equal(self.visible_mask, self._packet_visible):
            self.update_nodes()
        
    def process_command(self, cmd_str, record_history=True):
        cmd_str = cmd_str.strip()
        if not cmd_str: return
        
        # --- 0. FILE-BACKED HISTORY ---
        # Only record if it's different from the very last command typed
        if record_history:
            if not self.command_history or self.command_history[-1] != cmd_str:
                self.command_history.append(cmd_str)
                try:
                    os.makedirs(os.path.dirname(self.history_file), exist_ok=True)
                    with open(self.history_file, "a", encoding="utf-8") as f:
                        f.write(cmd_str + "\n")

                    # Truncate if file exceeds 1 MB (1,048,576 bytes)
                    if os.path.getsize(self.history_file) > 1048576:
                        # Keep latest ~2000 lines (safely under 1MB limit for string paths)
                        self.command_history = self.command_history[-2000:]
                        with open(self.history_file, "w", encoding="utf-8") as f:
                            for line in self.command_history:
                                f.write(line + "\n")
                except Exception as e:
                    print(f"Warning: Failed to save history to {self.history_file} ({e})")

        self.history_index = len(self.command_history)
        
        parts = cmd_str.split()
        command_name = parts[0].lower()
        if command_name.startswith("vr_"):
            command_name = command_name[3:]
        args = parts[1:]
        
        # A command is a public module of the commands package. Anything else
        # would import something that is not one (`a.b`, `..`, `__init__`)
        # and fail with a misleading error instead.
        if not command_name.isidentifier() or command_name.startswith("_"):
            print(f"Unknown command: {command_name}")
            return False

        module_name = f"commands.{command_name}"
        try:
            module = importlib.import_module(module_name)
            importlib.reload(module)
        except ModuleNotFoundError as error:
            # Discriminate "no such command" from "this command's dependency is
            # missing"; the old handler reported both as "Unknown command",
            # which hid real import failures.
            if error.name in (module_name, command_name):
                print(f"Unknown command: {command_name}")
            else:
                print(
                    f"Command '{command_name}' is unavailable: "
                    f"missing dependency {error.name!r}."
                )
            return False
        except Exception as error:
            print(f"Error loading command '{command_name}': {error}")
            traceback.print_exc()
            return False

        if not hasattr(module, "run"):
            print(f"Error: no run() entry point in commands/{command_name}.py")
            return False

        try:
            module.run(self, args)
        except Exception as error:
            print(f"Command Error: {error}")
            traceback.print_exc()
            return False

def _as_three_dimensional(positions):
    """The VR client expects three floats per node; lift a 2D cache onto z = 0."""
    if positions.ndim != 2 or positions.shape[1] not in (2, 3):
        sys.exit(
            f"Unsupported cache positions shape {positions.shape}; "
            "expected (n_nodes, 2) or (n_nodes, 3)."
        )
    if positions.shape[1] == 3:
        return positions
    print(
        "Warning: this is a 2D layout cache. Lifting it onto the z = 0 plane.\n"
        "         Regenerate with LAYOUT_DIMENSIONS = 3 for a true 3D view."
    )
    lifted = np.zeros((positions.shape[0], 3), dtype=np.float32)
    lifted[:, :2] = positions
    return lifted


def _input_path(value):
    """A configured input path, resolved as the VR settings write it.

    Relative settings that climb out of the submodule resolve against the
    submodule root, not against this module's directory inside src/.
    """
    if value and value.startswith('..'):
        return os.path.normpath(os.path.join(_bootstrap_vr.OPT_VR_DIR, value))
    return value


def _edge_filter_label(settings):
    """Describe the edge filter `settings` name, or None when they name none."""
    try:
        if getattr(settings, "UMAP_MODE", False) is True:
            return f"UMAP topology, {int(settings.UMAP_NEIGHBORS)} neighbours per node"
        top = getattr(settings, "TOP_EDGE_PERCENT", None)
        if top is not None:
            return f"top {float(top)}% of edges"
        threshold = getattr(settings, "SIMILARITY_THRESHOLD", None)
        if threshold is not None:
            return f"score >= {float(threshold)}"
    except (TypeError, ValueError):
        pass
    return None


def _describe_input_mismatch(stored, current):
    """Name the inputs that differ from the files a cache was built from."""
    reasons = []
    for key, setting in (("sequence", "NODE_FASTA_FILE"), ("network", "INPUT_HDF5")):
        recorded = stored["inputs"][key]
        found = current["inputs"][key]
        if recorded.get("sha256") != found["sha256"]:
            reasons.append(
                f"{setting} ({found['basename']}, {found['size_bytes']} bytes) is "
                "not the file this cache was built from "
                f"({recorded.get('basename', '?')}, {recorded.get('size_bytes', '?')} bytes)."
            )
    if not reasons:
        reasons.append("its manifest does not match the current inputs and settings.")
    return " ".join(reasons)


#: What verify_layout_cache established about a cache before it is opened.
VerifiedCache = collections.namedtuple(
    "VerifiedCache", "manifest provenance dimensions records edges edge_scores"
)


def verify_layout_cache(cache_path):
    """Check a cache against the files it was built from, as the desktop does.

    The desktop viewer takes a cache's analysis settings (score, normalization,
    UMAP settings and edge filter) from the cache itself, rebuilds the folder
    manifest from the current NODE_FASTA_FILE and INPUT_HDF5 and requires the
    two to match, then requires the cache's node order to equal the network
    filtered by the sanitised FASTA. This runs the same checks, for 3D caches
    as well as 2D ones, and exits with the reason when one fails. Without them
    an edited FASTA or a different network paired with an older layout, and
    `export` and the edges described files the layout was never built from.

    Returns the FASTA records and the edges the checks produced, so the viewer
    reads neither file a second time.
    """
    import Cache_Manifest as cache_manifest
    from desktop.Viewer_State import prepare_network, resolve_cache_settings
    from utilities.Cache_Metadata import validate_cache_provenance
    from utilities.Sequence_Utils import load_sanitized_fasta

    name = os.path.basename(cache_path)
    folder = os.path.dirname(os.path.abspath(cache_path))
    try:
        # ViewerSettingsError, which this raises, is a ValueError.
        settings = resolve_cache_settings(cache_path, allow_3d=True)
        stored = cache_manifest.read_manifest(folder)
    except (OSError, ValueError) as error:
        sys.exit(f"Cannot open {name}: {error}")

    requested = _edge_filter_label(cfg)
    for key, value in settings.items():
        setattr(cfg, key, value)
    adopted = _edge_filter_label(cfg)
    print(f"Edge filter from the cache manifest: {adopted}.")
    if requested is not None and requested != adopted:
        print(
            f"Note: the settings name {requested}; the cache's own filter is used, "
            "as in the desktop viewer."
        )

    fasta = _input_path(
        getattr(cfg, "NODE_FASTA_FILE", None) or getattr(cfg, "SEQUENCES_FILE", "")
    )
    network = _input_path(getattr(cfg, "INPUT_HDF5", None))
    for setting, path in (("NODE_FASTA_FILE", fasta), ("INPUT_HDF5", network)):
        if not path or not os.path.isfile(path):
            sys.exit(
                f"Cannot open {name}: {setting} {path!r} does not exist. A cache "
                "opens only with the FASTA and network it was built from, as in "
                "the desktop viewer; the edges are drawn from that network."
            )

    layout_mode = str(stored["compatibility"].get("layout_mode", ""))
    dimensions = 3 if layout_mode.endswith("_3d") else 2
    try:
        current = cache_manifest.build_manifest_for_files(
            fasta,
            network,
            alignment_score=cfg.ALIGNMENT_SCORE,
            normalization=cfg.NORM_MODE,
            umap_mode=cfg.UMAP_MODE,
            umap_neighbors=cfg.UMAP_NEIGHBORS,
            top_edge_percent=cfg.TOP_EDGE_PERCENT,
            similarity_threshold=cfg.SIMILARITY_THRESHOLD,
            layout_dimensions=dimensions,
        )
    except (OSError, ValueError) as error:
        sys.exit(f"Cannot open {name}: {error}")
    try:
        manifest = cache_manifest.read_manifest(folder, current["compatibility"])
    except (OSError, ValueError):
        sys.exit(f"Cannot open {name}: {_describe_input_mismatch(stored, current)}")

    try:
        headers, sequences, _ = load_sanitized_fasta(fasta)
        with h5py.File(network, "r") as data:
            expected_headers, edges, edge_scores = prepare_network(
                data, settings=cfg, selected_fasta_headers=headers
            )
        with h5py.File(cache_path, "r") as hf:
            cache_manifest.validate_cache_hdf5(hf, expected_headers, manifest["manifest_id"])
            provenance = validate_cache_provenance(hf.attrs, manifest["manifest_id"])
    except (OSError, KeyError, ValueError) as error:
        sys.exit(f"Cannot open {name}: {error}")

    return VerifiedCache(
        manifest=manifest,
        provenance=provenance,
        dimensions=dimensions,
        records=list(zip(headers, sequences)),
        edges=np.asarray(edges, dtype=np.int32).reshape(-1, 2),
        edge_scores=np.asarray(edge_scores, dtype=np.float32),
    )


def _modified_at(path):
    try:
        return os.path.getmtime(path)
    except OSError:
        return float("-inf")


def _newest_cache_in(folder):
    """The most recently written .h5 in a cache folder, or None.

    Newest means last modified, the order both Config GUIs list a folder's
    caches in: `save` writes version_NN.h5 or a name of the user's choosing,
    so neither the name nor its sort order says which came last.

    The folder name is escaped before globbing: cache folders carry the model
    tag in square brackets (..._[E1_RA]_...), which glob reads as a character
    class and would never match.
    """
    if not folder or not os.path.isdir(folder):
        return None
    candidates = glob.glob(os.path.join(glob.escape(folder), "*.h5"))
    if not candidates:
        return None
    return max(candidates, key=lambda path: (_modified_at(path), path))


def _available_caches():
    """Every cache folder the configured SAVED_LAYOUT_DIR actually holds."""
    root = getattr(cfg, "SAVED_LAYOUT_DIR", None)
    if not root or not os.path.isdir(root):
        return []
    return sorted(
        entry
        for entry in os.listdir(root)
        if _newest_cache_in(os.path.join(root, entry))
    )


def _how_to_get_a_cache():
    """The ways to get a layout cache this viewer can open, for its errors."""
    layout_dir = getattr(cfg, "SAVED_LAYOUT_DIR", None) or "(unset)"
    return (
        "Generate one in the VR Configuration GUI: choose (New Layout Cache) and\n"
        "Save & Run. The main program's src/Layout_Cache_Generator.py builds one too,\n"
        "given a layout settings document with LAYOUT_DIMENSIONS 3 whose\n"
        f"SAVED_LAYOUT_DIR is this viewer's:\n    {layout_dir}\n"
        "Or set TARGET_CACHE_PATH in viewer_settings_vr.json (or the\n"
        "SSN_TARGET_CACHE environment variable) to an existing cache."
    )


def _resolve_cache_path():
    pinned = getattr(cfg, "TARGET_CACHE_FILE", None)
    if pinned:
        resolved = _newest_cache_in(pinned) if os.path.isdir(pinned) else pinned
        if not resolved or not os.path.exists(resolved):
            sys.exit(f"Layout cache not found: {pinned!r}")
        return resolved

    # Nothing pinned, so ask the main program where its cache lives rather than
    # predicting the name here. resolve_selected_cache is what the desktop
    # viewer calls, so opt_vr honours whatever the Config GUI last saved.
    try:
        selected = resolve_selected_cache(cfg)
        flat = resolve_selected_cache(cfg, layout_dimensions=2)
    except Exception as error:
        sys.exit(
            f"Could not work out which layout cache these settings describe: {error}\n\n"
            + _how_to_get_a_cache()
        )

    # The resolver names the folder LAYOUT_DIMENSIONS selects, the "_3D" one
    # for a 3D layout. The 2D folder beside it is the fallback; its
    # coordinates are lifted onto the z = 0 plane.
    folders = list(dict.fromkeys(os.path.dirname(path) for path in (selected, flat)))

    for folder in folders:
        found = _newest_cache_in(folder)
        if found:
            return found
    if os.path.exists(selected):
        return selected

    available = _available_caches()
    listing = (
        "\n\nCaches available in "
        f"{getattr(cfg, 'SAVED_LAYOUT_DIR', '(unset)')}:\n"
        + "\n".join(f"    {name}" for name in available)
        if available
        else ""
    )
    sys.exit(
        "No layout cache matches the current settings. Looked for:\n"
        + "\n".join(f"    {folder}" for folder in folders)
        + "\n\n" + _how_to_get_a_cache() + listing
    )


def load_layout_cache(cache_path=None):
    """Load a layout cache published by the main EMAP-SSN program.

    Coordinates, node order and node metadata all come from the cache; nothing
    here computes a layout. Everything scientific - sanitization, embeddings,
    alignment, network construction, layout generation - is the main program's
    responsibility, and opt_vr is strictly a consumer of its output.
    CACHE_PATH defaults to the one the settings resolve to.

    The cache is checked against the files it was built from first, as the
    desktop viewer checks it (verify_layout_cache), and the result is returned
    last: the manifest, provenance and FASTA records the check read.
    """
    cache_path = cache_path or _resolve_cache_path()
    print(f"Loading layout cache: {cache_path}")
    source = verify_layout_cache(cache_path)

    metadata = {}
    with h5py.File(cache_path, "r") as hf:
        positions = hf["positions"][:].astype(np.float32)
        raw_headers = hf["headers"][:]
        headers = [
            value.decode("utf-8") if isinstance(value, bytes) else str(value)
            for value in raw_headers
        ]
        dimensions = int(hf.attrs.get("layout_dimensions", positions.shape[1]))

        if "metadata" in hf:
            group = hf["metadata"]
            for name in group.keys():
                dataset = group[name]
                prop_type = dataset.attrs.get("type", "text")
                raw_values = dataset[:]
                # Read exactly as the desktop viewer reads it: every number,
                # Length included, as float64; `meta` and the HUD formatter
                # show integral values without decimals.
                if prop_type == "number":
                    values = raw_values.astype(np.float64)
                else:
                    values = np.array(
                        [
                            value.decode("utf-8")
                            if isinstance(value, bytes)
                            else str(value)
                            for value in raw_values
                        ],
                        dtype=object,
                    )
                metadata[name] = {"type": prop_type, "values": values}

    positions = _as_three_dimensional(positions)
    n_nodes = len(positions)
    if len(headers) != n_nodes:
        sys.exit(
            f"Cache is inconsistent: {len(headers)} headers for "
            f"{n_nodes} positions."
        )

    edges, edge_scores = source.edges, source.edge_scores
    print(
        f"Loaded {n_nodes} nodes and {len(edges)} edges "
        f"from a {dimensions}D cache."
    )
    return positions, edges, edge_scores, n_nodes, headers, list(headers), metadata, source


#: Root-level cache datasets with a fixed meaning. Any other dataset is a
#: custom attribute, exactly as the desktop viewer's loader treats it.
_CORE_CACHE_DATASETS = frozenset({
    "headers", "positions", "colors", "sizes", "shapes", "visible_mask",
    "cluster_labels", "group_labels", "metadata", "connectivity",
    "edge_scores", "node_render_order",
})


def _decoded(value):
    return value.decode("utf-8") if isinstance(value, bytes) else value


def read_saved_session(cache_path):
    """The session state a layout cache carries, read as the desktop reads it.

    Everything `save` writes beside the positions: colours, sizes and the
    NODE_SIZE they were drawn at, shapes, visibility, the render order,
    clusters, groups, the last clustering parameters and any extra datasets.
    HeadlessViewer.restore_cached_state applies it. A freshly generated cache
    carries none of it, and the viewer keeps its defaults.
    """
    state = {"custom": {}}
    with h5py.File(cache_path, "r") as hf:
        if "colors" in hf:
            state["colors"] = hf["colors"][:]
        if "sizes" in hf:
            state["sizes"] = hf["sizes"][:].astype(np.float32)
            state["base_node_size"] = hf.attrs.get("base_node_size", None)
        if "shapes" in hf:
            state["shapes"] = [_decoded(value) for value in hf["shapes"][:]]
        if "visible_mask" in hf:
            state["visible_mask"] = hf["visible_mask"][:]
        if "node_render_order" in hf:
            state["node_render_order"] = hf["node_render_order"][:]
        if "cluster_labels" in hf:
            state["cluster_labels"] = hf["cluster_labels"][:]
        if "group_labels" in hf:
            state["group_labels"] = json.loads(_decoded(hf["group_labels"][()]))
        if "last_cluster_params" in hf.attrs:
            value = _decoded(hf.attrs["last_cluster_params"])
            if isinstance(value, str) and value.startswith("["):
                state["last_cluster_params"] = tuple(json.loads(value))
            else:
                state["last_cluster_params"] = tuple(value)
        for name in hf.keys():
            dataset = hf[name]
            if name in _CORE_CACHE_DATASETS or not isinstance(dataset, h5py.Dataset):
                continue
            if dataset.attrs.get("is_json", False):
                state["custom"][name] = json.loads(_decoded(dataset[()]))
            else:
                state["custom"][name] = dataset[()] if dataset.shape == () else dataset[:]
    return state


def _bind_layout_cache(viewer, source):
    """Record the cache binding the shared `save` command requires.

    `save` writes a new version into the folder of the cache this session
    loaded, and refuses unless the viewer carries that folder's manifest ID
    and the cache's provenance, the binding the desktop viewer records when it
    opens a cache. `source`, from verify_layout_cache, holds both. A 2D cache
    is left unbound: its positions were lifted onto z = 0, and saving them
    would put 3D coordinates in a 2D layout folder. It still opens; only
    `save` is unavailable, and the reason is printed now rather than at save
    time.
    """
    if source.dimensions != 3:
        print(
            "Note: save is unavailable for a 2D cache; its positions were lifted "
            "onto z = 0. Regenerate with LAYOUT_DIMENSIONS = 3 to save VR edits."
        )
        return
    viewer.cache_manifest = source.manifest
    viewer.cache_manifest_id = source.manifest["manifest_id"]
    viewer._cache_provenance = source.provenance


def open_layout_session():
    """Resolve, pin and load this session's layout cache into a bound viewer.

    The resolved path is pinned before the viewer is built, so every later
    lookup agrees with what is on screen: HeadlessViewer names its command
    history through utils.get_cache_filename, which reads TARGET_CACHE_FILE,
    and the shared `save` gets its folder from resolve_selected_cache, which
    returns TARGET_CACHE_PATH first. Save & Run sets both; a direct launch
    that resolved the cache here set neither.
    """
    cache_path = _resolve_cache_path()
    cfg.TARGET_CACHE_PATH = cache_path
    cfg.TARGET_CACHE_FILE = cache_path
    pos, edges, edge_scores, n_nodes, headers, full_headers, metadata, source = (
        load_layout_cache(cache_path)
    )

    viewer = HeadlessViewer(
        n_nodes, headers, full_headers, metadata, source_records=source.records
    )
    # A version `save` wrote carries the session it saved; reopen it as the
    # desktop viewer would, instead of starting from the defaults again.
    viewer.restore_cached_state(read_saved_session(cache_path))
    viewer.edges = edges  # Retain full edge list for viewing purposes/commands
    viewer.edge_scores = edge_scores
    # Commands such as `save` read viewer.pos; without these two lines the
    # positions existed only as a local and every `save` raised
    # AttributeError.
    viewer.pos = pos
    viewer.original_pos = pos.copy()
    _bind_layout_cache(viewer, source)
    return viewer


def _simple_terminal_loop(viewer):
    """Line-based fallback for hosts without msvcrt (Linux, macOS).

    No arrow-key history, but the viewer stays usable. input() blocks, so a
    VR client disconnect is noticed on the next command rather than immediately.
    """
    while viewer.running:
        try:
            command = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nExiting terminal...")
            viewer.running = False
            raise KeyboardInterrupt
        if command.lower() in ("exit", "quit"):
            viewer.running = False
            return
        if command:
            viewer.process_command(command)


def terminal_loop(viewer):
    print("--- Terminal Ready. Type 'help' for a list of commands ---")
    if not viewer.is_connected:
        print("    (The VR client is not connected yet; commands still work and "
              "the view syncs on connect.)")
    
    # We use msvcrt for low-level keyboard polling to completely bypass the 
    # buggy line-editor/echo behavior in the IDE or hooked Windows console.
    try:
        import msvcrt
    except ImportError:
        # Not Windows: fall back to a plain line reader rather than
        # failing at import.
        _simple_terminal_loop(viewer)
        return
    
    while viewer.running:
        try:
            cmd_chars = []
            CONSOLE.show_prompt("> ", cmd_chars)

            if hasattr(viewer, 'command_history'):
                viewer.history_index = len(viewer.command_history)
                
            while viewer.running:
                if msvcrt.kbhit():
                    ch = msvcrt.getwch()
                    
                    # Enter key
                    if ch in ('\r', '\n'):
                        CONSOLE.end_prompt()
                        break
                    # Backspace
                    elif ch == '\x08':
                        CONSOLE.erase()
                    # Ctrl+C
                    elif ch == '\x03':
                        raise KeyboardInterrupt
                    # Arrow keys and other special key prefixes
                    elif ch in ('\xe0', '\x00'):
                        scan_code = msvcrt.getwch()
                        if scan_code == 'H':  # Up Arrow
                            if hasattr(viewer, 'command_history') and viewer.command_history:
                                viewer.history_index = max(0, viewer.history_index - 1)
                                new_cmd = viewer.command_history[viewer.history_index]
                                # Swap in the recalled command. CONSOLE edits
                                # cmd_chars and the screen together, so a
                                # message always redraws what was on screen.
                                CONSOLE.erase(len(cmd_chars))
                                CONSOLE.type(new_cmd)
                        elif scan_code == 'P':  # Down Arrow
                            if hasattr(viewer, 'command_history') and viewer.command_history:
                                viewer.history_index = min(len(viewer.command_history), viewer.history_index + 1)
                                if viewer.history_index == len(viewer.command_history):
                                    new_cmd = ""
                                else:
                                    new_cmd = viewer.command_history[viewer.history_index]
                                CONSOLE.erase(len(cmd_chars))
                                CONSOLE.type(new_cmd)
                    # Normal characters
                    else:
                        CONSOLE.type(ch)
                else:
                    time.sleep(0.01)
                    
            if not viewer.running:
                CONSOLE.end_prompt()
                break

            cmd = "".join(cmd_chars).strip()
            if cmd.lower() in ("exit", "quit"):
                viewer.running = False
                return
            if cmd:
                viewer.process_command(cmd)
        except KeyboardInterrupt:
            print("\nExiting terminal...")
            raise KeyboardInterrupt
        except Exception as e:
            print(f"Terminal error: {e}")
            break

def client_reader_loop(client, viewer):
    try:
        rfile = client.makefile('r', encoding='utf-8')
        for line in rfile:
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                if data.get("type") == "transform":
                    viewer.transform_position = data.get("position", viewer.transform_position)
                    viewer.transform_rotation = data.get("rotation", viewer.transform_rotation)
                    viewer.transform_scale = data.get("scale", viewer.transform_scale)
                    viewer.distance_scale = data.get("distanceScale", viewer.distance_scale)
            except Exception as ex:
                CONSOLE.message(f"[Warning] Failed to parse VR client JSON: {ex}")
                CONSOLE.message(f"Raw line: {repr(line)}")
    except Exception as e:
        CONSOLE.message(f"[Warning] Client reader loop encountered exception: {e}")
    finally:
        viewer.is_connected = False

class PromptConsole:
    """Serialise terminal output so a message never lands on the prompt.

    The VR server runs in its own thread and prints whenever a client
    connects, receives the layout, or drops, while the main thread is sitting
    on "> " with a possibly half-typed command. Printing straight to stdout
    puts the message *after* that prompt, so the prompt scrolls away and the
    cursor is left on a bare line - which reads as a terminal that has stopped
    accepting input, and is why pressing Enter looked necessary to get the
    prompt back.

    The cure is to treat the prompt as state rather than as characters already
    written: a background message erases it, prints, and draws it again with
    whatever had been typed so far. The lock also stops a message from landing
    between the prompt and its echoed keystrokes.
    """

    def __init__(self, stream=None):
        self._lock = threading.RLock()
        self._stream = stream
        self._prompt = ""
        self._typed = None
        self._visible = False

    @property
    def stream(self):
        # Resolved late: the launcher reconfigures sys.stdout for UTF-8 before
        # the viewer starts, and a stream captured at import would miss it.
        return self._stream if self._stream is not None else sys.stdout

    def show_prompt(self, prompt, typed):
        """Draw `prompt` and remember it, so a message can restore it.

        `typed` is kept by reference and must be mutated in place; rebinding it
        would leave this holding the previous list and redraw a stale line.
        """
        with self._lock:
            self._prompt = prompt
            self._typed = typed
            self._visible = True
            self._write(prompt + "".join(typed))

    def type(self, text):
        """Add `text` to the command and echo it, in one step.

        Done apart, a message between the two would redraw the line with
        `text` already in it, and the echo would then show it twice.
        """
        with self._lock:
            self._typed.extend(text)
            self._write(text)

    def erase(self, count=1):
        """Delete up to `count` characters from the end of the command.

        Stops at the prompt, so a backspace on an empty command does nothing.
        """
        with self._lock:
            count = min(count, len(self._typed))
            del self._typed[len(self._typed) - count:]
            self._write("\b \b" * count)

    def end_prompt(self, newline=True):
        """The prompt is finished with; messages may print freely again."""
        with self._lock:
            if newline:
                self._write("\n")
            self._visible = False
            self._typed = None

    def message(self, text=""):
        """Print `text` above the prompt, then put the prompt back."""
        with self._lock:
            if self._visible:
                self._write("\r" + " " * self._width() + "\r")
            self._write(str(text).rstrip("\n") + "\n")
            if self._visible:
                self._write(self._prompt + "".join(self._typed or ()))

    def _width(self):
        return len(self._prompt) + len(self._typed or ())

    def _write(self, text):
        stream = self.stream
        stream.write(text)
        stream.flush()


#: One console for the process. The server thread and the terminal both go
#: through it, which is the only way their output can be ordered at all.
CONSOLE = PromptConsole()


def should_exit_with_unity():
    """Whether losing the VR client should end the viewer.

    On by default: the viewer exists to drive the headset, so it follows the
    client out rather than leaving an orphaned process holding the port. Off
    keeps the command console alive after the app closes, which is the point
    while debugging.

    The name and the EXIT_WITH_UNITY key predate the Godot client; saved
    settings and profiles still use them.
    """
    return bool(getattr(cfg, "EXIT_WITH_UNITY", True))


def unity_server_loop(server_socket, viewer, pos, edges_to_send, n_nodes, n_edges_to_send, unfiltered_edges):
    """Serve VR clients one at a time; docs/PROTOCOL.md is the contract.

    Named for the Unity client it first served. The tests and tools/ drive
    this loop by name, so it keeps it.
    """
    try:
        while True:
            client, addr = server_socket.accept()
            CONSOLE.message(f"VR client connected from {addr}")
            
            try:
                # 1. Send Node Count
                client.sendall(struct.pack('<I', n_nodes))
                # 2. Send Node Positions (now 3D)
                pos_bytes = pos.astype('<f4').tobytes()
                client.sendall(pos_bytes)
                
                # 3. Send Edge Count (Rendered edges)
                client.sendall(struct.pack('<I', n_edges_to_send))
                # 4. Send Edges (Rendered edges, pairs of int32)
                edge_bytes = edges_to_send.astype('<i4').tobytes()
                client.sendall(edge_bytes)

                # 5. Send Unfiltered Edge Count
                n_unfiltered = len(unfiltered_edges)
                client.sendall(struct.pack('<I', n_unfiltered))
                # 6. Send Unfiltered Edges (pairs of int32)
                unfiltered_bytes = unfiltered_edges.astype('<i4').tobytes()
                client.sendall(unfiltered_bytes)
                
                CONSOLE.message(
                    "Successfully sent initial binary layout. "
                    "Establishing persistent JSON connection..."
                )
                
                # Send initial state (colors, sizes, visible, settings, transform).
                # It is the current state, so a packet queued before it is
                # older and, sent after it, would undo part of it.
                _discard_queued_packets(viewer.update_queue)
                initial_packet = {
                    "colors": viewer.current_colors.flatten().tolist(),
                    "sizes": viewer.current_sizes.tolist(),
                    "visible": viewer.visible_mask.tolist(),
                    "globalSettings": viewer.get_global_settings(),
                    "transformState": viewer.get_transform_state()
                }
                client.sendall((json.dumps(initial_packet) + "\n").encode('utf-8'))
                
                # Mark as connected
                viewer.is_connected = True
                
                # Start reader thread for this client
                reader_thread = threading.Thread(target=client_reader_loop, args=(client, viewer), daemon=True)
                reader_thread.start()
                
                # Enter persistent update loop
                while viewer.is_connected:
                    if not viewer.update_queue.empty():
                        packet = viewer.update_queue.get()
                        json_str = json.dumps(packet) + "\n"
                        client.sendall(json_str.encode('utf-8'))
                    else:
                        time.sleep(0.05)
            except (ConnectionResetError, BrokenPipeError, ConnectionAbortedError, socket.error):
                pass
            finally:
                viewer.is_connected = False
                try:
                    client.close()
                except Exception:
                    pass
                if _restart_requested_client(viewer):
                    pass  # its successor connects next; keep accepting
                elif should_exit_with_unity():
                    CONSOLE.message(
                        f"VR client {addr} disconnected. Closing the viewer.\n"
                        '         Turn "Quit with VR Client" off in the VR '
                        "Configuration GUI to keep the console running instead."
                    )
                    viewer.running = False
                    # The main thread may be blocked reading a command, so ask
                    # for the same KeyboardInterrupt that Ctrl+C would raise and
                    # let the existing shutdown path do the cleanup.
                    _thread.interrupt_main()
                    return
                else:
                    CONSOLE.message(
                        f"VR client {addr} disconnected. Waiting for a new connection..."
                    )
    except Exception as e:
        CONSOLE.message(f"Server loop shutting down: {e}")

#: Where install_vr.bat unpacks the VR client, relative to opt_vr.
DEFAULT_PLAYER_DIR = Player_Build_VR.DEFAULT_CLIENT_DIR


def vr_app_search_dirs():
    """Directories that may hold the VR client, most specific first."""
    script_dir = _bootstrap_vr.OPT_VR_DIR
    configured = getattr(cfg, "VR_APP_DIR", DEFAULT_PLAYER_DIR) or DEFAULT_PLAYER_DIR
    dirs = [
        # The setting wins, resolved against opt_vr when it is relative.
        configured if os.path.isabs(configured)
        else os.path.join(script_dir, configured),
    ]
    # A folder chosen by hand may hold no client; fall through to where
    # install_vr.bat puts it.
    default = os.path.join(script_dir, DEFAULT_PLAYER_DIR)
    if os.path.normcase(os.path.normpath(dirs[0])) != os.path.normcase(os.path.normpath(default)):
        dirs.append(default)
    return dirs


def _is_player(path):
    # Godot names a console wrapper <name>.console.exe; it is not the player.
    return "console" not in os.path.basename(path).lower()


def find_vr_app():
    """Return the VR client executable, or None if none is installed."""
    for search_dir in vr_app_search_dirs():
        search_dir = os.path.normpath(search_dir)
        if not os.path.isdir(search_dir):
            continue
        candidates = sorted(
            path
            for path in glob.glob(os.path.join(glob.escape(search_dir), "*.exe"))
            if _is_player(path)
        )
        if candidates:
            return os.path.abspath(candidates[0])

    return None


def _is_newer_version(installed, pinned):
    """True when `installed` is a later release than `pinned`."""
    try:
        from packaging.version import InvalidVersion, Version
    except ImportError:  # pragma: no cover - packaging ships with the environment
        return False
    try:
        return Version(str(installed)) > Version(str(pinned))
    except (InvalidVersion, TypeError):
        return False


def _is_player_dir(folder):
    player_dir = os.path.join(_bootstrap_vr.OPT_VR_DIR, DEFAULT_PLAYER_DIR)
    return os.path.normcase(os.path.normpath(folder)) == os.path.normcase(os.path.normpath(player_dir))


def warn_about_stale_player(exe_path):
    """Say so when the installed client is not the release this checkout pins.

    A `git pull` can move the pin to a newer client while player/ keeps the
    old one. It is started anyway; the note says how to update it. A newer
    client, such as a test build, is started as it is. A folder without
    vr_client.json holds no EMAP-SSN-VR client release at all - a Unity-era
    build a saved VR Client Build folder still names, for example - and gets
    a note saying how to go back to the pinned client. Returns the installed
    version, or None when the build does not say.
    """
    folder = os.path.dirname(exe_path)
    info = Player_Build_VR.read_client_info(folder)
    pin = Player_Build_VR.read_release_pin()
    pinned = pin["version"] if pin else None
    if info is None:
        if _is_player_dir(folder):
            CONSOLE.message(
                "Note: player/ has no vr_client.json, so the installed VR client's "
                "version is unknown. Run install_vr.bat to replace it with the "
                "pinned release."
            )
        else:
            CONSOLE.message(
                f"Note: {folder} has no vr_client.json, so "
                f"{os.path.basename(exe_path)} is not an EMAP-SSN-VR client "
                "release (a Unity-era build, for example). Set VR Client Build in "
                "the VR Configuration GUI back to player to use the pinned client."
            )
        return None
    installed = info.get("version")
    if pinned and installed and installed != pinned:
        if _is_newer_version(installed, pinned):
            CONSOLE.message(
                f"Note: the installed VR client is {installed}, newer than the "
                f"{pinned} this checkout pins, so it is started as it is. Run "
                f"install_vr.bat to install {pinned} instead."
            )
        else:
            CONSOLE.message(
                f"Note: the installed VR client is {installed}, but this checkout pins "
                f"{pinned}. Run install_vr.bat to update it."
            )
    return installed


def warn_about_vr_hardware():
    """Say so when the client is about to start on hardware that cannot run it.

    This is the moment it matters: an Intel Arc GPU will take the layout
    happily and then fail to present it, because SteamVR refuses to start at
    all. A warning here costs under a second and turns "the headset stayed
    black" into something with a cause attached.

    It warns and continues rather than refusing. The check reads adapter names,
    which is a weaker thing to know than whether a headset actually works, and
    a false negative that blocked a working setup would be worse than the
    problem it prevents.
    """
    try:
        import Detect_GPU_VR

        report = Detect_GPU_VR.check()
    except Exception as error:
        CONSOLE.message(f"Note: could not check VR hardware: {error}")
        return None
    if report["verdict"] != Detect_GPU_VR.READY:
        CONSOLE.message(f"Warning: {Detect_GPU_VR.summary(report)}")
    return report


#: Listening on every interface is reachable locally through the loopback.
_WILDCARD_HOSTS = ("", "0.0.0.0")


#: The exit code with which the VR client asks to be started again
#: (docs/PROTOCOL.md, "Starting the client").
CLIENT_RESTART_EXIT_CODE = 75


def player_command(exe_path, host, port, restartable=True):
    """The command line that starts the VR client dialling `host`:`port`.

    Everything after `--` is the client's own; this viewer is the one place
    that decides the endpoint, so the two ends can never disagree about it.
    `restartable` tells the client it may exit with CLIENT_RESTART_EXIT_CODE
    to be started again.
    """
    host = str(host).strip()
    if host in _WILDCARD_HOSTS:
        host = "127.0.0.1"
    command = [exe_path, "--", "--host", host, "--port", str(int(port))]
    if restartable:
        command.append("--restartable")
    return command


#: Downloads, checks and unpacks the pinned VR client; install_vr.bat runs it too.
CLIENT_INSTALLER = os.path.join(_bootstrap_vr.VR_SRC_DIR, "bin", "Install_Client_VR.ps1")


def ensure_vr_client(say=print):
    """Install or update the VR client when player/ lacks the pinned release.

    A checkout that was just pulled may pin a client player/ does not hold
    yet, or player/ may be empty on a first run. Either way this runs the
    installer install_vr.bat uses, which downloads the pinned release, checks
    its SHA-256 and unpacks it, so pulling is all an update takes. A client
    the user pointed VR_APP_DIR at is theirs, and is left alone. If the
    install fails, for example offline, whatever client is installed is used.
    An automatic update never moves player/ backwards: a newer client there,
    such as a test build installed with build_release.ps1 -InstallTo, is kept,
    and install_vr.bat remains the way to install the pinned one over it.
    Returns True when player/ holds the pinned release afterwards.
    """
    pin = Player_Build_VR.read_release_pin()
    if pin is None:
        return False
    player_dir = os.path.join(_bootstrap_vr.OPT_VR_DIR, DEFAULT_PLAYER_DIR)
    configured = os.path.normcase(os.path.normpath(vr_app_search_dirs()[0]))
    if configured != os.path.normcase(os.path.normpath(player_dir)) and os.path.isdir(configured) \
            and any(_is_player(path) for path in glob.glob(os.path.join(glob.escape(configured), "*.exe"))):
        return False
    installed = (Player_Build_VR.read_client_info(player_dir) or {}).get("version")
    has_client = os.path.isfile(os.path.join(player_dir, "EMAP-SSN-VR.exe"))
    if installed == pin["version"] and has_client:
        return True
    if has_client and _is_newer_version(installed, pin["version"]):
        say(f"player/ holds VR client {installed}, newer than the {pin['version']} "
            "this checkout pins, so Save & Run keeps it. install_vr.bat installs "
            f"{pin['version']} over it.")
        return False
    say(f"Installing VR client {pin['version']} into {player_dir}...")
    # Windows PowerShell cannot load its own modules with PowerShell 7's
    # module path, which a terminal may pass down; unset, it uses its own.
    environment = {key: value for key, value in os.environ.items() if key.upper() != "PSMODULEPATH"}
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
             CLIENT_INSTALLER, "-OptVr", _bootstrap_vr.OPT_VR_DIR],
            env=environment,
        )
    except OSError as error:
        say(f"Could not run the VR client installer: {error}")
        return False
    if result.returncode != 0:
        say("The VR client could not be installed; see above. The installed client, "
            "if any, is used instead.")
        return False
    return True


def launch_vr_app(host="127.0.0.1", port=5005, restartable=True, say=print):
    """Start the installed VR client, telling it where this viewer listens.
    Returns the subprocess.Popen object if launched, or None if not found.

    `say` prints the messages; the server thread passes CONSOLE.message so a
    restart cannot land on the command prompt. The first launch installs or
    updates the pinned client first (ensure_vr_client).
    """
    if restartable:
        ensure_vr_client(say)
    exe_path = find_vr_app()
    if exe_path is None:
        say("VR client not found. Run install_vr.bat to download it.")
        say("  Searched:")
        for search_dir in vr_app_search_dirs():
            say(f"    {os.path.normpath(search_dir)}")
        say("  The viewer keeps listening; a client started by hand can still connect.")
        return None

    if restartable:
        # Checked once, at the first launch; a restart is the same hardware.
        warn_about_vr_hardware()
        warn_about_stale_player(exe_path)
    say(f"Launching the VR client: {exe_path}")
    try:
        proc = subprocess.Popen(
            player_command(exe_path, host, port, restartable),
            cwd=os.path.dirname(exe_path),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        say(f"VR client launched (PID {proc.pid}). Waiting for it to connect...")
        return proc
    except Exception as e:
        say(f"Failed to launch the VR client: {e}")
        say("The viewer keeps listening; a client started by hand can still connect.")
        return None


def _restart_requested_client(viewer):
    """Start the VR client again if it just quit asking for that.

    The client asks, by exiting with CLIENT_RESTART_EXIT_CODE, when SteamVR
    bound its controllers before it knew them; a fresh start fixes that. It
    is started again without --restartable, so it asks at most once. Returns
    True when a new client is on its way.
    """
    proc = getattr(viewer, "vr_proc", None)
    endpoint = getattr(viewer, "vr_endpoint", None)
    if proc is None or endpoint is None:
        return False
    try:
        # The socket closes as the client quits, so its exit is moments away.
        code = proc.wait(timeout=3)
    except subprocess.TimeoutExpired:
        return False
    if code != CLIENT_RESTART_EXIT_CODE:
        return False
    CONSOLE.message(
        "SteamVR bound the controllers before it knew them, so the VR client "
        "is restarting to pick up their own bindings."
    )
    host, port = endpoint
    viewer.vr_proc = launch_vr_app(host, port, restartable=False, say=CONSOLE.message)
    return viewer.vr_proc is not None

def _consume_launch_snapshot():
    """Delete the per-launch settings snapshot the Config GUI handed us.

    Settings_VR has already read the file by the time this runs, so removing it
    here honours --delete-settings exactly as the desktop viewer does.
    """
    path = _bootstrap_vr.SETTINGS_SNAPSHOT_TO_DELETE
    _bootstrap_vr.SETTINGS_SNAPSHOT_TO_DELETE = None
    if not path:
        return
    try:
        os.unlink(path)
    except OSError:
        pass


def start_server(host=None, port=None):
    _consume_launch_snapshot()
    # The endpoint is a setting; launch_vr_app() hands the same one to the
    # client on its command line.
    host = host or getattr(cfg, 'VR_HOST', '127.0.0.1')
    port = int(port or getattr(cfg, 'VR_PORT', 5005))
    viewer = open_layout_session()
    pos, edges, edge_scores, n_nodes = (
        viewer.pos, viewer.edges, viewer.edge_scores, viewer.n_nodes
    )

    # --- Intelligent Edge Downsampling for VR Rendering ---
    MAX_RENDER_EDGES = int(getattr(cfg, 'MAX_RENDER_EDGES', 500000))
    enable_filtering = getattr(cfg, 'ENABLE_EDGE_FILTERING', True)
    if enable_filtering and len(edges) > MAX_RENDER_EDGES:
        print(f"Network has {len(edges)} edges. Downsampling to {MAX_RENDER_EDGES} for rendering.")
        print("Using skewed normal distribution to prioritize weaker inter-cluster connections...")
        
        s_min = np.min(edge_scores)
        s_max = np.max(edge_scores)
        sigma = (s_max - s_min) / 3.0
        
        if sigma > 0:
            weights = np.exp(-((edge_scores - s_min)**2) / (2 * sigma**2))
        else:
            weights = np.ones(len(edges))
            
        weights /= np.sum(weights) # Normalize to create probability distribution
        
        sampled_indices = np.random.choice(len(edges), size=MAX_RENDER_EDGES, replace=False, p=weights)
        edges_to_send = edges[sampled_indices]
    else:
        if not enable_filtering:
            print(f"Edge downsampling is disabled. Passing all {len(edges)} edges to the VR client.")
        edges_to_send = edges

    n_edges_to_send = len(edges_to_send)
    
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    # SO_REUSEADDR on Windows lets an unrelated process bind a port this one is
    # already serving and take the connections with it. SO_EXCLUSIVEADDRUSE is
    # the opposite, and turns a clash into an error someone can act on.
    exclusive = getattr(socket, "SO_EXCLUSIVEADDRUSE", None)
    if exclusive is not None:
        server_socket.setsockopt(socket.SOL_SOCKET, exclusive, 1)
    try:
        server_socket.bind((host, port))
    except OSError as error:
        server_socket.close()
        sys.exit(
            f"Could not listen on {host}:{port}: {error}\n\n"
            "Something else already holds that endpoint.\n"
            "Close whatever is using the port, or choose another VR Client Port "
            "in the VR Configuration GUI; the viewer passes it to the client."
        )
    server_socket.listen(1)

    print(f"\nServer listening on {host}:{port}. Waiting for the VR client to connect...")

    # Serve the VR client from a background thread (passes both render edges and unfiltered edges)
    t = threading.Thread(target=unity_server_loop, args=(server_socket, viewer, pos, edges_to_send, n_nodes, n_edges_to_send, edges), daemon=True)
    t.start()

    # Auto-launch the installed VR client (falls back gracefully if not found).
    # Kept on the viewer: the server thread replaces it if the client restarts.
    viewer.vr_endpoint = (host, port)
    viewer.vr_proc = launch_vr_app(host, port)

    try:
        while viewer.running:
            # The terminal is deliberately not gated on the VR client: analysis
            # commands operate on viewer state, and the client resynchronises
            # from that state whenever it connects.
                
            try:
                terminal_loop(viewer)
            except KeyboardInterrupt:
                raise
    except KeyboardInterrupt:
        print("Server shutting down.")
    finally:
        # Queued label/logo jobs are dropped, as the desktop drops them at exit.
        viewer.background_job_scheduler.shutdown()
        # Terminate the VR app if we launched it
        vr_proc = getattr(viewer, "vr_proc", None)
        if vr_proc is not None:
            try:
                vr_proc.terminate()
                vr_proc.wait(timeout=5)
                print("VR client terminated.")
            except Exception:
                try:
                    vr_proc.kill()
                except Exception:
                    pass
        server_socket.close()

if __name__ == "__main__":
    # The server exists to drive the Windows VR client in player/, so it
    # refuses to start elsewhere rather than binding a socket nothing can
    # ever connect to.
    _bootstrap_vr.require_windows("The EMAP-SSN VR Viewer")
    # Claimed before the cache is loaded: finding out that another viewer owns
    # the headset after a minute of reading HDF5 helps nobody. The handle is
    # held in a module global so the mutex lives as long as the process.
    _INSTANCE_HANDLE = Single_Instance_VR.acquire()
    if _INSTANCE_HANDLE is None:
        sys.exit(Single_Instance_VR.BUSY_MESSAGE)
    print("--- VR SSN Viewer Backend ---")
    start_server()
