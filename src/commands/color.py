import os
import re
import fnmatch
import numpy as np
import matplotlib.colors as mcolors
import Settings_VR as cfg
import Viewer_Utils_VR as utils
import Command_Engine

def print_help():
    print("""
    Advanced Coloring & Highlighting Tool
    =====================================
    Usage: color [EXPR_1] [COLOR_1] [xSCALE_1] [<EXPR_2> ...]
           color help

    Description:
      Colors and scales nodes. You can target nodes using complex
      boolean expressions.

      * QUICK USE: If no expression is provided, the command automatically targets
        the nodes currently selected in the viewer using your mouse.
      * IMPORTANT: Only visible nodes are affected; hidden nodes are skipped.
      * If any expression in the command is invalid, nothing is changed.

    Attributes:
      1. Color: Name (red, blue) or Hex (#ff0000)
      2. Scale: Prefix with 'x' (e.g., x2, x0.5)

    Expression Targets (Do NOT use spaces inside expressions!):
      1. AA Position:  [AA][Pos] (e.g., P106, _100 for gap)
      2. Header Text:  "[Text]"  (e.g., "3HMU", "*4A6T*")
      3. File Search:  @[File]@  (e.g., @my_list.txt@)
      4. NCBI/PDB:     @[NCBI][File]@ or @[PDB][File]@ (Regex extraction)
      5. Labels:       #[Name]#  (e.g., #cluster_1#, #noise#, #my_group#)
      6. UI Selection: $sele$     (Explicitly targets selected nodes)
      7. Metadata:     {Key Op Val} (e.g., {Length>500}, {Organism=*coli*})

    Logic Operators:
      & (AND), | (OR), ! (NOT), ^ (XOR)

    Examples:
      color red x2                      (Modifies currently selected nodes)
      color P106 red                    (Colors nodes with Proline at pos 106 red)
      color "ATA"&#cluster_2# blue x1.5 (Colors "ATA" matches inside Cluster 2)
      color {Organism=*coli*} green     (Colors nodes where Organism matches *coli* green)
      color #cluster_1# red #noise# x0  (Chains multiple commands together)
    """)

def run(viewer, args):
    if args and args[0].lower() == 'reset':
        Command_Engine.execute_reset(viewer, ["colors"])
        return

    if not args or args[0].lower() in ['help', '-h', '--help']:
        print_help()
        if hasattr(viewer, 'console_text'):
            viewer.console_text.text = "Help information printed to the console."
        return

    # $sele$ is resolved in memory by the expression parser. It used to be
    # spilled to HEADER_LIST_DIR/_sele.txt and read back as @_sele.txt@,
    # writing into the user's shared header-list directory on every call.
    selection_mask = Command_Engine.get_selected_mask(viewer)

    # Strip quoting so "$sele$" and '$sele$' resolve like a bare token.
    args = [re.sub(r'["\']?(\$sele\$)["\']?', r'\1', arg, flags=re.IGNORECASE)
            for arg in args]

    assignments = []
    current_expr = None
    current_color = None
    current_scale = None

    def push_assignment():
        nonlocal current_expr, current_color, current_scale
        
        # NEW: Default to targeting selected nodes if properties exist but no expression is given
        # A scale of 0 is a legal size (the help advertises "x0"), so compare
        # against None instead of testing truthiness.
        if not current_expr and (current_color or current_scale is not None):
            current_expr = '$sele$'

        if current_expr and (current_color or current_scale is not None):
            assignments.append((current_expr, current_color, current_scale))
        elif current_expr:
            print(f"Warning: Skipping '{current_expr}' (No valid color or scale provided)")

    for arg in args:
        # 1. Check if Scale (e.g., x2.5). Force lowercase 'x'.
        if arg.startswith('x'):
            try:
                current_scale = float(arg[1:])
                continue
            except ValueError:
                pass

        # 2. Check if explicitly an expression
        if any(c in arg for c in '&|!^"@') or arg.count('#') >= 2 or re.match(r'^[a-zA-Z_][\d\.]+$', arg):
            if current_expr:
                push_assignment()
                current_color = None; current_scale = None
            current_expr = arg
            continue
            
        # 3. Check if Color
        is_color = False
        try: mcolors.to_rgba(arg); is_color = True
        except:
            try: utils.hex_to_rgba(arg); is_color = True
            except: pass
        
        if is_color:
            if current_color is not None:
                push_assignment()
                current_color = None; current_scale = None
                current_expr = None
                current_color = arg
            else:
                current_color = arg
            continue
            
        # 4. Fallback for unrecognized tokens
        if current_expr:
            push_assignment()
            current_color = None; current_scale = None
        current_expr = arg

    if current_expr or current_color or current_scale is not None:
        push_assignment()
        
    if not assignments:
        if hasattr(viewer, 'console_text'):
            viewer.console_text.text = "Error: No valid assignments found."
        print("Error: No valid assignments found.")
        return

    viewer_to_aln = np.full(len(viewer.full_headers), -1, dtype=int)
    if (getattr(viewer, 'alignment', None).aln if getattr(viewer, 'alignment', None) else None) is not None:
        for i, h in enumerate(viewer.full_headers):
            if h in viewer.alignment.seq_map:
                viewer_to_aln[i] = viewer.alignment.seq_map[h]
    valid_indices = np.where(viewer_to_aln != -1)[0]
    
    total_modified = 0
    stats = []
    state_saved = False  # <--- NEW FLAG

    # Evaluate every expression BEFORE mutating any viewer state, so a bad
    # expression late in the chain cannot leave the earlier ones half-applied.
    evaluated_assignments = []
    for expr, color_str, scale_val in assignments:
        if expr:
            expr = re.sub(r'\{([^}]+)\}', lambda m: '{' + m.group(1).replace(' ', '') + '}', expr)
        try:
            mask = Command_Engine.parse_advanced_expression(expr, viewer_to_aln, valid_indices, viewer.full_headers, getattr(viewer, 'cluster_labels', None), getattr(viewer, 'group_labels', None), getattr(viewer, 'alignment', None), metadata=getattr(viewer, 'metadata', None), selection_mask=selection_mask)
        except Exception as e:
            Command_Engine.print_help(viewer, f"Error in expression '{expr}': {e}\nNothing was changed.")
            return

        # Hidden nodes are outside the command's target domain: recolouring them
        # is invisible now and would surprise the user after `reset hide`.
        mask = np.asarray(mask, dtype=bool) & viewer.visible_mask
        evaluated_assignments.append((expr, color_str, scale_val, mask, int(np.sum(mask))))

    for expr, color_str, scale_val, mask, count in evaluated_assignments:
        if count <= 0:
            print(f"No visible nodes matched expression: {expr}")
            continue

        # ---> NEW: Save state only once, and only if a match is actually found
        if not state_saved:
            viewer._save_state()
            state_saved = True

        if color_str:
            try: new_rgba = mcolors.to_rgba(color_str)
            except: new_rgba = utils.hex_to_rgba(color_str)
            viewer.current_colors[mask] = new_rgba

        if scale_val is not None: viewer.current_sizes[mask] = getattr(cfg, 'NODE_SIZE', 10.0) * scale_val

        total_modified += count

        labels = []
        if color_str: labels.append(color_str)
        if scale_val is not None: labels.append(f"x{scale_val}")
        stats.append(f"{count} nodes set to {', '.join(labels)}")

    if total_modified > 0:
        # update_nodes() is the only channel that reaches Unity; update_edges()
        # is a no-op here, so it is not called.
        viewer.update_nodes()
        if hasattr(viewer, 'console_text'):
            viewer.console_text.text = f"Color Updated: {'; '.join(stats)}"
        print(f"Color Updated: {'; '.join(stats)}")
