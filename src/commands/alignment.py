import os
import fnmatch
import Settings_VR as cfg
import Command_Engine

def print_help():
    print("""
    Alignment Switcher Tool (VR version)
    =======================================
    Usage:
      alignment <alignment_identifier>
          Loads the MSA file matching the identifier (index or filename query) 
          from the Multiple Alignments folder.
      alignment list
          Lists all available alignments in the Multiple Alignments folder.
      alignment help
          Displays this help message.

    Loading Rules:
      To load successfully, the FASTA subset currently representing the nodes in the viewer 
      must be a strict subset of the sequence headers present in the new MSA file. 
      If any node is missing, the load fails and the system automatically rolls back 
      to the previously active alignment to ensure session stability.
    """)

def run(viewer, args):
    if args and args[0].lower() in ['help', '-h', '--help']:
        print_help()
        if hasattr(viewer, 'console_text'):
            viewer.console_text.text = "Help printed to console."
        return

    msa_dir = getattr(cfg, 'MSA_DIR', os.path.join("Input_Files", "Multiple_Alignments"))

    if not args:
        msg = "Error: Please specify an alignment or type 'alignment list' to see available alignments."
        Command_Engine.print_help(viewer, msg)
        return

    # Check if list is requested
    if args[0].lower() == 'list':
        if not os.path.exists(msa_dir):
            msg = f"Error: MSA directory '{msa_dir}' does not exist."
            Command_Engine.print_help(viewer, msg)
            return
        files = sorted([f for f in os.listdir(msa_dir) if f.endswith('.fasta') or f.endswith('.h5')])
        if not files:
            msg = f"No alignment files found in '{msa_dir}'."
            Command_Engine.print_help(viewer, msg)
            return
        print("\nAvailable alignments:")
        print("=====================")
        current_base = os.path.basename(cfg.MSA_FILE) if cfg.MSA_FILE else ""
        for i, file in enumerate(files, 1):
            is_active = "[ACTIVE]" if file == current_base else ""
            print(f"  {i: >2}. {file} {is_active}")
        print("\nTo load an alignment, type: alignment <index> or alignment <filename_query>")
        if hasattr(viewer, 'console_text'):
            viewer.console_text.text = f"Listed {len(files)} alignments in console."
        return

    identifier = " ".join(args).strip()

    # Accept a direct path first (absolute, relative, or a bare name inside the
    # MSA folder, with the .fasta/.h5 extension optional). The index / substring
    # catalogue lookup below is only used when the identifier is not a real file.
    selected_file = None
    new_path = None
    candidates = [identifier, os.path.join(msa_dir, identifier)]
    for ext in ('.fasta', '.h5'):
        candidates.append(identifier + ext)
        candidates.append(os.path.join(msa_dir, identifier + ext))
    for candidate in candidates:
        if os.path.isfile(candidate):
            new_path = os.path.abspath(candidate).replace("\\", "/")
            selected_file = os.path.basename(candidate)
            break

    if new_path is None and not os.path.exists(msa_dir):
        msg = f"Error: MSA directory '{msa_dir}' does not exist."
        Command_Engine.print_help(viewer, msg)
        return
        
    files = [] if new_path is not None else sorted(
        [f for f in os.listdir(msa_dir) if f.endswith('.fasta') or f.endswith('.h5')])
    if new_path is None and not files:
        msg = f"Error: No alignment files found in '{msa_dir}'."
        Command_Engine.print_help(viewer, msg)
        return

    if new_path is not None:
        pass  # the identifier already resolved to a file on disk
    elif identifier.isdigit():
        idx = int(identifier) - 1
        if 0 <= idx < len(files):
            selected_file = files[idx]
        else:
            msg = f"Error: Index '{identifier}' is out of range. Range is 1-{len(files)}."
            Command_Engine.print_help(viewer, msg)
            return
    else:
        # Search by case-insensitive substring
        matches = [f for f in files if identifier.lower() in f.lower()]
        if not matches:
            matches = [f for f in files if fnmatch.fnmatch(f.lower(), identifier.lower())]
            
        if len(matches) == 1:
            selected_file = matches[0]
        elif len(matches) > 1:
            print(f"\nMultiple matches found for '{identifier}':")
            for f in matches:
                print(f"  - {f}")
            msg = "Error: Ambiguous query. Please be more specific."
            Command_Engine.print_help(viewer, msg)
            return
        else:
            msg = f"Error: No alignments matching '{identifier}' found."
            Command_Engine.print_help(viewer, msg)
            return

    if new_path is None:
        new_path = os.path.join(msa_dir, selected_file).replace("\\", "/")

    # Load the selected alignment file
    print(f"\nAttempting to load alignment: {selected_file}...")
    if hasattr(viewer, 'console_text'):
        viewer.console_text.text = f"Loading {selected_file}..."

    # Backup current state for safety rollback
    backup_msa_file = cfg.MSA_FILE
    backup_alignment = viewer.alignment
    backup_active_ref = viewer.active_reference

    cfg.MSA_FILE = new_path

    try:
        viewer.load_global_alignment()

        # Alignment_Manager signals two very different failures the same way
        # (aln is None), and Viewer.load_global_alignment() swallows the
        # underlying exception, so they are told apart by valid_cols: it is only
        # populated once the file has parsed, which means the reference sequence
        # was the sole problem. A file that never parsed (unreadable, or not a
        # strict superset of the network's sequence set) fails identically
        # without a reference, so retrying it only wastes a second full load.
        parsed_ok = (
            viewer.alignment is not None
            and getattr(viewer.alignment, 'valid_cols', None) is not None
        )
        if viewer.alignment is None or viewer.alignment.aln is None:
            if not parsed_ok:
                raise ValueError(
                    f"'{selected_file}' could not be read as an alignment. The "
                    "loader messages printed above give the reason; the usual "
                    "cause is a sequence subset violation - every node currently "
                    "in the viewer must also be present in the new MSA."
                )

            print(f"Warning: Active reference '{viewer.active_reference}' not found in '{selected_file}'.")
            print("Re-attempting load in Pure Occupancy Mode (no reference sequence)...")
            viewer.active_reference = None
            viewer.load_global_alignment()

            if viewer.alignment is None or viewer.alignment.aln is None:
                raise ValueError("Alignment loader failed to return an alignment.")
            else:
                success_msg = f"Success: Loaded '{selected_file}' in Pure Occupancy Mode."
                print(f"\n{success_msg}")
                if hasattr(viewer, 'console_text'):
                    viewer.console_text.text = f"Loaded {selected_file} (No Ref)"
        else:
            success_msg = f"Success: Loaded alignment '{selected_file}'."
            print(f"\n{success_msg}")
            if hasattr(viewer, 'console_text'):
                viewer.console_text.text = f"Loaded {selected_file}"

    except Exception as e:
        print(f"\nFailed to load alignment '{selected_file}': {e}")
        print("Reverting to previous alignment state...")
        
        # Rollback
        cfg.MSA_FILE = backup_msa_file
        viewer.alignment = backup_alignment
        viewer.active_reference = backup_active_ref
        
        if hasattr(viewer, 'console_text'):
            viewer.console_text.text = "Load failed. Reverted to previous alignment."
