import Command_Engine
import os
import h5py
import numpy as np
import json
import Cache_Manifest as cache_manifest
import Settings as cfg
import Viewer_Utils as utils

def run(viewer, args):
    if args and args[0].lower() in ['help', '-h', '--help']:
        msg = "Usage: save [filename.h5]\nDescription: Takes a snapshot of the current network state (positions, colors, sizes, shapes, visibility, clusters, groups) and saves it as an HDF5 layout cache.\nThe file is always written into the cache folder this session is bound to, so the name must be a plain .h5 basename.\nIf no filename is provided, it automatically generates a versioned filename (e.g., version_01.h5).\nExamples:\n  save\n  save my_layout.h5"
        Command_Engine.print_help(viewer, msg, report_message=False)
        Command_Engine.command_succeeded(viewer, 'Help information printed to the terminal.')
        return
        
    partial_save_path = None
    try:
        default_path, _ = utils.get_cache_filename()
        if not default_path:
            # Without a bound cache folder this used to fail deep inside
            # os.path.dirname(None) and surface as a bare TypeError.
            raise ValueError(
                "No layout cache is bound to this session, so there is no folder "
                "to save into. Launch the viewer through the EMAP-SSN launcher or "
                "set TARGET_CACHE_PATH in the settings, then try again."
            )
        folder_path = os.path.dirname(default_path)

        os.makedirs(folder_path, exist_ok=True)

        if args:
            save_name = args[0]
            if not save_name.endswith(".h5"):
                save_name += ".h5"
            # Rejects "../escape.h5" and friends: the snapshot belongs in the
            # session cache folder, not wherever a relative path points.
            cache_manifest.validate_cache_filename(save_name)
        else:
            # The main program owns the cache naming convention, so reuse its
            # helper instead of inventing a second "_ver.NN" scheme that its
            # own version scan cannot see.
            save_name = cache_manifest.next_cache_version_filename(folder_path)
        final_save_path = os.path.join(folder_path, save_name)

        # Write to a sibling .partial first: a crash mid-write must not leave
        # a truncated .h5 that the next session would load as the layout.
        partial_save_path = final_save_path + ".partial"
        if os.path.exists(partial_save_path):
            os.remove(partial_save_path)

        with h5py.File(partial_save_path, "w") as hf:
            dt_str = h5py.string_dtype(encoding='utf-8')
            hf.create_dataset("headers", data=np.array(viewer.full_headers, dtype=object), dtype=dt_str, compression="gzip")
            hf.create_dataset("positions", data=viewer.pos, compression="gzip")
            
            if hasattr(viewer, 'current_colors'): hf.create_dataset("colors", data=viewer.current_colors, compression="gzip")
            if hasattr(viewer, 'current_sizes'):
                hf.create_dataset("sizes", data=viewer.current_sizes, compression="gzip")
                hf.attrs["base_node_size"] = getattr(cfg, 'NODE_SIZE', 10)
            if hasattr(viewer, 'current_shapes'): hf.create_dataset("shapes", data=np.array(viewer.current_shapes, dtype=object), dtype=dt_str, compression="gzip")
            if hasattr(viewer, 'visible_mask'): hf.create_dataset("visible_mask", data=viewer.visible_mask, compression="gzip")
            if getattr(viewer, 'cluster_labels', None) is not None: hf.create_dataset("cluster_labels", data=viewer.cluster_labels, compression="gzip")
            
            if hasattr(viewer, 'group_labels'):
                hf.create_dataset("group_labels", data=json.dumps([list(g) for g in viewer.group_labels]))
                
            if getattr(viewer, 'metadata', None):
                meta_group = hf.create_group("metadata")
                for prop_name, prop_data in viewer.metadata.items():
                    prop_type = prop_data["type"]
                    values = prop_data["values"]
                    
                    if prop_type == "number":
                        ds = meta_group.create_dataset(prop_name, data=values, compression="gzip")
                    else:
                        dt_str = h5py.string_dtype(encoding='utf-8')
                        ds = meta_group.create_dataset(prop_name, data=np.array(values, dtype=object), dtype=dt_str, compression="gzip")
                    ds.attrs["type"] = prop_type
                    
            if getattr(viewer, '_cacheable_attrs', None):
                for attr_name in viewer._cacheable_attrs:
                    if hasattr(viewer, attr_name):
                        val = getattr(viewer, attr_name)
                        if val is not None:
                            CORE_DATASETS = {
                                "headers", "positions", "colors", "sizes", "shapes", 
                                "visible_mask", "cluster_labels", "group_labels", "metadata",
                                "connectivity", "edge_scores"
                            }
                            if attr_name in CORE_DATASETS:
                                continue
                                
                            if attr_name in hf:
                                del hf[attr_name]
                                
                            if isinstance(val, np.ndarray):
                                hf.create_dataset(attr_name, data=val, compression="gzip")
                            else:
                                ds = hf.create_dataset(attr_name, data=json.dumps(val))
                                ds.attrs["is_json"] = True
                
            if getattr(viewer, 'last_cluster_params', None) is not None: hf.attrs["last_cluster_params"] = json.dumps(viewer.last_cluster_params)

        os.replace(partial_save_path, final_save_path)
        partial_save_path = None
        Command_Engine.command_artifact(viewer, final_save_path)

        if hasattr(viewer, 'original_pos'):
            viewer.original_pos = viewer.pos.copy()

        msg = f"State successfully saved: {save_name}\n  {final_save_path}"
        Command_Engine.print_help(viewer, msg)
        Command_Engine.command_succeeded(viewer, msg)

    except Exception as e:
        if partial_save_path and os.path.exists(partial_save_path):
            try:
                os.remove(partial_save_path)
            except OSError:
                pass
        msg = f"Error saving layout state: {e}"
        Command_Engine.command_failed(viewer, msg)
        Command_Engine.print_help(viewer, msg)
