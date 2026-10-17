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

"""Switch the active embedding, matching the desktop viewer's loading rules.

One deliberate difference from upstream, the one `alignment` has too: **the
file is named on the command line**. Upstream takes no argument and opens a Qt
file dialog on ``viewer.canvas.native``; there is no Qt and no canvas here, so
the path is required. Path resolution is upstream's - absolute, relative to the
working directory, or relative to ``EMBED_DIR``, with the ``.h5`` extension
optional - and so is everything that happens once the file is chosen: the
file is loaded through ``viewer.load_embedding()`` (the main program's
Embedding_Manager), a file the manager refuses is rolled back, and a partial or
zero-overlap embedding is accepted and reported. The coverage, the model, the
width and the saving mode, and the note for a network built with another
model, come from ``Embedding_Manager.describe``, so both viewers say the same.
"""

import os

import Settings_VR as cfg
import Command_Engine


def print_help(embed_dir):
    print(f"""
    Embedding Switcher Tool
    =======================
    Usage:
      embedding <filename.h5>
          Loads the specified embedding file. The path may be absolute, relative to
          the current directory, or relative to the configured embedding directory:
          {embed_dir}
          The .h5 extension may be omitted.
      embedding help
          Displays this help message.

    Note:
      The desktop viewer opens a file explorer when 'embedding' is typed alone.
      This viewer is headless, so the file is named on the command line.

    Loading Rules:
      The embedding may contain all, some, or none of the nodes currently plotted in the viewer.
      Missing nodes remain visible but are excluded from embedding-dependent analyses.
      Coverage is matched by exact full headers and identical sequences, and is reported when the embedding loads.
      Unreadable, malformed or incomplete files still fail and restore the previous embedding.
      The switch lasts for this session and is not an undo step; the saved settings are unchanged.
    """)


def _resolve(identifier, embed_dir):
    """Upstream's search order: as given, inside EMBED_DIR, then with the extension."""
    candidates = [identifier, os.path.join(embed_dir, identifier)]
    candidates.append(identifier + '.h5')
    candidates.append(os.path.join(embed_dir, identifier + '.h5'))
    for candidate in candidates:
        if os.path.isfile(candidate):
            return os.path.abspath(candidate).replace("\\", "/")
    return None


def run(viewer, args):
    embed_dir = getattr(cfg, 'EMBED_DIR', "Embeddings")

    if args and args[0].lower() in ['help', '-h', '--help']:
        print_help(embed_dir)
        if hasattr(viewer, 'console_text'):
            viewer.console_text.text = "Help information printed to the terminal"
        Command_Engine.command_succeeded(viewer, 'Help information printed to the terminal.')
        return

    if not args:
        msg = (
            "Error: Please name the embedding file to load.\n"
            "Usage: embedding <filename.h5>\n"
            f"The path may be absolute, relative, or relative to {embed_dir}."
        )
        Command_Engine.command_failed(viewer, msg)
        Command_Engine.print_help(viewer, msg)
        return

    identifier = " ".join(args).strip()
    # A quoted path, such as one with spaces, keeps its quotes in args.
    if len(identifier) >= 2 and identifier[0] == identifier[-1] and identifier[0] in "\"'":
        identifier = identifier[1:-1]
    new_path = _resolve(identifier, embed_dir)
    if not new_path:
        msg = (
            f"Error: Embedding file '{identifier}' not found "
            f"(checked absolute, relative, and {embed_dir})."
        )
        Command_Engine.command_failed(viewer, msg)
        Command_Engine.print_help(viewer, msg)
        return

    selected_file = os.path.basename(new_path)

    # Load the selected embedding file
    print(f"\nAttempting to load embedding: {selected_file}...")
    if hasattr(viewer, 'console_text'):
        viewer.console_text.text = f"Loading {selected_file}..."

    # Backup current state for safety rollback
    backup_embed_file = cfg.EMBED_FILE
    backup_embedding = getattr(viewer, 'embedding', None)

    cfg.EMBED_FILE = new_path
    reason = None

    try:
        viewer.load_embedding()

        # A parseable partial or zero-overlap embedding is valid. Only a file the
        # manager refuses leaves it without a source and triggers rollback. The
        # manager says why on the object it leaves behind; when the viewer could
        # not even build one, load_embedding leaves None.
        embedding = viewer.embedding
        if embedding is None or getattr(embedding, 'source', None) is None:
            reason = getattr(embedding, 'load_failure', None)
            raise ValueError(
                "Embedding loader failed to return an embedding." if reason is None else str(reason)
            )

        embedded_count = len(getattr(embedding, 'matched_headers', []))
        total_count = len(getattr(viewer, 'full_headers', []))
        details = [str(part) for part in embedding.describe(getattr(cfg, 'INPUT_HDF5', ''))]

        success_msg = (
            f"Success: Loaded embedding '{selected_file}' "
            f"({embedded_count}/{total_count} network nodes embedded)."
        )
        print(f"\n{success_msg}")
        for detail in details:
            print(detail)
        if hasattr(viewer, 'console_text'):
            viewer.console_text.text = " ".join(
                [f"Loaded {selected_file}: {embedded_count}/{total_count} embedded.", *details]
            )

        Command_Engine.command_succeeded(viewer, " ".join([success_msg, *details]))

    except Exception as e:
        print(f"\nFailed to load embedding '{selected_file}': {e}")
        print("Reverting to previous embedding state...")

        # Rollback
        cfg.EMBED_FILE = backup_embed_file
        viewer.embedding = backup_embedding

        if hasattr(viewer, 'console_text'):
            viewer.console_text.text = "Load failed. Reverted to previous embedding."
        Command_Engine.command_failed(
            viewer, f"Failed to load embedding '{selected_file}': {e}\nReverted to previous embedding."
        )
