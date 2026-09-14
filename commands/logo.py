import os
import re
import numpy as np
from datetime import datetime  # <--- NEW IMPORT
import Settings as cfg
import Viewer_Utils as utils
import Command_Engine

def print_help():
    print("""
    Sequence Logo Generator
    =======================
    Usage: logo [EXPRESSION] [POSITIONS] [FILENAME] [MODE] [GAP_MODE] [COLOR_SCHEME]
           logo help

    Description:
      Generates a high-resolution SVG or PNG sequence logo for a targeted subset of nodes.
      Output is automatically saved to your 'Results/Sequence_Logos/' directory.

      * QUICK USE: If no expression is provided, the command automatically targets 
        the nodes currently selected in the viewer. If no nodes are selected, it 
        defaults to analyzing ALL nodes in the entire network.

    Arguments (Can be provided in almost any order):
      1. [POSITIONS] : (Required) Comma-separated list or ranges enclosed in brackets.
                       Example: [1, 2, 9-12]
      2. EXPRESSION  : Boolean logic target (e.g., #cluster_1#, "ATA", or $sele$).
      3. FILENAME    : Output name. Defaults to logo_YYYYMMDD_HHMMSS.svg. 
                       (Note: The LAST unrecognized string is treated as the filename).
      4. MODE        : 'bits' (Default, Information Content) or 'pcts' (Percentages).
      5. GAP_MODE    : 'with_gap' (Default, scales total height by occupancy) or 'no_gap'.
      6. COLOR_SCHEME: Preset color scheme name. (Default: chemistry)
                       Can be provided standalone or as key-value (e.g. color=classic).
                       Presets: chemistry, classic, grays, base_pairing, colorblind_safe,
                       weblogo_protein, skylign_protein, dmslogo_charge, dmslogo_funcgroup,
                       hydrophobicity, charge, NajafabadiEtAl2017.

    Examples:
      logo [10-20]                        (Logos pos 10-20 for selected or all nodes)
      logo #cluster_1# [1,5] pcts no_gap  (Percentage logo ignoring gaps for pos 1 and 5)
      logo [10-20] color=charge           (Generates bits logo using the charge color scheme)
      logo #cluster_1# [1,5] classic      (Generates bits logo using classic scheme)
      logo K10 [1] target_logo.png        (Logos pos 1 for K10 expr, saves as target_logo.png)
    """)

def _row_sequence(aln, row_index):
    """Return one alignment row as a plain string.

    Alignment_Manager's sparse loaders build a SeqRecord inside __getitem__
    without ever importing Seq/SeqRecord, so indexing or iterating them raises
    NameError. Rows are therefore rebuilt here straight from the sparse matrix;
    a real Biopython alignment still goes through normal indexing.
    """
    matrix = getattr(aln, 'matrix', None)
    int_to_aa = getattr(aln, 'int_to_aa', None)
    if matrix is None or int_to_aa is None:
        return str(aln[row_index].seq)
    row = matrix[row_index].toarray()[0]
    return "".join(int_to_aa.get(value, '-') if value != 0 else '-' for value in row)


def _normalize_logo_filename(filename):
    """Return a safe .svg/.png basename to write inside the logo directory."""
    filename = str(filename).strip()
    if not filename:
        raise ValueError("Filename cannot be empty.")
    if filename in ('.', '..') or "/" in filename or "\\" in filename:
        raise ValueError("Filename must not include a directory or path separators.")
    if re.search('[<>:"|?*]', filename) or any(ord(c) < 32 for c in filename):
        raise ValueError(f"Filename contains unsupported characters: '{filename}'.")
    if not filename.lower().endswith(('.png', '.svg')):
        filename += ".svg"
    return filename


def run(viewer, args):
    if not args or args[0].lower() in ['help', '-h', '--help']:
        print_help()
        if hasattr(viewer, 'console_text'):
            viewer.console_text.text = "Help information printed to the console."
        return

    try:
        import logomaker
        import pandas as pd
        import matplotlib.pyplot as plt
    except ImportError:
        msg = "Error: 'logomaker', 'pandas', or 'matplotlib' not installed. Run: pip install logomaker pandas matplotlib"
        Command_Engine.print_help(viewer, msg)
        return

    # 1. Extract Mode Keywords (Aggressively filter to prevent filename confusion)
    mode = "bits"
    gap_mode = "with_gap"
    
    # 1.5. Extract Color Scheme preset
    KNOWN_SCHEMES = [
        'classic', 'grays', 'base_pairing', 'colorblind_safe',
        'weblogo_protein', 'skylign_protein', 'dmslogo_charge',
        'dmslogo_funcgroup', 'hydrophobicity', 'chemistry', 'charge',
        'NajafabadiEtAl2017'
    ]
    color_scheme = "chemistry"  # Default
    
    filtered_args = []
    for arg in args:
        a_lower = arg.lower()
        match = re.match(r'^(color_scheme|colors|color|scheme)=(.*)$', arg, re.IGNORECASE)
        if match:
            color_scheme = match.group(2)
        elif a_lower in [s.lower() for s in KNOWN_SCHEMES]:
            color_scheme = [s for s in KNOWN_SCHEMES if s.lower() == a_lower][0]
        elif a_lower in ["pcts", "pct", "percentage", "percentages"]:
            mode = "pcts"
        elif a_lower in ["bits", "bit"]:
            mode = "bits"
        elif a_lower in ["with_gap", "with_gaps", "gaps", "gap"]:
            gap_mode = "with_gap"
        elif a_lower in ["no_gap", "no_gaps"]:
            gap_mode = "no_gap"
        else:
            filtered_args.append(arg)
            
    args = filtered_args

    # 2. Extract Positions Argument (First argument containing brackets)
    bracket_indices = [i for i, a in enumerate(args) if a.startswith('[') and a.endswith(']')]
    
    if not bracket_indices:
        msg = "Error: No positions provided. Use [...] syntax."
        Command_Engine.print_help(viewer, msg)
        return
        
    pos_idx = bracket_indices[0]
    pos_str = args.pop(pos_idx)
    
    # 3. Handle Ambiguity & Assign Filename/Expression
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"logo_{timestamp}.svg"
    expr = "$sele$" 
    
    if len(args) == 1:
        if args[0].lower().endswith(('.png', '.svg')) or args[0].startswith('['): 
            filename = args[0]
        else:
            expr = args[0]
    elif len(args) >= 2:
        filename = args.pop(-1)
        expr = "".join(args)

    try:
        filename = _normalize_logo_filename(filename)
    except ValueError as e:
        Command_Engine.print_help(viewer, f"Error: {e}")
        return

    # ---> NEW LOGIC: Smart Fallback to ALL Nodes <---
    if expr == "$sele$" and not getattr(viewer, 'selected_indices', []):
        expr = '"*"'  # The wildcard string matches all headers
        if hasattr(viewer, 'console_text'):
            viewer.console_text.text = "No selection found. Defaulting to ALL nodes."
        print("No nodes selected. Defaulting to ALL nodes in the network.")

    # 4. Handle UI Selection dynamically. Command_Engine.parse_advanced_expression
    # resolves $sele$ from the mask handed to it below, so the selection no
    # longer has to be spilled to Input_Files/Header_Lists/_sele.txt and read
    # back - a shared scratch file that two commands could race over, and that
    # silently substituted a stale selection whenever the write failed. Quotes
    # around the token are stripped first: the string rule runs before the
    # selection rule, so "$sele$" would otherwise be matched as a header pattern.
    expr = re.sub(r'["\']\$sele\$["\']', '$sele$', expr, flags=re.IGNORECASE)

    # 5. Parse Position Array
    inner = pos_str[1:-1]
    positions = set()
    for part in inner.split(','):
        part = part.strip()
        if not part: continue
        if '-' in part:
            try:
                start, end = map(int, part.split('-'))
                positions.update(range(start, end + 1))
            except ValueError: pass
        else:
            try: positions.add(int(part))
            except ValueError: pass
            
    requested_positions = sorted(list(positions))
    if not requested_positions:
        Command_Engine.print_help(viewer, "Error: Could not parse positions from brackets.")
        return

    # The alignment has to exist before the selection expression is evaluated:
    # every branch below indexes into it.
    alignment = getattr(viewer, 'alignment', None)
    if alignment is None or alignment.aln is None:
        Command_Engine.print_help(viewer, "Error: MSA not loaded in viewer. Please check inputs.")
        return
    if len(alignment.aln) == 0:
        Command_Engine.print_help(
            viewer,
            "Error: The selected MSA contains no aligned rows for the current network.")
        return

    # 6. Apply Boolean Logic to get matching sequences
    viewer_to_aln, valid_indices = Command_Engine.get_alignment_mapping(viewer)

    try:
        mask = Command_Engine.parse_advanced_expression(
            expr,
            viewer_to_aln,
            valid_indices,
            viewer.full_headers,
            getattr(viewer, 'cluster_labels', None),
            getattr(viewer, 'group_labels', None),
            getattr(viewer, 'alignment', None),
            metadata=getattr(viewer, 'metadata', None),
            selection_mask=Command_Engine.get_selected_mask(viewer),
        )
        selected_nodes = np.where(mask)[0]
    except Exception as e:
        Command_Engine.report_selection_error(viewer, expr, e, "Logo")
        return

    if len(selected_nodes) == 0:
        Command_Engine.print_help(viewer, "No nodes matched the criteria for logo generation.")
        return

    # 7. Map the Reference Sequence. The live reference wins over the configured
    # one: 'reference <ID>' and the occupancy-mode fallback in 'alignment' both
    # change viewer.active_reference without touching Settings.
    aln = alignment.aln
    ref_id = getattr(viewer, 'active_reference', None) or getattr(cfg, 'ALIGNMENT_REFERENCE', '')
    ref_seq_str = None

    if ref_id:
        header_map = getattr(aln, 'header_map', None)
        if header_map is not None: # Sparse mode
            for k, idx in header_map.items():
                if ref_id in k:
                    ref_seq_str = _row_sequence(aln, idx)
                    break
        else: # Legacy Biopython mode
            for r in aln:
                if ref_id in r.id or ref_id in r.description:
                    ref_seq_str = str(r.seq)
                    break

    if not ref_seq_str:
        print(f"Warning: Reference ID '{ref_id}' not found. Using the first sequence as reference.")
        ref_seq_str = _row_sequence(aln, 0)

    # Map Reference Coordinates to Alignment Columns (1-based mapping)
    ref_pos_to_col = {}
    curr_pos = 1
    for col_idx, char in enumerate(ref_seq_str):
        if char not in getattr(cfg, 'GAP_CHARS', ['-', '.']):
            ref_pos_to_col[curr_pos] = col_idx
            curr_pos += 1

    valid_cols = []
    plot_positions = []
    for p in requested_positions:
        if p in ref_pos_to_col:
            valid_cols.append(ref_pos_to_col[p])
            plot_positions.append(p)
        else:
            print(f"Warning: Position {p} exceeds reference sequence length.")

    if not valid_cols:
        Command_Engine.print_help(viewer, "Error: Requested positions are outside the sequence bounds.")
        return

    # 8. Extract Sequences for Selected Nodes
    selected_seqs = []
    for idx in selected_nodes:
        row_idx = int(viewer_to_aln[idx])
        if row_idx != -1:
            selected_seqs.append(_row_sequence(aln, row_idx))

    if not selected_seqs:
        Command_Engine.print_help(
            viewer, "Error: None of the matched nodes are present in the active alignment.")
        return

    # 9. Calculate Matrix Data
    AAs = list("ACDEFGHIKLMNPQRSTVWY")
    # logomaker draws each row at its index value, so non-contiguous positions
    # such as [1,5,300] must be packed onto evenly spaced coordinates and then
    # relabelled, otherwise the letters are separated by huge empty stretches.
    plot_coordinates = list(range(len(plot_positions)))
    df = pd.DataFrame(0.0, index=plot_coordinates, columns=AAs)
    
    # NEW: Store total sequences (N) for statistical penalties
    N_total = len(selected_seqs)

    for i, col in enumerate(valid_cols):
        col_chars = [s[col].upper() for s in selected_seqs if col < len(s)]
        valid_chars = [c for c in col_chars if c in AAs]
        
        n_valid = len(valid_chars)
        if n_valid == 0 or N_total == 0:
            continue
            
        occupancy = n_valid / N_total
        counts = {aa: valid_chars.count(aa) for aa in AAs}
        
        if mode == "pcts":
            for aa in AAs:
                val = counts[aa] / n_valid
                # Height scaling for gaps
                if gap_mode == "with_gap":
                    val *= occupancy
                df.at[i, aa] = val
        else:
            # Bits calculation
            H = 0
            for aa in AAs:
                p_i = counts[aa] / n_valid
                if p_i > 0:
                    H -= p_i * np.log2(p_i)
            
            # NEW: Small sample correction based on TOTAL sequences (N_total)
            e_n = 19.0 / (2.0 * np.log(2) * N_total)
            R = max(0.0, np.log2(20) - (H + e_n))
            
            for aa in AAs:
                p_i = counts[aa] / n_valid
                val = p_i * R
                # Height scaling for gaps
                if gap_mode == "with_gap":
                    val *= occupancy
                df.at[i, aa] = val

    # 10. Generate and Save Logo
    logo_dir = getattr(cfg, 'LOGO_DIR', os.path.join("Results", "Sequence_Logos"))
    os.makedirs(logo_dir, exist_ok=True)
    save_path = os.path.join(logo_dir, filename)

    try:
        from matplotlib.transforms import Affine2D
        
        fig_width = max(6, len(plot_positions) * 0.5 + 1)
        fig, ax = plt.subplots(figsize=(fig_width, 4))
        
        # 1. Generate standard flush logo
        logo = logomaker.Logo(df, ax=ax, color_scheme=color_scheme)
        
        # 2. THE MATRIX FIX (With Mode-Scaled Upper Limit)
        # Define the visual gap as a fraction of the total plot height (5%)
        BASE_GAP = 0.01 
        
        # Scale the absolute gap mathematically based on the Y-axis limits
        if mode == "pcts":
            MAX_GAP = BASE_GAP
        else:
            MAX_GAP = BASE_GAP * np.log2(20) # ~0.216 bits
            
        for patch in ax.patches:
            local_bbox = patch.get_path().get_extents()
            local_height = local_bbox.height
            
            if local_height > 0.001:
                local_ymax = local_bbox.ymax
                
                # Calculate the gap: 5% of the local height, capped at the global visual MAX_GAP
                gap = min(local_height * 0.05, MAX_GAP)
                
                # Convert the absolute gap back into a relative scale factor for this specific letter
                scale_factor = (local_height - gap) / local_height
                
                # Apply the shrink matrix anchored at the top
                local_shrink = Affine2D().translate(0, -local_ymax).scale(1.0, scale_factor).translate(0, local_ymax)
                patch.set_transform(local_shrink + patch.get_transform())
        
        logo.style_spines(visible=False)
        logo.style_spines(spines=['left', 'bottom'], visible=True)
        
        ax.set_xticks(plot_coordinates)
        ax.set_xticklabels(plot_positions)
        ax.set_xlim(-0.5, len(plot_coordinates) - 0.5)
        ax.set_xlabel(f"Position (relative to {ref_id or 'first sequence'})")

        # Fixed theoretical Y scale, so two logos can be compared side by side.
        if mode == "bits":
            ax.set_ylim(0.0, float(np.log2(len(AAs))))
            ylabel = "Information Content (Bits)" if gap_mode == "with_gap" else "Bits"
        else:
            from matplotlib.ticker import PercentFormatter
            ax.set_ylim(0.0, 1.0)
            ax.set_yticks(np.linspace(0.0, 1.0, 6))
            ax.yaxis.set_major_formatter(PercentFormatter(xmax=1.0, decimals=0))
            ylabel = "Percentage"

        ax.set_ylabel(ylabel)
        
        plt.tight_layout()
        
        # 3. HIGH RESOLUTION EXPORT
        plt.savefig(save_path, transparent=(filename.endswith('.png')), dpi=600, bbox_inches='tight')
        plt.close(fig)
        
        msg = f"Saved {gap_mode} {mode} logo for {len(selected_nodes)} nodes to {filename}"
        viewer.console_text.text = msg
        print(f"\nSuccess! {msg}")
        
    except Exception as e:
        msg = f"Plotting Error: {e}"
        Command_Engine.print_help(viewer, msg)
