import Command_Engine
import os
import re
from Bio import SeqIO
import Settings_VR as cfg
import Viewer_Utils_VR as utils

def _sequence_export_directory():
    """Resolve the configured Sequence_Export folder.

    The previous implementation wrote to the relative path
    "Cache_Files/FASTA_Split", which lands wherever the VR process happened to
    be launched from - usually inside the opt_vr checkout - instead of the
    Analysis Results directory the user configured. Upstream routes exports to
    $analysis_result$/Sequence_Export; this mirrors that without requiring the
    Qt config module.
    """
    base = getattr(cfg, "SEQUENCE_EXPORT_DIR", None)
    if base:
        return base
    base = getattr(cfg, "ANALYSIS_RESULT_DIR", None) or os.path.join(
        getattr(cfg, "PROJECT_ROOT", "."), "Analysis_Results"
    )
    return os.path.join(base, "Sequence_Export")

def print_help():
    print("""
    FASTA Export Tool
    =================
    Usage: export [TARGET] [<TARGET_2> ...]
           export help

    Description:
      Extracts sequence subsets from the currently active viewer state and saves them 
      as standalone .fasta files. Files are routed to strictly organized subdirectories 
      of the Sequence_Export folder inside the configured Analysis Results directory.
      The destination is printed to the terminal when the export completes.
      
    [TARGET] Arguments (Default: clusters):
      clusters : Exports sequences based on their assigned topology cluster ID. 
                 (Note: Unclustered 'Noise' nodes are automatically ignored).
      groups   : Exports separate .fasta files for ALL custom group labels currently defined.
                 ('group' is accepted as a synonym.)
      group:<Name> : Exports only specific groups by prefixing with group: (e.g., group:kinase).
                     You can chain multiple specific groups (e.g., export group:kinase group:receptor).
      Unrecognized targets are rejected instead of being silently exported as clusters.

    Examples:
      export             (Defaults to exporting all clusters)
      export groups      (Exports all custom groups)
      export group:human (Exports only the sequences in the 'human' group)
    """)
    
def run(viewer, args):
    if args and args[0].lower() in ['help', '-h', '-?']:
        print_help()
        Command_Engine.command_succeeded(viewer, 'Help information printed to the terminal.')
        return

    # --- 1. Parse Arguments ---
    target_mode = "clusters"
    specific_groups = []
    mode_tokens = []

    for arg in args:
        arg_lower = arg.lower()
        if arg_lower in ("clusters", "cluster"):
            mode_tokens.append("clusters")
        elif arg_lower in ("groups", "group"):
            mode_tokens.append("groups")
        elif arg_lower.startswith("group:") and arg_lower[6:].strip():
            g_target = arg_lower[6:].strip()
            if g_target not in specific_groups:
                specific_groups.append(g_target)
        else:
            # An unknown target used to be ignored, so a typo silently
            # exported every cluster instead of what was asked for.
            msg = (f"Error: Unrecognized export target '{arg}'. "
                   "Use clusters, groups, or group:<Name>.")
            Command_Engine.print_help(viewer, msg)
            Command_Engine.command_failed(viewer, msg)
            return

    if mode_tokens and specific_groups:
        msg = "Error: 'clusters'/'groups' cannot be combined with specific group:<Name> targets."
        Command_Engine.print_help(viewer, msg)
        Command_Engine.command_failed(viewer, msg)
        return
    if len(set(mode_tokens)) > 1:
        msg = "Error: Export accepts only one all-target mode: clusters or groups."
        Command_Engine.print_help(viewer, msg)
        Command_Engine.command_failed(viewer, msg)
        return

    if specific_groups:
        target_mode = "specific"
    elif mode_tokens:
        target_mode = mode_tokens[0]

    # --- Validations ---
    if target_mode == "clusters" and getattr(viewer, 'cluster_labels', None) is None:
        msg = "Error: Run 'cluster' first to export clusters."
        Command_Engine.print_help(viewer, msg)
        Command_Engine.command_failed(viewer, msg)
        return
        
    if target_mode in ["groups", "specific"] and getattr(viewer, 'group_labels', None) is None:
        msg = "Error: No groups defined. Use the 'group' command first."
        Command_Engine.print_help(viewer, msg)
        Command_Engine.command_failed(viewer, msg)
        return

    # --- 2. Load Source FASTA ---
    fasta_path = getattr(cfg, 'NODE_FASTA_FILE', None)
    if not fasta_path or not os.path.exists(fasta_path):
        fasta_path = getattr(cfg, 'SEQUENCES_FILE', None)
        
    if not fasta_path or not os.path.exists(fasta_path):
        msg = "Error: Cannot find source FASTA file."
        Command_Engine.print_help(viewer, msg)
        Command_Engine.command_failed(viewer, msg)
        return

    print(f"Loading source FASTA: {os.path.basename(fasta_path)}...")
    source_records = {}
    try:
        for rec in SeqIO.parse(fasta_path, "fasta"):
            # Store by full header to ensure perfect mapping
            source_records[rec.description] = rec
    except Exception as e:
        msg = f"Error reading FASTA: {e}"
        Command_Engine.print_help(viewer, msg)
        Command_Engine.command_failed(viewer, msg)
        return

    # --- 3. Resolve Target Directory (NO Reference Injection) ---
    hdf5_base = os.path.basename(getattr(cfg, 'INPUT_HDF5', ''))
    fasta_base = os.path.splitext(os.path.basename(fasta_path))[0]
    
    match = re.search(r'(\[.*?\])', hdf5_base)
    if match:
        model_str = f"_{match.group(1)}"
    else:
        hdf5_no_ext = hdf5_base[:-3] if hdf5_base.endswith(".h5") else os.path.splitext(hdf5_base)[0]
        stripped = re.sub(r'_(network|evalue)$', '', hdf5_no_ext, flags=re.IGNORECASE)
        old_match = re.search(r'_(e[0-9]+_.*|blast.*)$', stripped, flags=re.IGNORECASE)
        model_str = f"_{old_match.group(1)}" if old_match else ""
        
    lvl1_name = f"{fasta_base}{model_str}"
    is_blast = "EValue" in hdf5_base or "Evalue" in hdf5_base or "blast" in hdf5_base.lower()
    if not is_blast:
        norm_m = getattr(cfg, 'NORM_MODE', None)
        if norm_m: lvl1_name += f"_{norm_m}"
        score_m = getattr(cfg, 'ALIGNMENT_SCORE', None)
        if score_m: lvl1_name += f"_{score_m}"
        
    lvl2_name_base = ""
    top_val = getattr(cfg, 'TOP_EDGE_PERCENT', None)
    if top_val is not None and str(top_val).strip() != "None":
        try: lvl2_name_base += f"Top{float(top_val)}Pct"
        except: pass
    else:
        thresh = getattr(cfg, 'SIMILARITY_THRESHOLD', 0.0)
        try: lvl2_name_base += f"Score{float(thresh)}"
        except: pass
        
    if target_mode == "clusters":
        if getattr(viewer, 'last_cluster_params', None):
            c_mode_param, c_min_param = viewer.last_cluster_params
            if lvl2_name_base:
                lvl2_name = f"{lvl2_name_base}_{c_mode_param}_Min{c_min_param}"
            else:
                lvl2_name = f"{c_mode_param}_Min{c_min_param}"
        else:
            lvl2_name = lvl2_name_base
    else:
        lvl2_name = lvl2_name_base

    # Build Output Path (configured Analysis Results / Sequence_Export)
    out_dir = os.path.join(_sequence_export_directory(), lvl1_name)
    
    if target_mode in ["groups", "specific"]:
        final_dir_name = f"{lvl2_name}_GROUPS" if lvl2_name else "GROUPS"
        out_dir = os.path.join(out_dir, final_dir_name)
    else:
        out_dir = os.path.join(out_dir, lvl2_name) if lvl2_name else out_dir

    # --- 4. Group Sequences ---
    file_map = {}
    missing_count = 0
    
    print("Mapping sequences...")
    for i, full_header in enumerate(viewer.full_headers):
        if full_header not in source_records:
            missing_count += 1
            continue
            
        record = source_records[full_header]
        
        if target_mode == "clusters":
            if i >= len(viewer.cluster_labels): continue
            cid = viewer.cluster_labels[i]
            if cid == -1: continue # Skip noise
            
            file_name = f"Cluster_{cid}.fasta"
            if file_name not in file_map: file_map[file_name] = []
            file_map[file_name].append(record)
            
        elif target_mode == "groups":
            if i >= len(viewer.group_labels): continue
            for g_name in viewer.group_labels[i]:
                file_name = f"{g_name}.fasta"
                if file_name not in file_map: file_map[file_name] = []
                file_map[file_name].append(record)
                
        elif target_mode == "specific":
            if i >= len(viewer.group_labels): continue
            for g_name in viewer.group_labels[i]:
                if g_name.lower() in specific_groups:
                    file_name = f"{g_name}.fasta"
                    if file_name not in file_map: file_map[file_name] = []
                    file_map[file_name].append(record)

    if missing_count > 0:
        print(f"Warning: {missing_count} viewer nodes were not found in the original FASTA file.")

    if not file_map:
        # Nothing to write: do not leave an empty directory tree behind.
        msg = "No valid subsets found to export."
        Command_Engine.print_help(viewer, msg)
        Command_Engine.command_succeeded(viewer, msg)
        return

    os.makedirs(out_dir, exist_ok=True)

    # --- 5. Write Files ---
    print(f"Exporting to: {out_dir}")
    files_written = 0
    seqs_written = 0
    
    for filename, recs in file_map.items():
        out_path = os.path.join(out_dir, filename)
        try:
            SeqIO.write(recs, out_path, "fasta")
            Command_Engine.command_artifact(viewer, out_path)
            files_written += 1
            seqs_written += len(recs)
        except Exception as e:
            print(f"Failed to write {filename}: {e}")
            Command_Engine.command_failed(viewer, f"Failed to write {filename}: {e}")

    # The terminal is the only output surface here, so the destination is
    # reported instead of popping a file manager window over the headset.
    msg = (f"Exported {files_written} files ({seqs_written} sequences) to:\n"
           f"  {os.path.abspath(out_dir)}")
    Command_Engine.print_help(viewer, msg)
    Command_Engine.command_succeeded(viewer, msg)
