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

"""Qt-free settings for the VR viewer.

The schema for every shared key comes from ``src/desktop/Viewer_State.py``;
this module layers ``opt_vr/vr_settings.json`` on top of those defaults and
adds the handful of keys only the VR bridge needs.

The division of labour is deliberate: **opt_vr's Config GUI writes settings,
the VR runtime only reads them.** Nothing here imports PySide6, so the viewer
process stays headless. The two front ends are configured independently - the
VR side never reads or writes the desktop program's ``viewer_settings.json``,
and every relative path resolves inside the submodule.

Values are exposed as module attributes so existing ``cfg.NODE_SIZE`` style
access keeps working unchanged.
"""

from __future__ import annotations

import ast
import json
import os
import re
import sys

import _bootstrap
from desktop.Viewer_State import ALIASES, DEFAULTS, decode_document

#: Upstream renamed some keys; the VR code and the Unity client still use the
#: older spellings, so read the current key and publish it under both names.
LEGACY_KEY_SOURCES = {
    "NEIGHBOR_COLOR": "INITIAL_NODE_COLOR",
}

#: Keys whose upstream default is ``None``, so their type cannot be inferred.
_NULLABLE_NUMBERS = ("SIMILARITY_THRESHOLD", "TOP_EDGE_PERCENT")

_NULL_TOKENS = {"", "none", "null"}

PROJECT_ROOT = _bootstrap.PROJECT_ROOT
OPT_VR_DIR = _bootstrap.OPT_VR_DIR

#: Keys with no upstream counterpart. Everything else comes from DEFAULTS.
VR_DEFAULTS = {
    # --- Unity bridge -------------------------------------------------
    "VR_HOST": "127.0.0.1",
    "VR_PORT": 5005,
    "VR_APP_DIR": "VR_App",
    "DISTANCE_SCALE": 1.0,
    # --- Edge rendering budget ---------------------------------------
    "ENABLE_EDGE_FILTERING": True,
    "MAX_RENDER_EDGES": 500000,
    # --- Visual keys the Unity client reads from globalSettings -------
    "NEIGHBOR_COLOR": "#4488ff",
    # --- Alignment ----------------------------------------------------
    "GAP_CHARS": ["-", "."],
    # --- Directories without an upstream profile entry ----------------
    "HISTORY_DIR": os.path.join("$cache_file$", "History"),
    "LOGO_DIR": os.path.join("$analysis_result$", "Sequence_Logos"),
    "CLUSTER_ALIGNMENT_DIR": os.path.join("$analysis_result$", "Cluster_Alignments"),
    "CLUSTER_LABEL_DIR": os.path.join("$analysis_result$", "Cluster_Labels"),
    # --- Layout ---------------------------------------------------------
    # The VR viewer is three dimensional by definition, so this is not a
    # user choice: it is a property of which viewer was launched. The
    # desktop program has no such setting and is always two dimensional.
    "LAYOUT_DIMENSIONS": 3,
    # --- Runtime state, resolved at load ------------------------------
    "TARGET_CACHE_FILE": None,
    "SEQUENCE_SET": None,
    "INPUT_IS_EVALUE": False,
}

_DIRECTORY_SUFFIX = "_DIR"

#: File-valued settings that are stored with an alias and/or relative.
_PATH_KEYS = ("NODE_FASTA_FILE", "INPUT_HDF5", "MSA_FILE", "TARGET_CACHE_PATH")


def _settings_path() -> str:
    """The VR settings file, which lives inside the submodule.

    opt_vr is configured by its own GUI and does not read the desktop
    program's ``viewer_settings.json``: the two front ends are configured
    independently, so a VR session can never disturb a desktop one. The
    environment override is how the VR Config GUI hands a per-launch snapshot
    to the viewer.
    """
    override = os.environ.get("SSN_VIEWER_SETTINGS_PATH")
    if override:
        return override
    return os.path.join(OPT_VR_DIR, "vr_settings.json")


def _read_json(path):
    if not path or not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as handle:
            stored = json.load(handle)
    except (OSError, ValueError) as error:
        print(f"[Settings] Ignoring unreadable settings at {path}: {error}")
        return {}
    if not isinstance(stored, dict):
        return {}
    # The Config GUI hands each launch a private snapshot written with
    # encode_document() - sectioned, not a flat mapping - and points
    # SSN_VIEWER_SETTINGS_PATH at it. Decode that shape so the VR viewer
    # consumes the GUI's handoff exactly as the desktop viewer does.
    if stored.get("schema_version") is not None:
        try:
            return decode_document(stored, "viewer", partial=True)
        except ValueError as error:
            print(f"[Settings] Ignoring unreadable settings document at {path}: {error}")
            return {}
    return stored


def _resolve_alias(value, values, seen=()):
    """Expand ``$input_file$`` style directory aliases, as the GUI does."""
    if not isinstance(value, str) or not value.strip():
        return value
    for alias, alias_key in ALIASES.items():
        if value == alias or value.startswith((alias + "/", alias + "\\")):
            if alias_key in seen:
                raise ValueError(f"Circular directory alias: {alias_key}")
            base = _resolve_alias(
                values.get(alias_key, alias_key), values, (*seen, alias_key)
            )
            return os.path.join(base, value[len(alias):].lstrip("/\\"))
    return value


def _absolute(value, base=None):
    if not isinstance(value, str) or not value.strip():
        return value
    if os.path.isabs(value):
        return value
    return os.path.join(base or PROJECT_ROOT, value)


def resolve_directory_path(value, base_directories=None):
    """Expand one exact leading directory alias without changing other paths.

    Shared commands hold their output directory as a literal - ``logo.py`` uses
    ``"$analysis_result$/Sequence_Logos"`` - and call this to turn it into a
    real path. The contract mirrors ``EMAPSSN_Config.resolve_directory_path``
    exactly, because the same command source runs against both: only a leading
    alias is expanded, and anything else is handed back untouched.

    The alias table is ``Viewer_State.ALIASES``, which is the same mapping the
    desktop config publishes as ``DIRECTORY_PATH_ALIASES``.
    """
    if value is None:
        return value
    raw_path = os.fspath(value)
    bases = base_directories or {}
    for alias, setting_key in ALIASES.items():
        if raw_path == alias:
            suffix = ""
        elif (
            raw_path.startswith(alias)
            and raw_path[len(alias):len(alias) + 1] in {"/", "\\"}
        ):
            suffix = raw_path[len(alias):].lstrip("/\\")
        else:
            continue

        base_path = os.fspath(bases.get(setting_key, globals().get(setting_key, "")))
        if not suffix:
            return os.path.normpath(base_path)
        parts = [part for part in re.split(r"[/\\]+", suffix) if part]
        return os.path.normpath(os.path.join(base_path, *parts))
    return raw_path


def _coerce(key, value):
    """Coerce a stored value to the type of its upstream default.

    viewer_settings.json round-trips through Qt widgets, so numbers and
    booleans routinely arrive as strings ("15", "None", "5.0"). The desktop
    Config GUI fixes this in apply_viewer_settings by coercing against the
    type of the existing module global; the same rule is applied here against
    Viewer_State.DEFAULTS so both front ends agree on every value.
    """
    if key in _NULLABLE_NUMBERS:
        if value is None or (
            isinstance(value, str) and value.strip().lower() in _NULL_TOKENS
        ):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return value

    reference = DEFAULTS.get(key)
    if reference is None or value is None:
        return value
    if isinstance(value, str) and not value.strip() and not isinstance(reference, str):
        return value

    if isinstance(reference, bool):
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in ("true", "1", "t", "y", "yes")
    if isinstance(reference, int):
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return value
    if isinstance(reference, float):
        try:
            return float(value)
        except (TypeError, ValueError):
            return value
    if isinstance(reference, list):
        if isinstance(value, str):
            try:
                return ast.literal_eval(value)
            except (ValueError, SyntaxError):
                return value
    return value


def load_settings() -> dict:
    """Merge shared defaults, viewer_settings.json and VR-only overrides."""
    values = dict(DEFAULTS)
    values.update(VR_DEFAULTS)

    # One file only. Reading vr_settings.json again after this would override
    # the per-launch snapshot the VR Config GUI hands the viewer, which is
    # exactly the choice the user just made in the GUI.
    for key, value in _read_json(_settings_path()).items():
        values[key] = _coerce(key, value)

    # Publish renamed upstream keys under the spellings the VR code uses.
    for legacy, current in LEGACY_KEY_SOURCES.items():
        if current in values and values[current] not in (None, ""):
            values[legacy] = values[current]

    # Aliases appear on file keys as well as directory keys - INPUT_HDF5,
    # MSA_FILE and NODE_FASTA_FILE are all stored as "$input_file$/...", so
    # resolving only *_DIR would leave those paths literally containing the
    # alias token.
    for key, value in list(values.items()):
        if isinstance(value, str) and value.startswith(tuple(ALIASES)):
            values[key] = _resolve_alias(value, values)

    # Relative paths resolve inside the submodule. opt_vr keeps its own inputs,
    # caches and analysis outputs, so a VR configuration never writes into the
    # desktop program's directories.
    for key, value in list(values.items()):
        if key.endswith(_DIRECTORY_SUFFIX) or key in _PATH_KEYS:
            values[key] = _absolute(values[key], OPT_VR_DIR)

    # The launcher pins one cache folder for this session.
    target = os.environ.get("SSN_TARGET_CACHE") or values.get("TARGET_CACHE_PATH")
    if target:
        target = _absolute(_resolve_alias(target, values))
    values["TARGET_CACHE_FILE"] = target or None

    # Legacy alias retained so existing VR command modules keep working.
    values["SEQUENCES_FILE"] = values.get("NODE_FASTA_FILE")
    return values


def reload() -> dict:
    """Re-read settings from disk and refresh this module's attributes."""
    values = load_settings()
    globals().update(values)
    return values


reload()

# Register the alias here, not at the call site. Upstream modules do
# `import EMAPSSN_Config as cfg`, and if the real one loads first it drags
# PySide6 into this headless process. Doing it on import of this module means
# merely importing Settings is enough, so no caller has to get the order right.
_bootstrap.install_settings_alias(sys.modules[__name__])
