import Command_Engine
import os
import re
import numpy as np
import pandas as pd
import h5py
import Viewer_Utils as utils
import Settings as cfg

def print_help(meta_dir_help):
    print(f"""
    Node Metadata Manager Tool (VR version)
    ==========================================
    Usage:
      meta <index> or meta <filename_query>
          Uploads the metadata file matching the index or query from the default metadata folder.
      meta list
          Lists all available metadata files in the default metadata folder.
      meta retrieve/download/export <filename> [expression]
          Downloads the current session metadata to the specified filename inside the metadata folder.
          An optional boolean logic expression can be provided at the end to filter 
          which nodes are exported (e.g., #cluster_1#, {{Length>500}}, or $sele$).
      meta help
          Displays this help message.

    Examples:
      meta 2
      meta my_metadata
      meta list
      meta download my_data.xlsx
      meta download filtered.xlsx {{Length>500}}
      meta export filtered_meta.xlsx #cluster_1#
      meta export selected_meta.xlsx $sele$
    """)

def export_metadata_value(value):
    """Keep whole numbers whole on export.

    Numeric metadata is stored as float64, so a Length of 350 used to be
    written back to the spreadsheet as 350.0.
    """
    if isinstance(value, (float, np.floating)) and float(value).is_integer():
        return int(value)
    return value

def is_logic_expression(arg):
    if any(c in arg for c in '{}#@&|!^"'):
        return True
    if arg.lower() == '$sele$':
        return True
    if re.match(r'^[a-zA-Z_][\d\.]+$', arg):
        return True
    return False

def run(viewer, args):
    meta_dir = getattr(cfg, 'METADATA_DIR', os.path.join("Cache_Files", "Meta_Data"))
    os.makedirs(meta_dir, exist_ok=True)

    if not args or args[0].lower() in ['help', '-h', '--help']:
        print_help(meta_dir)
        Command_Engine.command_succeeded(viewer, 'Help information printed to the terminal.')
        return

    # --- 2. Resolve Directory & Path ---
    is_download = False
    filepath = None
    filename = ""
    expr = None

    if args[0].lower() in ['retrieve', 'download', 'export']:
        is_download = True
        if len(args) < 2:
            msg = "Error: Please specify a filename for downloading metadata (e.g., 'meta download data.xlsx')."
            Command_Engine.print_help(viewer, msg)
            return

        # Check if filename or expression is provided
        if len(args) >= 2:
            if len(args) >= 3 and is_logic_expression(args[1]) and not is_logic_expression(args[-1]):
                filename = args[-1]
                expr = " ".join(args[1:-1]).strip()
            elif is_logic_expression(args[1]):
                # If only expression, filename is missing, print error
                msg = "Error: Please specify a filename for downloading metadata (e.g., 'meta download data.xlsx expression')."
                Command_Engine.print_help(viewer, msg)
                return
            else:
                filename = args[1]
                if len(args) >= 3:
                    expr = " ".join(args[2:]).strip()

        if filename:
            _, ext = os.path.splitext(filename)
            if not ext:
                filename += ".xlsx"
                ext = ".xlsx"
            if os.path.isabs(filename) or "/" in filename or "\\" in filename:
                filepath = filename
            else:
                filepath = os.path.join(meta_dir, filename)
    else:
        # Upload mode
        files = sorted([f for f in os.listdir(meta_dir) if f.endswith('.xlsx') or f.endswith('.xls') or f.endswith('.csv')])
        
        if args[0].lower() == 'list':
            if not files:
                msg = f"No metadata files found in '{meta_dir}'."
                Command_Engine.print_help(viewer, msg)
                Command_Engine.command_succeeded(viewer, msg)
                return
            print("\nAvailable metadata files:")
            print("=========================")
            for i, file in enumerate(files, 1):
                print(f"  {i: >2}. {file}")
            print("\nTo upload a metadata file, type: meta <index> or meta <filename_query>")
            Command_Engine.command_succeeded(
                viewer, f"Listed {len(files)} metadata files in the terminal."
            )
            return

        identifier = " ".join(args).strip()
        selected_file = None
        
        if identifier.isdigit():
            idx = int(identifier) - 1
            if 0 <= idx < len(files):
                selected_file = files[idx]
            else:
                msg = f"Error: Index '{identifier}' is out of range. Range is 1-{len(files)}."
                Command_Engine.print_help(viewer, msg)
                return
        else:
            matches = [f for f in files if identifier.lower() in f.lower()]
            if not matches:
                import fnmatch
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
                # Direct check
                filename = identifier
                _, ext = os.path.splitext(filename)
                if not ext:
                    filename += ".xlsx"
                    ext = ".xlsx"
                if os.path.isabs(filename) or "/" in filename or "\\" in filename:
                    filepath = filename
                else:
                    filepath = os.path.join(meta_dir, filename)

        if selected_file:
            filename = selected_file
            filepath = os.path.join(meta_dir, filename)
        
        _, ext = os.path.splitext(filename)

    # --- 3. Execute Download Mode ---
    if is_download:
        if not getattr(viewer, 'metadata', None):
            msg = "Error: No metadata available in the viewer to download."
            Command_Engine.print_help(viewer, msg)
            Command_Engine.command_failed(viewer, msg)
            return

        try:
            mask = np.ones(viewer.n_nodes, dtype=bool)
            if expr:
                # The command line is whitespace-split, so {key op value} has to
                # be re-tightened before the expression parser sees it.
                expr_cleaned = re.sub(r'\{([^}]+)\}', lambda m: '{' + m.group(1).replace(' ', '') + '}', expr)

                # $sele$ is understood natively now; it no longer has to be
                # round-tripped through Input_Files/Header_Lists/_sele.txt,
                # which clobbered that file as a side effect of an export.
                viewer_to_aln, valid_indices = Command_Engine.get_alignment_mapping(viewer)

                try:
                    mask = Command_Engine.parse_advanced_expression(
                        expr_cleaned,
                        viewer_to_aln,
                        valid_indices,
                        viewer.full_headers,
                        getattr(viewer, 'cluster_labels', None),
                        getattr(viewer, 'group_labels', None),
                        getattr(viewer, 'alignment', None),
                        metadata=viewer.metadata,
                        selection_mask=Command_Engine.get_selected_mask(viewer)
                    )
                except ValueError as error:
                    Command_Engine.report_selection_error(
                        viewer, expr, error, "Metadata export"
                    )
                    return

                if np.sum(mask) == 0:
                    msg = f"Error: No nodes matched the expression '{expr}'."
                    Command_Engine.print_help(viewer, msg)
                    Command_Engine.command_failed(viewer, msg)
                    return

            # Every property is exported, Length included: excluding it meant a
            # downloaded sheet could not be re-uploaded without losing it.
            prop_names = list(viewer.metadata.keys())
            row_0 = [""] + prop_names
            row_1 = [""] + [viewer.metadata[p]["type"] for p in prop_names]
            
            rows = [row_0, row_1]
            for i in range(viewer.n_nodes):
                if not mask[i]:
                    continue
                has_valid_prop = False
                row_val = [viewer.full_headers[i]]
                for p in prop_names:
                    val = viewer.metadata[p]["values"][i]
                    if viewer.metadata[p]["type"] == "number":
                        if pd.notna(val):
                            has_valid_prop = True
                            row_val.append(export_metadata_value(val))
                        else:
                            row_val.append("")
                    else:
                        if val is not None and str(val).strip() != "":
                            has_valid_prop = True
                            row_val.append(val)
                        else:
                            row_val.append("")
                
                if has_valid_prop or expr:
                    rows.append(row_val)

            df = pd.DataFrame(rows)

            if ext.lower() == ".csv":
                df.to_csv(filepath, header=False, index=False)
            else:
                df.to_excel(filepath, header=False, index=False)

            msg = f"Metadata successfully downloaded to {filepath}"
            if expr:
                msg += f" (filtered by: {expr})"
            Command_Engine.print_help(viewer, msg)
            Command_Engine.command_artifact(viewer, filepath)
            Command_Engine.command_succeeded(viewer, msg)
        except Exception as e:
            msg = f"Error downloading metadata: {e}"
            Command_Engine.print_help(viewer, msg)
            Command_Engine.command_failed(viewer, msg)
        return

    # --- 4. Execute Upload Mode ---
    if not filepath or not os.path.exists(filepath):
        msg = f"Error: Could not find file '{filename}'."
        Command_Engine.print_help(viewer, msg)
        Command_Engine.command_failed(viewer, msg)
        return

    try:
        if ext.lower() == ".csv":
            df = pd.read_csv(filepath, header=None, dtype=str)
        else:
            df = pd.read_excel(filepath, header=None)

        if df.shape[0] < 3 or df.shape[1] < 2:
            msg = "Error: Invalid file format. Must contain at least sequence headers and one property column."
            Command_Engine.print_help(viewer, msg)
            Command_Engine.command_failed(viewer, msg)
            return

        prop_names = []
        valid_cols = []
        for col_idx in range(1, df.shape[1]):
            val = df.iloc[0, col_idx]
            if pd.notna(val) and str(val).strip():
                prop_names.append(str(val).strip())
                valid_cols.append(col_idx)

        if not prop_names:
            msg = "Error: No valid property names found in the first row."
            Command_Engine.print_help(viewer, msg)
            Command_Engine.command_failed(viewer, msg)
            return

        illegal_props = [p for p in prop_names if not re.match(r'^[a-zA-Z0-9_\-\.]+$', p)]
        if illegal_props:
            msg = (
                f"Error: Property names {', '.join(repr(p) for p in illegal_props)} contain "
                "illegal characters. Allowed characters are: letters, numbers, underscores (_), "
                "hyphens (-), and periods (.)"
            )
            Command_Engine.print_help(viewer, msg)
            Command_Engine.command_failed(viewer, msg)
            return

        prop_types = []
        for col_idx in valid_cols:
            val = df.iloc[1, col_idx]
            if pd.notna(val) and str(val).strip():
                t = str(val).strip().lower()
                if t in ['number', 'num', 'numerical']:
                    prop_types.append('number')
                else:
                    prop_types.append('text')
            else:
                prop_types.append('text')

        header_to_idx = {h: idx for idx, h in enumerate(viewer.full_headers)}
        node_updates = {}
        matched_count = 0
        unmatched_count = 0

        for df_row_idx in range(2, df.shape[0]):
            header_val = df.iloc[df_row_idx, 0]
            if pd.isna(header_val):
                unmatched_count += 1
                continue
            header_str = str(header_val).strip()
            
            if header_str in header_to_idx:
                node_idx = header_to_idx[header_str]
                node_updates[node_idx] = df_row_idx
                matched_count += 1
            else:
                unmatched_count += 1

        if matched_count == 0:
            msg = "Error: No matching sequence headers found. Enforced strict exact matching against full headers."
            Command_Engine.print_help(viewer, msg)
            Command_Engine.command_failed(viewer, msg)
            return

        viewer._save_state()

        for p_idx, prop_name in enumerate(prop_names):
            prop_type = prop_types[p_idx]
            col_idx = valid_cols[p_idx]

            if prop_name not in viewer.metadata:
                if prop_type == 'number':
                    values = np.full(viewer.n_nodes, np.nan, dtype=np.float64)
                else:
                    values = np.full(viewer.n_nodes, "", dtype=object)
                viewer.metadata[prop_name] = {
                    "type": prop_type,
                    "values": values
                }
            else:
                old_type = viewer.metadata[prop_name]["type"]
                viewer.metadata[prop_name]["type"] = prop_type
                
                if old_type != prop_type:
                    old_vals = viewer.metadata[prop_name]["values"]
                    if prop_type == 'number':
                        new_vals = np.full(viewer.n_nodes, np.nan, dtype=np.float64)
                        for i in range(viewer.n_nodes):
                            try:
                                if str(old_vals[i]).strip():
                                    new_vals[i] = float(old_vals[i])
                            except ValueError:
                                pass
                        viewer.metadata[prop_name]["values"] = new_vals
                    else:
                        new_vals = np.full(viewer.n_nodes, "", dtype=object)
                        for i in range(viewer.n_nodes):
                            if pd.notna(old_vals[i]):
                                new_vals[i] = str(old_vals[i])
                        viewer.metadata[prop_name]["values"] = new_vals

            values_arr = viewer.metadata[prop_name]["values"]
            for node_idx, df_row_idx in node_updates.items():
                cell_val = df.iloc[df_row_idx, col_idx]
                if pd.isna(cell_val) or str(cell_val).strip() == "" or str(cell_val).strip().lower() == "nan":
                    continue
                
                if prop_type == 'number':
                    try:
                        values_arr[node_idx] = float(cell_val)
                    except (ValueError, TypeError):
                        pass
                else:
                    values_arr[node_idx] = str(cell_val)

        # The session may not be bound to a cache file at all; os.path.exists
        # used to raise TypeError on None *after* the merge had been applied.
        cache_path, _ = utils.get_cache_filename()
        if cache_path and os.path.exists(cache_path):
            try:
                with h5py.File(cache_path, "a") as hf:
                    if "metadata" in hf:
                        del hf["metadata"]
                    meta_group = hf.create_group("metadata")
                    for p_name, p_data in viewer.metadata.items():
                        p_type = p_data["type"]
                        vals = p_data["values"]
                        if p_type == "number":
                            ds = meta_group.create_dataset(p_name, data=vals, compression="gzip")
                        else:
                            dt_str = h5py.string_dtype(encoding='utf-8')
                            ds = meta_group.create_dataset(p_name, data=np.array(vals, dtype=object), dtype=dt_str, compression="gzip")
                        ds.attrs["type"] = p_type
            except Exception as e:
                print(f"Warning: Failed to write metadata to cache file: {e}")

        msg = (
            f"Successfully uploaded metadata: matched {matched_count} nodes, "
            f"ignored {unmatched_count} rows. Merged {len(prop_names)} properties: "
            f"{', '.join(prop_names)}."
        )
        Command_Engine.print_help(viewer, msg)
        Command_Engine.command_succeeded(viewer, msg)

    except Exception as e:
        msg = f"Error uploading metadata: {e}"
        Command_Engine.print_help(viewer, msg)
        Command_Engine.command_failed(viewer, msg)
        import traceback
        traceback.print_exc()
