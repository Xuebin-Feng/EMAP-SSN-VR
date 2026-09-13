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
import queue
import subprocess
import glob

# Ensure Python can import from the VR_Viewer directory regardless of where it is run
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import SSN_VR_Config as cfg
import SSN_VR_Utils as utils
import Layout_Engine_VR_SSN_MolecularDynamics as Layout_Engine
import Alignment_Manager_VR_SSN as Alignment_Manager



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
        
        self.cluster_labels = None
        self.group_labels = [set() for _ in range(n_nodes)]
        
        # Initialize metadata
        self.metadata = metadata if metadata is not None else {}
        
        # Initialize Length metadata if not already loaded from cache
        if "Length" not in self.metadata:
            lengths_map = {}
            fasta_path = getattr(cfg, 'NODE_FASTA_FILE', None) or getattr(cfg, 'SEQUENCES_FILE', '')
            if fasta_path and fasta_path.startswith('..'):
                script_dir = os.path.dirname(os.path.abspath(__file__))
                fasta_path = os.path.normpath(os.path.join(script_dir, fasta_path))
                
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
        
        try:
            module = importlib.import_module(f"VR_commands.VR_{command_name}")
            importlib.reload(module)
            if hasattr(module, 'run'):
                module.run(self, args)
            else:
                print(f"Error: No 'run' in VR_{command_name}")
        except ModuleNotFoundError:
            print(f"Unknown command: {command_name}")
        except Exception as e:
            print(f"Command Error: {e}")

def load_or_calculate_layout():
    if not os.path.exists(cfg.SAVED_LAYOUT_DIR):
        os.makedirs(cfg.SAVED_LAYOUT_DIR)
        
    cache_path, resolved_ref = utils.get_cache_filename()
    print(f"Target Cache File: {cache_path}")
    
    headers = []
    full_headers = []
    metadata = {}
    
    if os.path.exists(cache_path):
        print(f"--- Found Cached VR Layout! ---")
        try:
            with h5py.File(cache_path, "r") as hf:
                pos = hf["positions"][:].astype(np.float32)
                raw_headers = hf["headers"][:]
                headers = [h.decode('utf-8') if isinstance(h, bytes) else h for h in raw_headers]
                full_headers = headers
                n_nodes = len(pos)
                
                # --- Load Metadata from Cache ---
                if "metadata" in hf:
                    meta_group = hf["metadata"]
                    for prop_name in meta_group.keys():
                        ds = meta_group[prop_name]
                        prop_type = ds.attrs.get("type", "text")
                        raw_vals = ds[:]
                        if prop_name == "Length":
                            values = raw_vals.astype(np.int32)
                        elif prop_type == "number":
                            values = raw_vals.astype(np.float64)
                        else:
                            values = np.array([v.decode('utf-8') if isinstance(v, bytes) else str(v) for v in raw_vals], dtype=object)
                        metadata[prop_name] = {
                            "type": prop_type,
                            "values": values
                        }
                
            print("Fetching fresh connectivity and edge scores from raw network file...")
            try:
                with h5py.File(cfg.INPUT_HDF5, "r") as raw_data:
                    raw_headers, raw_edges, raw_edge_scores, _, _ = utils.build_network_from_raw(
                        raw_data, forced_ref_header=resolved_ref
                    )
                
                # Robustly map raw_edges to the cached headers
                raw_to_idx = {h: idx for idx, h in enumerate(raw_headers)}
                cached_to_idx = {h: idx for idx, h in enumerate(full_headers)}
                
                mapped_edges = []
                mapped_scores = []
                for edge_idx, (u, v) in enumerate(raw_edges):
                    u_header = raw_headers[u]
                    v_header = raw_headers[v]
                    u_cached = cached_to_idx.get(u_header)
                    v_cached = cached_to_idx.get(v_header)
                    if u_cached is not None and v_cached is not None:
                        mapped_edges.append([u_cached, v_cached])
                        mapped_scores.append(raw_edge_scores[edge_idx])
                
                edges = np.array(mapped_edges, dtype=np.int32) if mapped_edges else np.zeros((0, 2), dtype=np.int32)
                edge_scores = np.array(mapped_scores, dtype=np.float32) if mapped_scores else np.zeros(0, dtype=np.float32)
            except Exception as e:
                print(f"Warning: Failed to load raw connectivity/scores from network file: {e}")
                # Fallback: if connectivity was in older cache file, load it
                with h5py.File(cache_path, "r") as hf:
                    if "connectivity" in hf:
                        edges_raw = hf["connectivity"][:]
                        edges = edges_raw.astype(np.int32) if len(edges_raw) > 0 else np.zeros((0, 2), dtype=np.int32)
                    else:
                        edges = np.zeros((0, 2), dtype=np.int32)
                    
                    if "edge_scores" in hf:
                        edge_scores = hf["edge_scores"][:]
                    else:
                        edge_scores = np.zeros(0, dtype=np.float32)
                
            print(f"Loaded {n_nodes} nodes and {len(edges)} edges.")
            return pos, edges, edge_scores, n_nodes, headers, full_headers, metadata
        except Exception as e:
            print(f"Error loading cache: {e}. Recalculating...")
            
    print(f"--- Calculating New VR Layout ---")
    try:
        with h5py.File(cfg.INPUT_HDF5, "r") as raw_data: 
            headers, edges, edge_scores, initial_pos, box_limit = utils.build_network_from_raw(
                raw_data, forced_ref_header=resolved_ref
            )
            # Fetch full headers if they exist
            if "full_headers" in raw_data:
                full_headers = [h.decode('utf-8') for h in raw_data["full_headers"][:]]
            else:
                full_headers = headers
    except Exception as e:
        sys.exit(f"Error loading HDF5 file: {e}")
        
    n_nodes = len(headers)
    print(f"Network Built: {n_nodes} Nodes, {len(edges)} Edges.")
    
    params = {
        'BOX_SCALE': getattr(cfg, 'BOX_SCALE', 1.0),
        'SIMILARITY_THRESHOLD': getattr(cfg, 'SIMILARITY_THRESHOLD', 0.0),
        'ENABLE_PROGRESSIVE_SIMULATION': getattr(cfg, 'ENABLE_PROGRESSIVE_SIMULATION', True),
        'RMSD_WINDOW': getattr(cfg, 'RMSD_WINDOW', 50),
        'MAX_STEPS': getattr(cfg, 'MAX_STEPS', 2000),
        'RMSD_THRESHOLD': getattr(cfg, 'RMSD_THRESHOLD', 0.005),
        'PERCENTAGE_DROP_THRESHOLD': getattr(cfg, 'PERCENTAGE_DROP_THRESHOLD', 0.0),
        'PACKING_GRID_SIZE': getattr(cfg, 'PACKING_GRID_SIZE', 200.0),
        'PACKING_PADDING': getattr(cfg, 'PACKING_PADDING', 50.0),
        'COULOMB_CUTOFF': getattr(cfg, 'COULOMB_CUTOFF', 15.0),
        'COULOMB_K': getattr(cfg, 'COULOMB_K', 50.0),
        'MAX_FORCE_LIMIT': getattr(cfg, 'MAX_FORCE_LIMIT', 10.0),
        'SPRING_K': getattr(cfg, 'SPRING_K', 0.1),
        'DAMPING': getattr(cfg, 'DAMPING', 0.5),
        'DT': getattr(cfg, 'DT', 0.1),
        # Monte Carlo/SGLD parameters
        'SGLD_MIN_K': getattr(cfg, 'SGLD_MIN_K', 20),
        'SGLD_K_PERCENT': getattr(cfg, 'SGLD_K_PERCENT', 0.01),
        'SGLD_START_TEMP': getattr(cfg, 'SGLD_START_TEMP', 1.5),
        'SGLD_NOISE_SCALE': getattr(cfg, 'SGLD_NOISE_SCALE', 1.0)
    }
    
    if len(edges) > 0:
        connectivity = np.column_stack((edges, edge_scores))
    else:
        connectivity = np.zeros((0, 3), dtype=np.float32)
        
    engine_style = getattr(cfg, 'PHYSICS_ENGINE', 'Molecular Dynamics (Style)')
    if engine_style == 'Monte Carlo (Style)':
        import Layout_Engine_VR_SSN_MonteCarlo as Layout_Engine
        print("Using VR Monte Carlo (SGLD) Layout Engine...")
    else:
        import Layout_Engine_VR_SSN_MolecularDynamics as Layout_Engine
        print("Using VR Molecular Dynamics Layout Engine...")

    pos, box_limit = Layout_Engine.calculate_layout(connectivity, n_nodes, params)
    
    # --- Centering ---
    # Shift the entire network so its center of mass sits exactly at (0,0,0).
    pos -= np.mean(pos, axis=0)
    
    try:
        os.makedirs(os.path.dirname(cache_path), exist_ok=True)
        with h5py.File(cache_path, "w") as hf:
            dt_str = h5py.string_dtype(encoding='utf-8')
            hf.create_dataset("headers", data=np.array(headers, dtype=object), dtype=dt_str, compression="gzip")
            hf.create_dataset("positions", data=pos, compression="gzip")
        print(f"VR Layout saved to: {cache_path}")
    except Exception as e:
        print(f"Warning: Could not save layout cache: {e}")
        
    return pos, edges, edge_scores, n_nodes, headers, full_headers, metadata

def terminal_loop(viewer):
    print("--- Terminal Ready. Type 'help' for a list of commands ---")
    
    # We use msvcrt for low-level keyboard polling to completely bypass the 
    # buggy line-editor/echo behavior in the IDE or hooked Windows console.
    import msvcrt
    
    while viewer.is_connected:
        try:
            sys.stdout.write("> ")
            sys.stdout.flush()
            
            cmd_chars = []
            if hasattr(viewer, 'command_history'):
                viewer.history_index = len(viewer.command_history)
                
            while viewer.is_connected:
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
                    
            if not viewer.is_connected:
                print("\nUnity disconnected. Closing command line.")
                break
                
            cmd = "".join(cmd_chars).strip()
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

def find_vr_app():
    """Search for the built VR application executable.
    Searches in order:
      1. ../VR_App/ relative to this script
      2. ./VR_App/ relative to the current working directory
      3. Any .exe in ../VR_App/ matching *SSN*VR* or *My?project*
    Returns the absolute path to the .exe, or None if not found.
    """
    script_dir = os.path.dirname(os.path.abspath(__file__))
    search_dirs = [
        os.path.join(script_dir, '..', 'VR_App'),
        os.path.join(os.getcwd(), 'VR_App'),
    ]
    
    for search_dir in search_dirs:
        search_dir = os.path.normpath(search_dir)
        if not os.path.isdir(search_dir):
            continue
        # Look for any .exe in the directory (Unity builds produce exactly one)
        exe_files = glob.glob(os.path.join(search_dir, '*.exe'))
        if exe_files:
            # Return the first .exe found
            return os.path.abspath(exe_files[0])
    
    return None

def launch_vr_app():
    """Attempt to launch the built VR application.
    Returns the subprocess.Popen object if launched, or None if not found.
    """
    exe_path = find_vr_app()
    if exe_path is None:
        print("VR application not found. Falling back to manual Unity Editor mode.")
        print("  To build: Unity Editor > File > Build Settings > Build")
        print(f"  Expected location: ../VR_App/*.exe (relative to this script)")
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

def start_server(host='127.0.0.1', port=5005):
    pos, edges, edge_scores, n_nodes, headers, full_headers, metadata = load_or_calculate_layout()
    
    viewer = HeadlessViewer(n_nodes, headers, full_headers, metadata)
    viewer.edges = edges  # Retain full edge list for viewing purposes/commands
    viewer.edge_scores = edge_scores
    
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
            # Wait for Unity to connect before starting the terminal loop
            if not viewer.is_connected:
                print("Waiting for Unity to connect...")
                while not viewer.is_connected:
                    time.sleep(0.1)
                print("Unity connected. Starting command line...")
                
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
    print("--- VR SSN Viewer Backend ---")
    start_server()
