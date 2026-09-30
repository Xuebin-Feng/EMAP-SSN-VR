# Copyright 2026 Xuebin Feng
# Author affiliation: University of Toronto
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Genuine layout cache folders for the VR viewer's tests.

The VR viewer checks a cache against the files it was built from, exactly as
the desktop viewer does, so a test cache needs everything the layout generator
publishes: a FASTA, an alignment network, the folder manifest built from both
files, and a cache whose provenance and node order match them.
"""

import hashlib
import json
import os
import sys
from types import SimpleNamespace
from unittest import mock

OPT_VR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VR_SRC = os.path.join(OPT_VR, "src")
if VR_SRC not in sys.path:
    sys.path.insert(0, VR_SRC)

import h5py  # noqa: E402
import numpy as np  # noqa: E402

import _bootstrap_vr  # noqa: E402,F401  (puts the main program's src/ on sys.path)
import Settings_VR as cfg  # noqa: E402
import Cache_Manifest  # noqa: E402
from utilities.Sequence_Utils import load_sanitized_fasta  # noqa: E402

#: Settings the viewer adopts from a cache, or that prepare_network writes.
ADOPTED_SETTINGS = (
    "ALIGNMENT_SCORE",
    "NORM_MODE",
    "UMAP_MODE",
    "UMAP_NEIGHBORS",
    "UMAP_MIN_DIST",
    "BOX_SCALE",
    "SIMILARITY_THRESHOLD",
    "TOP_EDGE_PERCENT",
    "INPUT_IS_EVALUE",
)

SEQUENCE = "MKTAYIAKQRQISFVKSHFSRQLEERLGLIEVQ"
DEFAULT_HEADERS = tuple(f"sp|P{index:05d}|PROT{index}_TEST" for index in range(5))


def write_inputs(folder, raw_headers):
    """Write a FASTA with `raw_headers` and an alignment network joining every pair.

    The network carries the sanitised headers, as the pipeline writes them. Pair
    (a, b) scores 0.1 * (a + b) per aligned residue, so a threshold keeps a
    predictable subset: 0.45 keeps the four pairs whose indices sum to 5 or more
    among five nodes. Returns the two paths and the canonical headers.
    """
    os.makedirs(folder, exist_ok=True)
    fasta = os.path.join(folder, "set.fasta")
    with open(fasta, "w", encoding="utf-8", newline="\n") as handle:
        for index, header in enumerate(raw_headers):
            handle.write(f">{header}\n{SEQUENCE[: 10 + index]}\n")
    headers, sequences, _ = load_sanitized_fasta(fasta, report=False)

    pairs = [(a, b) for a in range(len(headers)) for b in range(a + 1, len(headers))]
    network = os.path.join(folder, "network.h5")
    with h5py.File(network, "w") as handle:
        handle.attrs["model_name"] = "test_model"
        handle.create_dataset(
            "headers",
            data=np.asarray(headers, dtype=object),
            dtype=h5py.string_dtype(encoding="utf-8"),
        )
        handle.create_dataset(
            "seq_lens", data=np.asarray([len(seq) for seq in sequences], dtype=np.uint16)
        )
        handle.create_dataset("i", data=np.asarray([a for a, _ in pairs], dtype=np.uint16))
        handle.create_dataset("j", data=np.asarray([b for _, b in pairs], dtype=np.uint16))
        scores = np.asarray([a + b for a, b in pairs], dtype=np.float32)
        lengths = np.full(len(pairs), 10, dtype=np.uint16)
        for name in ("g_score", "l_score"):
            handle.create_dataset(name, data=scores)
        for name in ("g_len", "l_len"):
            handle.create_dataset(name, data=lengths)
    return fasta, network, list(headers)


def publish_cache(
    root,
    *,
    dimensions=3,
    raw_headers=DEFAULT_HEADERS,
    similarity_threshold=0.45,
    top_edge_percent=None,
    umap_neighbors=None,
    folder_name=None,
):
    """Publish a cache folder the way the layout generator does.

    Returns its FASTA, network, folder, cache path, manifest ID and canonical
    headers. A top-edge percentage or a UMAP neighbour count replaces the
    similarity threshold, as it does in the generator.
    """
    fasta, network, headers = write_inputs(os.path.join(root, "inputs"), raw_headers)
    umap_mode = umap_neighbors is not None
    if umap_mode or top_edge_percent is not None:
        similarity_threshold = None
    neighbours = umap_neighbors if umap_mode else 15
    manifest = Cache_Manifest.build_manifest_for_files(
        fasta,
        network,
        alignment_score="global",
        normalization="alignment_length",
        umap_mode=umap_mode,
        umap_neighbors=neighbours,
        top_edge_percent=top_edge_percent,
        similarity_threshold=similarity_threshold,
        layout_dimensions=dimensions,
    )
    folder = os.path.join(root, folder_name or ("Network_3D" if dimensions == 3 else "Network"))
    Cache_Manifest.write_manifest_atomic(folder, manifest)

    parameters = json.dumps(
        {
            "UMAP_MODE": umap_mode,
            "UMAP_NEIGHBORS": neighbours,
            "UMAP_MIN_DIST": 0.1,
            "BOX_SCALE": 2.0,
            "SIMILARITY_THRESHOLD": similarity_threshold,
            "LAYOUT_DIMENSIONS": dimensions,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    path = os.path.join(folder, "version_00.h5")
    with h5py.File(path, "w") as handle:
        handle.attrs["cache_manifest_id"] = manifest["manifest_id"]
        handle.attrs["layout_compatibility_json"] = parameters
        handle.attrs["layout_compatibility_id"] = hashlib.sha256(
            parameters.encode("utf-8")
        ).hexdigest()
        handle.attrs["layout_dimensions"] = dimensions
        handle.create_dataset(
            "headers",
            data=np.asarray(headers, dtype=object),
            dtype=h5py.string_dtype(encoding="utf-8"),
        )
        handle.create_dataset(
            "positions",
            data=np.arange(len(headers) * dimensions, dtype=np.float32).reshape(-1, dimensions),
        )
    return SimpleNamespace(
        fasta=fasta,
        network=network,
        folder=folder,
        path=path,
        manifest_id=manifest["manifest_id"],
        headers=headers,
    )


def use_inputs(test, cache):
    """Point the settings at `cache` for the rest of `test`, as Save & Run does.

    Every setting the viewer adopts from a cache is patched as well, so one
    test's cache settings never leak into the next test.
    """
    values = {name: getattr(cfg, name, None) for name in ADOPTED_SETTINGS}
    values.update(
        NODE_FASTA_FILE=cache.fasta,
        SEQUENCES_FILE=cache.fasta,
        INPUT_HDF5=cache.network,
        TARGET_CACHE_FILE=cache.path,
        TARGET_CACHE_PATH=None,
    )
    for name, value in values.items():
        patcher = mock.patch.object(cfg, name, value, create=True)
        patcher.start()
        test.addCleanup(patcher.stop)
