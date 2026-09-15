import importlib.util
import numpy as np
import fnmatch
import re
import os
import sys

import _bootstrap_vr
import Settings_VR as cfg


def _upstream_engine():
    """Load the main program's Command_Engine under a private alias.

    ``import Command_Engine`` resolves to *this* module - opt_vr precedes src on
    sys.path, which is what makes the override work at all - so the upstream
    copy has to be loaded by path to be reachable from here.
    """
    alias = "_upstream_Command_Engine"
    module = sys.modules.get(alias)
    if module is None:
        path = os.path.join(_bootstrap_vr.SRC_DIR, "Command_Engine.py")
        spec = importlib.util.spec_from_file_location(alias, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[alias] = module
        spec.loader.exec_module(module)
    return module


# The Boolean selection grammar belongs to the main program. Classification is
# pure - upstream documents it as consulting "neither viewer data nor the
# filesystem" - so these names are adopted rather than forked. Re-implementing
# them here would mean copying a recursive-descent parser and twenty-odd helper
# predicates that would start drifting the day upstream touched them, which is
# exactly how the previous fork rotted.
_upstream = _upstream_engine()

SelectionExpressionError = _upstream.SelectionExpressionError
SelectionContextError = _upstream.SelectionContextError
SelectionClassification = _upstream.SelectionClassification
SelectionClassificationKind = _upstream.SelectionClassificationKind
classify_selection_expression = _upstream.classify_selection_expression
parse_selection_expression = _upstream.parse_selection_expression


def evaluate_string_mask(full_headers, target):
    """Evaluates a raw string, NCBI ID, or wildcard pattern into a boolean mask."""
    mask = np.zeros(len(full_headers), dtype=bool)
    t_lower = target.lower()
    
    # 0. NCBI Mode: e.g. E1_RA
    ncbi_pattern = re.compile(r'\b([A-Z]{2}_\d+(?:\.\d+)?|[A-Z]{3}\d{5,7}(?:\.\d+)?)\b', re.IGNORECASE)
    is_ncbi_format = bool(ncbi_pattern.search(target))
    
    for i, full_header in enumerate(full_headers):
        fh_lower = full_header.lower()
        sh_lower = full_header.split()[0].lower() if full_header else ""
        
        # 1. Standard sub-string matching
        if t_lower in fh_lower or t_lower in sh_lower:
            mask[i] = True
            
        # 2. Comprehensive wildcard evaluation (*, ?, [seq])
        elif fnmatch.fnmatch(fh_lower, t_lower) or fnmatch.fnmatch(sh_lower, t_lower):
            mask[i] = True
            
    return mask

def evaluate_file_mask(full_headers, target):
    """Evaluates an external header file, FASTA file, or NCBI/PDB list into a boolean mask."""
    mask = np.zeros(len(full_headers), dtype=bool)
    exact_matches = set()
    target_ncbi_ids = set()
    target_pdb_ids = set()
    is_ncbi_mode = False
    is_pdb_mode = False
    
    file_name = target.strip()
    if file_name.lower().startswith('[ncbi]'):
        is_ncbi_mode = True
        file_name = file_name[6:]
    elif file_name.lower().startswith('[pdb]'):
        is_pdb_mode = True
        file_name = file_name[5:]
        
    header_dir = getattr(cfg, 'HEADER_LIST_DIR', os.path.join("Input_Files", "Header_Lists"))
    
    # 1. Path Resolution (.fasta, .txt, or default to .txt)
    if file_name.lower().endswith('.fasta') or file_name.lower().endswith('.txt'):
        load_path = os.path.join(header_dir, file_name)
    else:
        load_path = os.path.join(header_dir, file_name + ".txt")
        
    if not os.path.isfile(load_path):
        print(f"Warning: Could not find file '{os.path.basename(load_path)}' in {header_dir}")
        return mask
        
    # Standard NCBI format regex (RefSeq or GenBank)
    ncbi_pattern = re.compile(r'\b([A-Z]{2}_\d+(?:\.\d+)?|[A-Z]{3}\d{5,7}(?:\.\d+)?)\b', re.IGNORECASE)
    # Standard PDB regex: 1 digit (1-9) + 3 alphanumeric. Accounts for optional chain appendages (e.g., 1XYZ_A)
    pdb_pattern = re.compile(r'\b([1-9][A-Z0-9]{3})(?:_[A-Z0-9]+)?\b', re.IGNORECASE)
    
    # 2. Parse the Input File
    is_fasta = load_path.lower().endswith('.fasta')
    with open(load_path, 'r', encoding='utf-8', errors='ignore') as f:
        for line in f:
            line = line.strip()
            if not line: continue
            
            # If FASTA, only read header lines and strip the '>'
            if is_fasta:
                if not line.startswith('>'): continue
                raw_str = line[1:] 
            else:
                raw_str = line
                
            if is_ncbi_mode:
                match = ncbi_pattern.search(raw_str)
                if match:
                    target_ncbi_ids.add(match.group(1).lower())
            elif is_pdb_mode:
                match = pdb_pattern.search(raw_str)
                if match:
                    target_pdb_ids.add(match.group(1).lower())
            else:
                exact_matches.add(raw_str.lower())
    
    # 3. Evaluate Against Network Headers
    for i, full_header in enumerate(full_headers):
        fh_lower = full_header.lower()
        sh_lower = full_header.split()[0].lower() if full_header else ""
        
        if is_ncbi_mode:
            # Extract NCBI ID from the network header and check against the set
            match = ncbi_pattern.search(full_header)
            if match and match.group(1).lower() in target_ncbi_ids:
                mask[i] = True
            else:
                # Fallback check against the simplified header just in case
                match_sh = ncbi_pattern.search(sh_lower)
                if match_sh and match_sh.group(1).lower() in target_ncbi_ids:
                    mask[i] = True
                    
        elif is_pdb_mode:
            # Extract all PDB-like IDs from the header and see if any match our targets
            matches = pdb_pattern.findall(full_header)
            if any(m.lower() in target_pdb_ids for m in matches):
                mask[i] = True
            else:
                # Fallback check against simplified header
                matches_sh = pdb_pattern.findall(sh_lower)
                if any(m.lower() in target_pdb_ids for m in matches_sh):
                    mask[i] = True
                    
        else:
            # Standard Exact/String Matching
            if fh_lower in exact_matches or sh_lower in exact_matches:
                mask[i] = True
                
    return mask

def evaluate_label_mask(full_headers, cluster_labels, group_labels, target):
    """Evaluates a #Cluster_N#, #Noise#, or #Custom_Group# into a boolean mask."""
    mask = np.zeros(len(full_headers), dtype=bool)
    t_lower = target.strip().lower()

    if t_lower == "noise":
        if cluster_labels is not None:
            mask = (cluster_labels == -1)
        return mask

    cluster_match = re.match(r'^cluster_(\d+)$', t_lower)
    if cluster_match:
        c_id = int(cluster_match.group(1))
        if cluster_labels is not None:
            mask = (cluster_labels == c_id)
        return mask

    if group_labels is not None:
        for i in range(len(full_headers)):
            if t_lower in group_labels[i]:
                mask[i] = True
                
    return mask

def evaluate_aa_mask(full_headers, alignment, target_aa, target_pos_label, viewer_to_aln, valid_indices):
    """Evaluates an Amino Acid position into a boolean mask."""
    mask = np.zeros(len(full_headers), dtype=bool)
    
    if alignment is None or alignment.aln is None:
        print(f"Warning: Cannot evaluate '{target_aa}{target_pos_label}' without an alignment.")
        return mask
        
    target_aa = target_aa.upper()
    if not alignment.label_to_col or target_pos_label not in alignment.label_to_col:
        return mask
        
    col_idx = alignment.label_to_col[target_pos_label]
    is_gap_query = (target_aa == '_')
    aln_rows = viewer_to_aln[valid_indices]
    
    if hasattr(alignment.aln, 'bulk_residue_check'):
        if is_gap_query:
            mask_dash = alignment.aln.bulk_residue_check(col_idx, '-')
            mask_dot = alignment.aln.bulk_residue_check(col_idx, '.')
            aln_mask = mask_dash | mask_dot
        else:
            aln_mask = alignment.aln.bulk_residue_check(col_idx, target_aa)
        mask[valid_indices] = aln_mask[aln_rows]
    else:
        for i in valid_indices:
            row = int(viewer_to_aln[i])
            try:
                char = str(alignment.aln[row].seq[col_idx]).upper()
                if is_gap_query:
                    if char in cfg.GAP_CHARS: mask[i] = True
                else:
                    if char == target_aa: mask[i] = True
            except:
                pass
                
    return mask

def evaluate_metadata_mask(full_headers, metadata, target):
    """Evaluates a metadata query of the form 'PropertyOperatorValue' into a boolean mask.
    
    Example targets: 'Length>500', 'Organism=Escherichia coli', 'Organism=*coli*'
    """
    mask = np.zeros(len(full_headers), dtype=bool)
    if not metadata:
        print("Warning: No metadata loaded in the viewer to evaluate query.")
        return mask

    # Regex to extract Property, Operator, and Value
    pattern = re.compile(r'^([a-zA-Z0-9_\-]+)\s*(>=|<=|!=|==|>|<|=)\s*(.*)$')
    match = pattern.match(target.strip())
    if not match:
        print(f"Warning: Invalid metadata query format '{target}'. Use 'KeyOperatorValue' (e.g. 'Length>500').")
        return mask
        
    key, op, val_str = match.groups()
    val_str = val_str.strip()
    
    # Resolve the metadata key (case-insensitive lookup)
    meta_key = None
    for k in metadata.keys():
        if k.lower() == key.lower():
            meta_key = k
            break
            
    if meta_key is None:
        print(f"Warning: Metadata property '{key}' not found. Available properties: {list(metadata.keys())}")
        return mask
        
    meta_prop = metadata[meta_key]
    prop_type = meta_prop["type"]
    prop_vals = meta_prop["values"]
    
    # --- Numeric Evaluation ---
    if prop_type == "number":
        try:
            val = float(val_str)
        except ValueError:
            # Check for range syntax: e.g. 100-200
            if '-' in val_str and op in ('=', '=='):
                try:
                    low_str, high_str = val_str.split('-')
                    low_val = float(low_str.strip())
                    high_val = float(high_str.strip())
                    mask = (prop_vals >= low_val) & (prop_vals <= high_val)
                    return mask
                except ValueError:
                    pass
            print(f"Warning: Cannot convert value '{val_str}' to number for property '{meta_key}'.")
            return mask
            
        if op == '>':
            mask = prop_vals > val
        elif op == '<':
            mask = prop_vals < val
        elif op == '>=':
            mask = prop_vals >= val
        elif op == '<=':
            mask = prop_vals <= val
        elif op in ('==', '='):
            mask = prop_vals == val
        elif op == '!=':
            mask = prop_vals != val

    # --- Text/String Evaluation ---
    else:
        t_val = val_str.lower()
        clean_t_val = t_val.strip('"\'') # Handle optional quoting
        
        if op in ('==', '='):
            if '*' in t_val or '?' in t_val:
                for i, v in enumerate(prop_vals):
                    if fnmatch.fnmatch(str(v).lower(), t_val):
                        mask[i] = True
            else:
                for i, v in enumerate(prop_vals):
                    if clean_t_val in str(v).lower():
                        mask[i] = True
        elif op == '!=':
            if '*' in t_val or '?' in t_val:
                for i, v in enumerate(prop_vals):
                    if not fnmatch.fnmatch(str(v).lower(), t_val):
                        mask[i] = True
            else:
                for i, v in enumerate(prop_vals):
                    if clean_t_val not in str(v).lower():
                        mask[i] = True
                        
    return mask

def parse_advanced_expression(expr, viewer_to_aln, valid_indices, full_headers, cluster_labels=None, group_labels=None, alignment=None, metadata=None, selection_mask=None):
    """Tokenizes and evaluates complex boolean logic expressions with explicit syntax."""
    masks = {}
    mask_idx = 0
    
    # 1. Strings: "Text" (EXECUTED FIRST to protect wildcards containing @ or #)
    def string_repl(match):
        nonlocal mask_idx
        masks[f'M_{mask_idx}'] = evaluate_string_mask(full_headers, match.group(1))
        repl = f"masks['M_{mask_idx}']"
        mask_idx += 1
        return repl
    expr = re.sub(r'"([^"]+)"', string_repl, expr)
    
    # 1.5. Current selection: $sele$
    def sele_repl(match):
        nonlocal mask_idx
        masks[f'M_{mask_idx}'] = _coerce_node_mask(selection_mask, len(full_headers))
        repl = f"masks['M_{mask_idx}']"
        mask_idx += 1
        return repl
    expr = re.sub(r'\$sele\$', sele_repl, expr, flags=re.IGNORECASE)

    # 2. Files: @file_name@
    def file_repl(match):
        nonlocal mask_idx
        masks[f'M_{mask_idx}'] = evaluate_file_mask(full_headers, match.group(1))
        repl = f"masks['M_{mask_idx}']"
        mask_idx += 1
        return repl
    expr = re.sub(r'@([^@]+)@', file_repl, expr)

    # 2.5. Metadata: {key op val}
    def metadata_repl(match):
        nonlocal mask_idx
        masks[f'M_{mask_idx}'] = evaluate_metadata_mask(full_headers, metadata, match.group(1))
        repl = f"masks['M_{mask_idx}']"
        mask_idx += 1
        return repl
    expr = re.sub(r'\{([^}]+)\}', metadata_repl, expr)

    # 3. Labels (Clusters/Groups): #label_name#
    def label_repl(match):
        nonlocal mask_idx
        masks[f'M_{mask_idx}'] = evaluate_label_mask(full_headers, cluster_labels, group_labels, match.group(1))
        repl = f"masks['M_{mask_idx}']"
        mask_idx += 1
        return repl
    expr = re.sub(r'#([^#]+)#', label_repl, expr)
    
    # 4. AA Positions (Remaining unmatched text)
    def aa_repl(match):
        nonlocal mask_idx
        if match.group(0).startswith('M_') or match.group(0) == 'masks':
            return match.group(0)
        aa = match.group(1)
        pos = match.group(2)
        masks[f'M_{mask_idx}'] = evaluate_aa_mask(full_headers, alignment, aa, pos, viewer_to_aln, valid_indices)
        repl = f"masks['M_{mask_idx}']"
        mask_idx += 1
        return repl
    expr = re.sub(r'(?<!\w)([a-zA-Z_])([\d\.]+)\b', aa_repl, expr)
    
    final_expr = expr.replace("!", "~").replace("&", "&").replace("|", "|").replace("^", "^")
    try:
        return eval(final_expr, {"__builtins__": {}}, {"masks": masks})
    except Exception as e:
        # SelectionExpressionError subclasses ValueError, so existing handlers
        # still catch this, while upstream commands that catch the specific
        # type now match instead of surfacing a raw traceback at the prompt.
        raise SelectionExpressionError(f"Invalid logic expression: {final_expr}. Ensure no spaces exist inside the logic.")

def print_help(viewer, msg, *, terminal_msg=None, report_message=True):
    """Print a message to the terminal.

    The VR viewer has no on-canvas HUD: ``viewer.console_text`` is a DummyText
    stand-in kept only so command code shared with the desktop viewer can
    assign to it. The terminal is the only output surface here.

    The previous implementation forwarded multi-line messages to that stand-in
    and printed "Please see the viewer console for details." instead, which
    made every help text, table and report invisible in the VR terminal.
    """
    text = msg if terminal_msg is None else terminal_msg
    if report_message:
        report(message=text, viewer=viewer)
    viewer.console_text.text = text
    print(f"\n{text}")


def execute_reset(viewer, targets):
    """Executes reset on the specified targets."""
    lower_parts = [p.lower() for p in targets]
    
    if "help" in lower_parts or "-h" in lower_parts or "--help" in lower_parts:
        msg = "Usage: reset <target_1> [target_2] ...\nDescription: Resets specific properties of the network to their default or backup states.\nValid Targets:\n  colors   - Resets all node colors to default\n  sizes    - Resets all node sizes to default\n  shapes   - Resets all node shapes to default\n  clusters - Clears all cluster labels\n  groups   - Clears all group labels\n  hide     - Unhides all hidden nodes\n  network  - Restores node layout positions to the original or last saved state\nExamples:\n  reset network hide\n  reset colors sizes"
        print_help(viewer, msg)
        return

    targets_found = []
    needs_update = False
    
    viewer._save_state()
    
    for p in lower_parts:
        base_p = p[:-1] if p.endswith('s') else p
        
        if base_p == "color":
            if hasattr(viewer, 'current_colors'):
                neighbor_hex = getattr(cfg, 'NEIGHBOR_COLOR', '#4488ff')
                def parse_hex_color(hex_str):
                    h = hex_str.lstrip('#')
                    if len(h) == 6:
                        return [int(h[0:2], 16)/255.0, int(h[2:4], 16)/255.0, int(h[4:6], 16)/255.0, 1.0]
                    elif len(h) == 8:
                        return [int(h[0:2], 16)/255.0, int(h[2:4], 16)/255.0, int(h[4:6], 16)/255.0, int(h[6:8], 16)/255.0]
                    return [0.8, 0.8, 0.8, 1.0]
                n_rgba = parse_hex_color(neighbor_hex)
                viewer.current_colors[:] = n_rgba
            needs_update = True
            targets_found.append("colors")
            
        elif base_p == "size":
            if hasattr(viewer, 'current_sizes'):
                viewer.current_sizes.fill(cfg.NODE_SIZE)
            needs_update = True
            targets_found.append("sizes")
        
        elif base_p == "shape":
            if hasattr(viewer, 'current_shapes'):
                viewer.current_shapes.fill('disc')
            needs_update = True
            targets_found.append("shapes")

        elif base_p == "cluster":
            viewer.cluster_labels = None
            viewer.tooltip.text = "" 
            targets_found.append("clusters")

        elif base_p == "group":
            viewer.group_labels = [set() for _ in range(viewer.n_nodes)]
            viewer.tooltip.text = "" 
            targets_found.append("groups")
                
        elif base_p in ["hide", "hidden"]:
            viewer.visible_mask.fill(True)
            needs_update = True
            targets_found.append("hidden")
            
        elif base_p == "network":
            if hasattr(viewer, 'original_pos'):
                viewer.pos = viewer.original_pos.copy()
            needs_update = True
            targets_found.append("network")

    if needs_update:
        viewer.update_nodes()
        if "hidden" in targets_found or "network" in targets_found:
            viewer.update_edges()

    if targets_found:
        msg = f"Reset successful: {', '.join(targets_found)}."
    else:
        msg = "Usage: reset [colors | sizes | clusters | hide | network]"
    
    viewer.console_text.text = msg
    print(f"{msg}")


# =====================================================================
# Shared helpers mirrored from the main program's Command_Engine
# =====================================================================

def _coerce_node_mask(mask, n_nodes):
    """Normalize any selection input to a node-length Boolean mask."""
    result = np.zeros(n_nodes, dtype=bool)
    if mask is None:
        return result
    candidate = np.asarray(mask)
    if candidate.dtype == bool and candidate.shape == (n_nodes,):
        return candidate.copy()
    if candidate.dtype == bool:
        limit = min(candidate.shape[0] if candidate.ndim else 0, n_nodes)
        result[:limit] = candidate[:limit]
        return result
    # Otherwise treat it as a sequence of indices.
    for index in candidate.reshape(-1).tolist():
        try:
            index = int(index)
        except (TypeError, ValueError):
            continue
        if 0 <= index < n_nodes:
            result[index] = True
    return result


def get_selected_mask(viewer):
    """Return the current selection as a stable node-length Boolean mask."""
    n_nodes = int(
        getattr(viewer, "n_nodes", len(getattr(viewer, "full_headers", [])))
    )
    return _coerce_node_mask(getattr(viewer, "selected_indices", None), n_nodes)


def get_alignment_mapping(viewer):
    """Return the network-to-alignment map and the mapped node indices.

    Mirrors the main program's helper. Seven command modules had each
    open-coded this block.
    """
    full_headers = getattr(viewer, 'full_headers', [])
    n_nodes = len(full_headers)
    alignment = getattr(viewer, 'alignment', None)

    if alignment is not None:
        stored_mapping = getattr(alignment, 'viewer_to_aln', None)
        if stored_mapping is not None:
            stored_mapping = np.asarray(stored_mapping, dtype=int)
            if stored_mapping.shape == (n_nodes,):
                return stored_mapping, np.flatnonzero(stored_mapping >= 0)

    viewer_to_aln = np.full(n_nodes, -1, dtype=int)
    if alignment is not None and getattr(alignment, 'aln', None) is not None:
        seq_map = getattr(alignment, 'seq_map', {}) or {}
        for index, header in enumerate(full_headers):
            if header in seq_map:
                viewer_to_aln[index] = seq_map[header]
    return viewer_to_aln, np.flatnonzero(viewer_to_aln >= 0)


# --- Explicit outcome reporting -------------------------------------
# Upstream commands call these unconditionally. Here they forward to the
# Qt-free Viewer_Command_Portal shim, whose report() is a no-op unless an
# execution context is bound - which interactive typing never does. That is
# what lets an upstream command run unmodified in the VR terminal.

def report(status=None, message=None, artifact=None, viewer=None):
    from Viewer_Command_Portal import report as _report
    _report(status, message, artifact, viewer)


def command_succeeded(viewer, message=None, artifact=None):
    report('succeeded', message, artifact, viewer)


def command_failed(viewer, message):
    report('failed', str(message), viewer=viewer)


def command_cancelled(viewer, message):
    report('cancelled', str(message), viewer=viewer)


def command_artifact(viewer, path):
    report(artifact=path, viewer=viewer)


def report_selection_error(viewer, expression, error, operation="Selection"):
    """Canonical abort path for a bad Boolean expression."""
    command_failed(viewer, error)
    print_help(
        viewer,
        f"{operation} failed for expression: {expression}\n"
        f"  {error}\n"
        "Operation aborted; no changes were applied.",
        report_message=False,
    )
