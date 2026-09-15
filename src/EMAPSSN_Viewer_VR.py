import socket
import struct
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
import Alignment_Manager
from desktop.Viewer_State import resolve_selected_cache



class DummyText:
    def __init__(self):
        self.text = ""

class HeadlessViewer:
    def __init__(self, n_nodes, headers, full_headers, metadata=None):
        self.n_nodes = n_nodes
        self.headers = headers
        self.full_headers = full_headers
        
        # State Arrays
        neighbor_hex = getattr(cfg, 'NEIGHBOR_COLOR', '#4488ff')
        def parse_hex_color(hex_str):
            h = hex_str.lstrip('#')
            if len(h) == 6:
                return [int(h[0:2], 16)/255.0, int(h[2:4], 16)/255.0, int(h[4:6], 16)/255.0, 1.0]
            elif len(h) == 8:
                return [int(h[0:2], 16)/255.0, int(h[2:4], 16)/255.0, int(h[4:6], 16)/255.0, int(h[6:8], 16)/255.0]
            return [0.8, 0.8, 0.8, 1.0]
        default_color = parse_hex_color(neighbor_hex)
        self.current_colors = np.full((n_nodes, 4), default_color, dtype=np.float32)
        self.current_sizes = np.full(n_nodes, cfg.NODE_SIZE, dtype=np.float32)
        self.current_shapes = np.full(n_nodes, 'disc', dtype=object)
        self.visible_mask = np.ones(n_nodes, dtype=bool)
        
        # The terminal runs until the user exits, not until Unity drops.
        self.running = True
        self.cluster_labels = None
        self.group_labels = [set() for _ in range(n_nodes)]
        
        # Initialize metadata
        self.metadata = metadata if metadata is not None else {}
        
        # Initialize Length metadata if not already loaded from cache
        if "Length" not in self.metadata:
            lengths_map = {}
            fasta_path = getattr(cfg, 'NODE_FASTA_FILE', None) or getattr(cfg, 'SEQUENCES_FILE', '')
            if fasta_path and fasta_path.startswith('..'):
                # Relative settings resolve against the submodule root, not
                # against this module's directory inside src/.
                fasta_path = os.path.normpath(
                    os.path.join(_bootstrap_vr.OPT_VR_DIR, fasta_path)
                )
                
            if fasta_path and os.path.exists(fasta_path):
                try:
                    from Bio import SeqIO
                    for rec in SeqIO.parse(fasta_path, "fasta"):
                        lengths_map[rec.id] = len(rec.seq)
                        lengths_map[rec.description] = len(rec.seq)
                except Exception as e:
                    print(f"Warning: Failed to parse FASTA for sequence lengths: {e}")
            
            length_values = np.zeros(self.n_nodes, dtype=np.int32)
            for i, h in enumerate(self.full_headers):
                rec_id = h.split()[0]
                if h in lengths_map:
                    length_values[i] = lengths_map[h]
                elif rec_id in lengths_map:
                    length_values[i] = lengths_map[rec_id]
            
            self.metadata["Length"] = {
                "type": "number",
                "values": length_values
            }
            
        # Reorder metadata dictionary so "Length" is the first property
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
            cache_path, _ = utils.get_cache_filename()
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
        self.edges = None  # Full edge list retained for commands
        
        self.transform_position = [0.0, 0.0, 0.0]
        self.transform_rotation = [0.0, 0.0, 0.0, 1.0]
        self.transform_scale = [1.0, 1.0, 1.0]
        self.distance_scale = 1.0
        self.is_connected = False
        
        # Load Alignment
        self.active_reference = getattr(cfg, 'ALIGNMENT_REFERENCE', None)
        try:
            self.alignment = Alignment_Manager.Alignment_Manager(
                cfg.MSA_FILE, 
                full_headers=self.full_headers, 
                active_reference=self.active_reference
            )
            print("Alignment Manager successfully loaded.")
        except Exception as e:
            print(f"Warning: Failed to load Alignment Manager: {e}")
            self.alignment = None
        
    def _save_state(self):
        snapshot = {
            "colors": self.current_colors.copy(),
            "sizes": self.current_sizes.copy(),
            "shapes": self.current_shapes.copy(),
            "visible": self.visible_mask.copy(),
            "cluster_labels": self.cluster_labels.copy() if self.cluster_labels is not None else None,
            "group_labels": [s.copy() for s in self.group_labels]
        }
        self.undo_stack.append(snapshot)
        if len(self.undo_stack) > self.max_history:
            self.undo_stack.pop(0)
        self.redo_stack.clear()
        
    def _do_undo(self):
        if not self.undo_stack:
            print("Nothing to undo.")
            self.console_text.text = "Nothing to undo."
            return
            
        snapshot = self.undo_stack.pop()
        current_state = {
            "colors": self.current_colors.copy(),
            "sizes": self.current_sizes.copy(),
            "shapes": self.current_shapes.copy(),
            "visible": self.visible_mask.copy(),
            "cluster_labels": self.cluster_labels.copy() if self.cluster_labels is not None else None,
            "group_labels": [s.copy() for s in self.group_labels]
        }
        self.redo_stack.append(current_state)
        
        self.current_colors = snapshot["colors"]
        self.current_sizes = snapshot["sizes"]
        self.current_shapes = snapshot["shapes"]
        self.visible_mask = snapshot["visible"]
        self.cluster_labels = snapshot["cluster_labels"]
        self.group_labels = snapshot["group_labels"]
        
        self.update_nodes()
        self.update_edges()
        
        print("Undo successful.")
        self.console_text.text = "Undo successful."
        
    def _do_redo(self):
        if not self.redo_stack:
            print("Nothing to redo.")
            self.console_text.text = "Nothing to redo."
            return
            
        snapshot = self.redo_stack.pop()
        current_state = {
            "colors": self.current_colors.copy(),
            "sizes": self.current_sizes.copy(),
            "shapes": self.current_shapes.copy(),
            "visible": self.visible_mask.copy(),
            "cluster_labels": self.cluster_labels.copy() if self.cluster_labels is not None else None,
            "group_labels": [s.copy() for s in self.group_labels]
        }
        self.undo_stack.append(current_state)
        
        self.current_colors = snapshot["colors"]
        self.current_sizes = snapshot["sizes"]
        self.current_shapes = snapshot["shapes"]
        self.visible_mask = snapshot["visible"]
        self.cluster_labels = snapshot["cluster_labels"]
        self.group_labels = snapshot["group_labels"]
        
        self.update_nodes()
        self.update_edges()
        
        print("Redo successful.")
        self.console_text.text = "Redo successful."

    def load_global_alignment(self):
        try:
            self.alignment = Alignment_Manager.Alignment_Manager(
                cfg.MSA_FILE, 
                full_headers=self.full_headers, 
                active_reference=self.active_reference
            )
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

    def update_nodes(self):
        # Package state into JSON, flattened for Unity JsonUtility
        packet = {
            "colors": self.current_colors.flatten().tolist(),
            "sizes": self.current_sizes.tolist(),
            "visible": self.visible_mask.tolist(),
            "globalSettings": self.get_global_settings(),
            "transformState": self.get_transform_state()
        }
        self.update_queue.put(packet)
        
    def update_edges(self):
        pass # Handled implicitly by unity when nodes update

    def update_selection_visual(self):
        pass # Selection highlighting is handled locally or not supported in Unity
        
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
            return
        except Exception as error:
            print(f"Error loading command '{command_name}': {error}")
            traceback.print_exc()
            return

        if not hasattr(module, "run"):
            print(f"Error: no run() entry point in commands/{command_name}.py")
            return

        try:
            module.run(self, args)
        except Exception as error:
            print(f"Command Error: {error}")
            traceback.print_exc()

def _as_three_dimensional(positions):
    """Unity expects three floats per node; lift a 2D cache onto z = 0."""
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


def _edges_for(cache_headers):
    """Rebuild the edge list from the source network.

    The layout generator deliberately does not cache edges, so they are
    derived here with the shared prepare_network. Using the upstream function
    rather than a local copy is what keeps VR edge filtering identical to the
    desktop viewer's.
    """
    empty = (np.zeros((0, 2), dtype=np.int32), np.zeros(0, dtype=np.float32))
    network_path = getattr(cfg, "INPUT_HDF5", None)
    if not network_path or not os.path.exists(network_path):
        print(
            f"Warning: source network {network_path!r} is unavailable; "
            "showing nodes without edges."
        )
        return empty

    try:
        from desktop.Viewer_State import prepare_network

        with h5py.File(network_path, "r") as data:
            network_headers, raw_edges, raw_scores = prepare_network(
                data, settings=cfg
            )
    except Exception as error:
        print(f"Warning: could not rebuild edges from {network_path}: {error}")
        return empty

    index_of = {header: index for index, header in enumerate(cache_headers)}
    mapped = []
    scores = []
    for position, (source, target) in enumerate(raw_edges):
        first = index_of.get(network_headers[source])
        second = index_of.get(network_headers[target])
        if first is not None and second is not None:
            mapped.append((first, second))
            scores.append(raw_scores[position])

    if not mapped:
        return empty
    return (
        np.asarray(mapped, dtype=np.int32),
        np.asarray(scores, dtype=np.float32),
    )


def _newest_cache_in(folder):
    """Latest .h5 in a cache folder, or None.

    The folder name is escaped before globbing: cache folders carry the model
    tag in square brackets (..._[E1_RA]_...), which glob reads as a character
    class and would never match.
    """
    if not folder or not os.path.isdir(folder):
        return None
    candidates = sorted(glob.glob(os.path.join(glob.escape(folder), "*.h5")))
    return candidates[-1] if candidates else None


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
        selected, _reference = resolve_selected_cache(cfg)
    except Exception as error:
        sys.exit(
            f"Could not work out which layout cache these settings describe: {error}\n\n"
            "opt_vr consumes a cache produced by the main EMAP-SSN program; it "
            "does not generate one. Build one with:\n"
            "    python src/Layout_Cache_Generator.py <layout_settings.json>\n"
            "or set TARGET_CACHE_PATH in viewer_settings.json - or the "
            "SSN_TARGET_CACHE environment variable - to choose one explicitly."
        )

    folders = [os.path.dirname(selected)]
    if int(getattr(cfg, "LAYOUT_DIMENSIONS", 2) or 2) == 3:
        # resolve_selected_cache does not forward LAYOUT_DIMENSIONS to
        # build_canonical_cache_name, so it always names the 2D folder. The
        # generator appends "_3D", so try that sibling first.
        folders.insert(0, folders[0] + "_3D")

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
        + "\n\nopt_vr consumes a cache produced by the main EMAP-SSN program; "
        "it does not generate one. Build one with:\n"
        "    python src/Layout_Cache_Generator.py <layout_settings.json>\n"
        "or point TARGET_CACHE_PATH (or SSN_TARGET_CACHE) at an existing "
        "folder." + listing
    )


def load_layout_cache():
    """Load a layout cache published by the main EMAP-SSN program.

    Coordinates, node order and node metadata all come from the cache; nothing
    here computes a layout. Everything scientific - sanitization, embeddings,
    alignment, network construction, layout generation - is the main program's
    responsibility, and opt_vr is strictly a consumer of its output.
    """
    cache_path = _resolve_cache_path()
    print(f"Loading layout cache: {cache_path}")

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
                if name == "Length":
                    values = raw_values.astype(np.int32)
                elif prop_type == "number":
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

    edges, edge_scores = _edges_for(headers)
    print(
        f"Loaded {n_nodes} nodes and {len(edges)} edges "
        f"from a {dimensions}D cache."
    )
    return positions, edges, edge_scores, n_nodes, headers, list(headers), metadata


def _simple_terminal_loop(viewer):
    """Line-based fallback for hosts without msvcrt (Linux, macOS).

    No arrow-key history, but the viewer stays usable. input() blocks, so a
    Unity disconnect is noticed on the next command rather than immediately.
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
        print("    (Unity is not connected yet; commands still work and "
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
            sys.stdout.write("> ")
            sys.stdout.flush()
            
            cmd_chars = []
            if hasattr(viewer, 'command_history'):
                viewer.history_index = len(viewer.command_history)
                
            while viewer.running:
                if msvcrt.kbhit():
                    ch = msvcrt.getwch()
                    
                    # Enter key
                    if ch in ('\r', '\n'):
                        sys.stdout.write('\n')
                        sys.stdout.flush()
                        break
                    # Backspace
                    elif ch == '\x08':
                        if cmd_chars:
                            cmd_chars.pop()
                            sys.stdout.write('\b \b')
                            sys.stdout.flush()
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
                                # Erase current line
                                sys.stdout.write('\b \b' * len(cmd_chars))
                                cmd_chars = list(new_cmd)
                                sys.stdout.write(new_cmd)
                                sys.stdout.flush()
                        elif scan_code == 'P':  # Down Arrow
                            if hasattr(viewer, 'command_history') and viewer.command_history:
                                viewer.history_index = min(len(viewer.command_history), viewer.history_index + 1)
                                if viewer.history_index == len(viewer.command_history):
                                    new_cmd = ""
                                else:
                                    new_cmd = viewer.command_history[viewer.history_index]
                                # Erase current line
                                sys.stdout.write('\b \b' * len(cmd_chars))
                                cmd_chars = list(new_cmd)
                                sys.stdout.write(new_cmd)
                                sys.stdout.flush()
                    # Normal characters
                    else:
                        cmd_chars.append(ch)
                        sys.stdout.write(ch)
                        sys.stdout.flush()
                else:
                    time.sleep(0.01)
                    
            if not viewer.running:
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
                print(f"\n[Warning] Failed to parse Unity client JSON: {ex}")
                print(f"Raw line: {repr(line)}")
    except Exception as e:
        print(f"[Warning] Client reader loop encountered exception: {e}")
    finally:
        viewer.is_connected = False

def unity_server_loop(server_socket, viewer, pos, edges_to_send, n_nodes, n_edges_to_send, unfiltered_edges):
    try:
        while True:
            client, addr = server_socket.accept()
            print(f"\nUnity connected from {addr}")
            
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
                
                print(f"Successfully sent initial binary layout. Establishing persistent JSON connection...")
                
                # Send initial state (colors, sizes, visible, settings, transform)
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
                print(f"\nUnity client {addr} disconnected. Waiting for a new connection...")
    except Exception as e:
        print(f"Server loop shutting down: {e}")

#: Unity ships these alongside the player; neither is the application.
_NOT_THE_PLAYER = ("unitycrashhandler",)


def vr_app_search_dirs():
    """Directories that may hold the built Unity player, most specific first."""
    # VR_App sits at the submodule root beside src/, the way the main
    # program keeps its own resource directories out of the module tree.
    script_dir = _bootstrap_vr.OPT_VR_DIR
    configured = getattr(cfg, "VR_APP_DIR", "VR_App")
    return [
        # The setting wins, resolved against opt_vr when it is relative.
        configured if os.path.isabs(configured)
        else os.path.join(script_dir, configured),
        # The build lives inside opt_vr, not beside it. Looking one level up
        # only worked back when the viewer sat in a subdirectory of the old
        # standalone repository.
        os.path.join(script_dir, "VR_App"),
        os.path.join(os.getcwd(), "VR_App"),
    ]


def find_vr_app():
    """Return the built VR player executable, or None if there is no build."""
    for search_dir in vr_app_search_dirs():
        search_dir = os.path.normpath(search_dir)
        if not os.path.isdir(search_dir):
            continue
        candidates = sorted(
            path
            for path in glob.glob(os.path.join(glob.escape(search_dir), "*.exe"))
            # A Unity build directory also contains the crash handler, so the
            # first .exe found is not necessarily the player.
            if not os.path.basename(path).lower().startswith(_NOT_THE_PLAYER)
        )
        if candidates:
            return os.path.abspath(candidates[0])

    return None

def launch_vr_app():
    """Attempt to launch the built VR application.
    Returns the subprocess.Popen object if launched, or None if not found.
    """
    exe_path = find_vr_app()
    if exe_path is None:
        print("VR application not found. Falling back to manual Unity Editor mode.")
        print("  To build: Unity Editor > File > Build Settings > Build")
        print("  Searched:")
        for search_dir in vr_app_search_dirs():
            print(f"    {os.path.normpath(search_dir)}")
        return None
    
    print(f"Launching VR application: {exe_path}")
    try:
        proc = subprocess.Popen(
            [exe_path],
            cwd=os.path.dirname(exe_path),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        print(f"VR application launched (PID {proc.pid}). Waiting for it to connect...")
        return proc
    except Exception as e:
        print(f"Failed to launch VR application: {e}")
        print("Falling back to manual Unity Editor mode.")
        return None

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
    # The endpoint is a setting, but the Unity build has 127.0.0.1:5005
    # baked into its scene, so changing it also means rebuilding the client.
    host = host or getattr(cfg, 'VR_HOST', '127.0.0.1')
    port = int(port or getattr(cfg, 'VR_PORT', 5005))
    pos, edges, edge_scores, n_nodes, headers, full_headers, metadata = load_layout_cache()
    
    viewer = HeadlessViewer(n_nodes, headers, full_headers, metadata)
    viewer.edges = edges  # Retain full edge list for viewing purposes/commands
    viewer.edge_scores = edge_scores
    # Commands such as `save` read viewer.pos; without these two lines the
    # positions existed only as a local and every `save` raised
    # AttributeError.
    viewer.pos = pos
    viewer.original_pos = pos.copy()
    
    # --- Intelligent Edge Downsampling for Unity Rendering ---
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
            print(f"Edge downsampling is disabled. Passing all {len(edges)} edges to Unity frontend.")
        edges_to_send = edges

    n_edges_to_send = len(edges_to_send)
    
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_socket.bind((host, port))
    server_socket.listen(1)
    
    print(f"\nServer listening on {host}:{port}. Waiting for Unity to connect...")
    
    # Start the Unity server listener in a background thread (passes both render edges and unfiltered edges)
    t = threading.Thread(target=unity_server_loop, args=(server_socket, viewer, pos, edges_to_send, n_nodes, n_edges_to_send, edges), daemon=True)
    t.start()
    
    # Auto-launch the built VR application (falls back gracefully if not found)
    vr_proc = launch_vr_app()
    
    try:
        while True:
            # The terminal is deliberately not gated on Unity: analysis
            # commands operate on viewer state, and Unity resynchronises
            # from that state whenever it connects.
                
            try:
                terminal_loop(viewer)
            except KeyboardInterrupt:
                raise
    except KeyboardInterrupt:
        print("Server shutting down.")
    finally:
        # Terminate the VR app if we launched it
        if vr_proc is not None:
            try:
                vr_proc.terminate()
                vr_proc.wait(timeout=5)
                print("VR application terminated.")
            except Exception:
                try:
                    vr_proc.kill()
                except Exception:
                    pass
        server_socket.close()

if __name__ == "__main__":
    # The server exists to drive the Windows Unity player in VR_App, so it
    # refuses to start elsewhere rather than binding a socket nothing can
    # ever connect to.
    _bootstrap_vr.require_windows("The EMAP-SSN VR Viewer")
    print("--- VR SSN Viewer Backend ---")
    start_server()
