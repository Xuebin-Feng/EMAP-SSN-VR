import os
import glob
import re
import numpy as np
from Bio import AlignIO
from Bio.Seq import Seq
from Bio.SeqRecord import SeqRecord
from collections import Counter
import math
import fnmatch
import Settings_VR as cfg

# --- 1. Library Detection ---
try:
    from numba import jit
    NUMBA_AVAILABLE = True
    print("\nNumba JIT Detected: Acceleration Enabled.")
except ImportError:
    NUMBA_AVAILABLE = False
    print("\nNumba not found. Using standard Python (Slower).")

try:
    import torch
    from utilities import Hardware_Utils
    HAS_TORCH = True
except Exception:
    HAS_TORCH = False

# --- 2. String & Label Helpers ---
def get_network_suffix():
    suffix = ""
    
    score_mode = getattr(cfg, 'ALIGNMENT_SCORE', None)
    if score_mode:
        suffix += f"_{score_mode}"
        
    norm_mode = getattr(cfg, 'NORM_MODE', None)
    if norm_mode:
        suffix += f"_{norm_mode}"
        
    if cfg.TOP_EDGE_PERCENT is not None:
        suffix += f"_Top{float(cfg.TOP_EDGE_PERCENT)}Pct"
    else:
        suffix += f"_Score{float(cfg.SIMILARITY_THRESHOLD)}"
    return suffix

def get_base_network_name():
    fasta_path = getattr(cfg, 'NODE_FASTA_FILE', None) or getattr(cfg, 'SEQUENCES_FILE', '')
    if fasta_path and isinstance(fasta_path, str):
        fasta_base = os.path.splitext(os.path.basename(fasta_path))[0]
    else:
        fasta_base = "Network"
        
    hdf5_base = os.path.basename(getattr(cfg, 'INPUT_HDF5', ''))
    hdf5_no_ext = hdf5_base[:-3] if hdf5_base.endswith(".h5") else os.path.splitext(hdf5_base)[0]
    
    cfg.INPUT_IS_EVALUE = "EValue" in hdf5_no_ext or "Evalue" in hdf5_no_ext
    
    stripped = re.sub(r'_(network|evalue)$', '', hdf5_no_ext, flags=re.IGNORECASE)
    match = re.search(r'_(e[0-9]+_.*|blast.*)$', stripped, flags=re.IGNORECASE)
    model_str = f"_{match.group(1)}" if match else ""
    
    return f"{fasta_base}{model_str}"

def get_cache_filename():
    """Return the layout cache this session is bound to.

    opt_vr no longer predicts cache names. The main program owns the naming
    convention - including the ``_3D`` suffix that distinguishes a three
    dimensional layout - so the path is simply whatever was resolved into
    TARGET_CACHE_FILE. The previous implementation re-derived the name from
    settings in a third place, and carried a comment warning that it had to
    "MATCH GUI PREDICTION LOGIC EXACTLY"; that duplication is now gone.
    """
    cache_path = getattr(cfg, "TARGET_CACHE_FILE", None)
    if cache_path and os.path.isdir(cache_path):
        # glob.escape the directory: cache folder names embed the model tag in
        # square brackets (..._[E1_RA]_...), which glob would otherwise read as
        # a character class and never match.
        candidates = sorted(glob.glob(os.path.join(glob.escape(cache_path), "*.h5")))
        if candidates:
            cache_path = candidates[-1]
    reference = getattr(cfg, "ALIGNMENT_REFERENCE", "") or None
    return cache_path, reference


def get_cluster_alignment_dir(viewer):
    """
    Centralized path resolver for the 3 external commands (load.py, label.py, align.py).
    Constructs the standard nested directory path based on current Viewer and Config state.
    """
    if not hasattr(viewer, 'last_cluster_params') or viewer.last_cluster_params is None:
        c_mode_param, c_min = "UNK", "UNK"
    else:
        c_mode_param, c_min = viewer.last_cluster_params

    import re
    hdf5_base = os.path.basename(getattr(cfg, 'INPUT_HDF5', ''))
    
    # --- 1. LEVEL 1: Cache Name until before ALIGNMENT_REFERENCE ---
    fasta_file = getattr(cfg, 'NODE_FASTA_FILE', None)
    if fasta_file:
        fasta_base = os.path.splitext(os.path.basename(fasta_file))[0]
    else:
        fasta_base = getattr(cfg, 'SEQUENCE_SET', 'Network')
        
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
        
    # --- 2. LEVEL 2: Rest of Cache Name + Cluster Parameters ---
    lvl2_name = ""
    
    is_umap = getattr(cfg, 'UMAP_MODE', False)
    if is_umap:
        umap_k = getattr(cfg, 'UMAP_NEIGHBORS', 15)
        lvl2_name += f"_UMAP_k{int(umap_k)}"
    else:
        top_val = getattr(cfg, 'TOP_EDGE_PERCENT', None)
        if top_val is not None and str(top_val).strip() != "None":
            try: lvl2_name += f"Top{float(top_val)}Pct"
            except: pass
        else:
            thresh = getattr(cfg, 'SIMILARITY_THRESHOLD', 0.0)
            try: lvl2_name += f"_Score{float(thresh)}"
            except: pass
        
    # Append the cluster parameters
    lvl2_name += f"_{c_mode_param}_Min{c_min}"

    # Return Full Target Path
    return os.path.join(cfg.CLUSTER_ALIGNMENT_DIR, lvl1_name, lvl2_name)

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

# --- 3. Clustering & Topology Functions ---

def calculate_jaccard_sparse(csr_matrix):
    intersection = csr_matrix.dot(csr_matrix.T)
    row_sums = csr_matrix.getnnz(axis=1)
    return intersection, row_sums

if NUMBA_AVAILABLE:
    @jit(nopython=True)
    def fast_jaccard_filter(edges, indptr, indices, threshold):
        n_edges = edges.shape[0]
        keep_mask = np.zeros(n_edges, dtype=np.bool_)
        for e in range(n_edges):
            u, v = edges[e, 0], edges[e, 1]
            start_u, end_u = indptr[u], indptr[u+1]
            start_v, end_v = indptr[v], indptr[v+1]
            size_u, size_v = end_u - start_u, end_v - start_v
            
            intersection = 0
            ptr_u, ptr_v = start_u, start_v
            while ptr_u < end_u and ptr_v < end_v:
                val_u, val_v = indices[ptr_u], indices[ptr_v]
                if val_u == val_v:
                    intersection += 1; ptr_u += 1; ptr_v += 1
                elif val_u < val_v: ptr_u += 1
                else: ptr_v += 1
            
            union = size_u + size_v - intersection
            if union > 0 and (intersection / union) >= threshold:
                keep_mask[e] = True
        return keep_mask
else:
    def fast_jaccard_filter(edges, indptr, indices, threshold):
        n_edges = edges.shape[0]
        keep_mask = np.zeros(n_edges, dtype=bool)
        for e in range(n_edges):
            u, v = edges[e]
            set_u = set(indices[indptr[u]:indptr[u+1]])
            set_v = set(indices[indptr[v]:indptr[v+1]])
            intersection = len(set_u.intersection(set_v))
            union = len(set_u.union(set_v))
            if union > 0 and (intersection / union) >= threshold:
                keep_mask[e] = True
        return keep_mask


# --- 8. Boolean Logic Engine ---


