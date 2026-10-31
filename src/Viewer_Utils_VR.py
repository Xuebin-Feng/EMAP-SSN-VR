# Copyright 2026 Xuebin Feng
# Author affiliation: University of Toronto
# SPDX-License-Identifier: Apache-2.0

import os
import glob
import re
import Settings_VR as cfg

# --- 2. String & Label Helpers ---
def get_cache_filename():
    """Return the layout cache this session is bound to.

    opt_vr no longer predicts cache names. The main program owns the naming
    convention - including the ``_3D`` suffix that distinguishes a three
    dimensional layout - so the path is simply whatever was resolved into
    TARGET_CACHE_FILE. The previous implementation re-derived the name from
    settings in a third place, and carried a comment warning that it had to
    "MATCH GUI PREDICTION LOGIC EXACTLY"; that duplication is now gone.

    Only the path is returned. The alignment reference plays no part in cache
    selection; the main program's resolve_selected_cache dropped it for the
    same reason.
    """
    cache_path = getattr(cfg, "TARGET_CACHE_FILE", None)
    if cache_path and os.path.isdir(cache_path):
        # glob.escape the directory: cache folder names embed the model tag in
        # square brackets (..._[E1_RA]_...), which glob would otherwise read as
        # a character class and never match.
        candidates = sorted(glob.glob(os.path.join(glob.escape(cache_path), "*.h5")))
        if candidates:
            cache_path = candidates[-1]
    return cache_path


def simplify_node_label(header):
    # 1. Try to match standard NCBI Accession formats
    # - RefSeq: 2 letters, underscore, numbers, optional version (e.g., WP_012345678.1, NP_123456)
    # - GenBank: 3 letters, 5 to 7 numbers, optional version (e.g., AAA12345.1, EAW123456)
    match = re.search(r'\b([A-Z]{2}_\d+(?:\.\d+)?|[A-Z]{3}\d{5,7}(?:\.\d+)?)\b', header)
    if match:
        return match.group(1)
        
    # 2. Legacy fallback for old |gb| flags
    marker = "|gb|"
    if marker in header:
        try: return header.split(marker)[1].split("|")[0]
        except IndexError: pass
        
    # 3. Ultimate fallback: Return the first word (Standard FASTA ID format)
    return header.split()[0] if header else ""

def sort_labels(labels):
    def key_func(k):
        try:
            # Split the label by the decimal point
            parts = str(k).split('.')
            major = int(parts[0])
            # If there's a decimal, grab the integer after it. Otherwise, it's 0.
            minor = int(parts[1]) if len(parts) > 1 else 0
            
            # Return a tuple for sorting (e.g., (188, 10) vs (188, 6))
            return (major, minor)
        except:
            return (0, 0)
            
    return sorted(labels, key=key_func)

def hex_to_rgba(hex_code):
    # Imported lazily, as upstream Command_Engine does. A module-level import
    # put matplotlib on the critical path of every command that touches this
    # file, so a headless viewer could not load `save` or `select` without a
    # plotting stack it never uses.
    import matplotlib.colors as mcolors

    return mcolors.to_rgba(hex_code)


# --- 8. Boolean Logic Engine ---


