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

"""Metadata manager, sharing the desktop viewer's implementation.

Upload, download and column deletion are not reimplemented here: they are the
main program's ``Metadata_Core`` functions, called with the same arguments the
desktop ``commands/meta.py`` passes. A spreadsheet uploaded in VR is parsed by
the same code, matched by the same strict full-header rule, and reported with
the same message as one uploaded on the desktop.

That module exists because of this command. The logic had always been Qt-free,
but it sat in ``web_ui/meta_backend.py`` behind a module-level PySide6 import,
so a headless process could not reach it and this command carried its own
parallel implementation - which had drifted into a different set of verbs
(``list``, index-based upload) and a different file format default.

What is not shared, and why:

* **The web spreadsheet UI.** ``meta`` alone opens a browser page on the
  desktop and registers a sidebar button. There is no web server here and the
  web UI is out of scope for this port, so bare ``meta`` prints help instead.

* **The file dialog.** There is none upstream for ``meta`` - paths are already
  typed - so upload resolution is upstream's, unchanged.

* **``show`` / ``display``.** Upstream attaches a HUD that prints the property
  beside the status indicators on node click. The headset has no HUD and no
  click, so the verb is accepted and acknowledged rather than refused:
  ``spectrum`` issues it automatically after every run.

One addition: ``download`` accepts a trailing selection expression.
``Metadata_Core.download_metadata`` has always taken an ``expr`` filter and
evaluates it with the shared selection grammar; the desktop CLI simply never
exposed it, and this command did. Keeping it costs nothing and forks nothing.
"""

import os

import Command_Engine
import Settings_VR as cfg
from Metadata_Core import (
    MetadataColumnDeleteError,
    delete_metadata_columns,
    download_metadata,
    upload_metadata,
)

#: Characters that make a token unambiguously a selection expression rather
#: than a filename. ``classify_selection_expression`` alone would read a bare
#: ``x2`` as an amino-acid predicate, and that is a plausible file name.
_EXPRESSION_MARKERS = '{}#@&|!^"$'


def print_help(meta_dir):
    print(f"""
    Node Metadata Manager
    =====================
    Usage:
      meta <filename> [<filename> ...]
      meta upload/import <filename> [<filename> ...]
          Uploads and merges the specified metadata file(s) (.xlsx, .xls, .csv)
          into the current viewer session. Each path can be absolute, relative,
          or located inside the metadata directory: {meta_dir}
          The extension may be omitted.
      meta download
          Downloads the current session metadata to a generic file (metadata.csv,
          or metadata1.csv if already taken) in {meta_dir}.
      meta download <filename>
          Downloads using the specified filename (defaults to .csv if no
          extension is given). Overwrites the file if it already exists.
      meta download <filename> <expression>
          Downloads only the nodes matching a selection expression, for example
          {{Length>500}}, #cluster_1# or $sele$. The expression comes last.
      meta show/display <property_name>
          Accepted for compatibility with the desktop viewer. The VR viewer has
          no on-canvas HUD, so nothing is displayed.
      meta delete/remove/clear <property_name> [property_name ...]
          Atomically deletes one or more metadata columns from the current
          session. Property matching is case-insensitive. Node ID/Sequence
          Header cannot be deleted; Length is deletable metadata. Deleting
          every column with "all" is not supported.
      meta help
          Displays this help message.

    Note:
      The desktop viewer opens an HTML5 metadata spreadsheet when 'meta' is
      typed alone. This viewer is headless, so that prints this help instead.

    Examples:
      meta my_data.xlsx
      meta download
      meta download my_exported_data
      meta download filtered.csv {{Length>500}}
      meta download cluster_one.csv #cluster_1#
      meta delete Organism Taxonomy
    """)


def _is_expression(token):
    """True when ``token`` is meant as a selection expression, not a filename."""
    if not token or not any(marker in token for marker in _EXPRESSION_MARKERS):
        return False
    classification = Command_Engine.classify_selection_expression(token)
    return (
        classification.kind
        is Command_Engine.SelectionClassificationKind.VALID_EXPRESSION
    )


def _resolve_upload_paths(viewer, tokens, meta_dir):
    """Upstream's search order, per file: as given, in META_DIR, then extensions."""
    file_paths = []
    for token in tokens:
        path = token.strip()
        if os.path.exists(path):
            file_paths.append(os.path.abspath(path))
            continue

        path_in_dir = os.path.join(meta_dir, path)
        if os.path.exists(path_in_dir):
            file_paths.append(os.path.abspath(path_in_dir))
            continue

        found = False
        for ext in ['.xlsx', '.xls', '.csv']:
            if os.path.exists(path + ext):
                file_paths.append(os.path.abspath(path + ext))
                found = True
                break
            elif os.path.exists(os.path.join(meta_dir, path + ext)):
                file_paths.append(os.path.abspath(os.path.join(meta_dir, path + ext)))
                found = True
                break
        if not found:
            msg = (
                f"Error: Metadata file '{path}' not found "
                f"(checked absolute, relative, and {meta_dir})."
            )
            Command_Engine.print_help(viewer, msg)
            Command_Engine.command_failed(viewer, msg)
            return None
    return file_paths


def run(viewer, args):
    meta_dir = getattr(cfg, 'METADATA_DIR', os.path.join("Input_Files", "Meta_Data"))
    os.makedirs(meta_dir, exist_ok=True)

    # Upstream registers the sidebar button for the web spreadsheet here. There
    # is nothing to register without a web server, and the viewer issues this
    # at startup, so it succeeds quietly rather than reporting an error.
    if args and args[0] == '--register-only':
        Command_Engine.command_succeeded(
            viewer, 'No metadata interface to register in the VR viewer.'
        )
        return

    # Upstream opens the spreadsheet in a browser when called alone.
    if not args:
        print_help(meta_dir)
        Command_Engine.command_succeeded(viewer, 'Help information printed to the terminal.')
        return

    first_arg = args[0].lower()

    if first_arg in ['help', '-h', '--help']:
        print_help(meta_dir)
        if hasattr(viewer, 'console_text'):
            viewer.console_text.text = "Help information printed to the terminal"
        Command_Engine.command_succeeded(viewer, 'Help information printed to the terminal.')
        return

    # --- Delete metadata columns ---
    if first_arg in ['delete', 'remove', 'clear']:
        if len(args) < 2:
            Command_Engine.command_failed(viewer, "Missing metadata command arguments")
            Command_Engine.print_help(
                viewer,
                f"Usage: meta {first_arg} <property_name> [property_name ...]",
            )
            return
        try:
            deleted = delete_metadata_columns(viewer, args[1:], broadcast=False)
        except MetadataColumnDeleteError as error:
            Command_Engine.print_help(viewer, f"Error: {error}")
            Command_Engine.command_failed(viewer, f'Error: {error}')
            return
        msg = "Deleted metadata columns: " + ", ".join(deleted) + "."
        Command_Engine.print_help(viewer, msg)
        Command_Engine.command_succeeded(viewer, msg)
        return

    # --- Display / show: accepted, but there is no HUD to show it on ---
    if first_arg in ['display', 'show']:
        target = " ".join(args[1:]).strip()
        if not target:
            Command_Engine.command_failed(viewer, "Missing metadata command arguments")
            Command_Engine.print_help(
                viewer, "Usage: meta show <property_name> OR meta show clear/off"
            )
            return
        if target.lower() in ('clear', 'off'):
            msg = "Metadata display is not used in the VR viewer; nothing to clear."
        else:
            msg = (
                f"Noted '{target}' for metadata display. The VR viewer has no "
                "on-canvas HUD to show it on - the headset renders the network "
                "and the terminal is the only text surface - so nothing changes "
                "here. Use 'meta download <file>' to take the property out, or "
                "open the layout in the desktop viewer to see it on node click."
            )
        Command_Engine.print_help(viewer, msg)
        Command_Engine.command_succeeded(viewer, msg)
        return

    # --- Download ---
    if first_arg in ['download', 'retrieve', 'export']:
        rest = list(args[1:])
        expr = None
        if rest and _is_expression(rest[-1]):
            expr = rest[-1]
            rest = rest[:-1]

        filename = " ".join(rest).strip()
        if filename:
            _, ext = os.path.splitext(filename)
            if not ext:
                filename += ".csv"
            filepath = os.path.join(meta_dir, filename)
        else:
            base_name = "metadata"
            ext = ".csv"
            candidate = f"{base_name}{ext}"
            filepath = os.path.join(meta_dir, candidate)
            counter = 1
            while os.path.exists(filepath):
                candidate = f"{base_name}{counter}{ext}"
                filepath = os.path.join(meta_dir, candidate)
                counter += 1
            filepath = os.path.abspath(filepath)

        download_metadata(viewer, filepath, expr)
        return

    # --- Upload (the first argument is a filename unless it named a verb) ---
    upload_args = list(args)
    if first_arg in ['upload', 'import']:
        upload_args = args[1:]
        if not upload_args:
            msg = "Error: Please specify a file path or filename to upload."
            Command_Engine.print_help(viewer, msg)
            Command_Engine.command_failed(viewer, msg)
            return

    file_paths = _resolve_upload_paths(viewer, upload_args, meta_dir)
    if file_paths is None:
        return

    upload_metadata(viewer, file_paths)
