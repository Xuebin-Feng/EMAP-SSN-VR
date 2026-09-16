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

"""Switch the active MSA, matching the desktop viewer's loading rules.

One deliberate difference from upstream: **the file is named on the command
line**. Upstream takes no argument and opens a Qt file dialog on
``viewer.canvas.native``; there is no Qt and no canvas here, so the path is
required. Path resolution is upstream's - absolute, relative to the working
directory, or relative to ``MSA_DIR``, with the ``.fasta``/``.h5`` extension
optional - and so is everything that happens once the file is chosen.

That last part is the substantive fix. This command used to carry its own
loading rules, and they were stricter than the loader's: the help promised
that the viewer's sequences had to be a *strict subset* of the new MSA, and a
failure was re-attempted with the reference dropped. Neither matches the main
program. ``Alignment_Manager`` accepts partial coverage - unmatched nodes stay
visible and sit out alignment-dependent analyses - and it reports how many
nodes aligned. A reference that is absent from the new file is not an error
either; the alignment simply loads in occupancy mode. Both are now reported
the way the desktop viewer reports them, so the same file gives the same
verdict in either front end.
"""

import os

import Settings_VR as cfg
import Command_Engine


def print_help(msa_dir):
    print(f"""
    Alignment Switcher Tool
    =======================
    Usage:
      alignment <filename.fasta / filename.h5>
          Loads the specified MSA file. The path may be absolute, relative to
          the current directory, or relative to the configured MSA directory:
          {msa_dir}
          The .fasta / .h5 extension may be omitted.
      alignment help
          Displays this help message.

    Note:
      The desktop viewer opens a file explorer when 'alignment' is typed alone.
      This viewer is headless, so the file is named on the command line.

    Loading Rules:
      The MSA may contain all, some, or none of the nodes currently plotted in the viewer.
      Missing nodes remain visible but are excluded from alignment-dependent analyses.
      Coverage is matched by exact full headers and reported when the alignment loads.
      Unreadable or malformed files still fail and restore the previous alignment.
    """)


def _resolve(identifier, msa_dir):
    """Upstream's search order: as given, inside MSA_DIR, then with extensions."""
    candidates = [identifier, os.path.join(msa_dir, identifier)]
    for extension in ('.fasta', '.h5'):
        candidates.append(identifier + extension)
        candidates.append(os.path.join(msa_dir, identifier + extension))
    for candidate in candidates:
        if os.path.isfile(candidate):
            return os.path.abspath(candidate).replace("\\", "/")
    return None


def run(viewer, args):
    msa_dir = getattr(cfg, 'MSA_DIR', os.path.join("Input_Files", "Multiple_Alignments"))

    if args and args[0].lower() in ['help', '-h', '--help']:
        print_help(msa_dir)
        if hasattr(viewer, 'console_text'):
            viewer.console_text.text = "Help information printed to the terminal"
        Command_Engine.command_succeeded(viewer, 'Help information printed to the terminal.')
        return

    if not args:
        msg = (
            "Error: Please name the alignment file to load.\n"
            "Usage: alignment <filename.fasta / filename.h5>\n"
            f"The path may be absolute, relative, or relative to {msa_dir}."
        )
        Command_Engine.command_failed(viewer, msg)
        Command_Engine.print_help(viewer, msg)
        return

    identifier = " ".join(args).strip().strip('"')
    new_path = _resolve(identifier, msa_dir)
    if not new_path:
        msg = (
            f"Error: Alignment file '{identifier}' not found "
            f"(checked absolute, relative, and {msa_dir})."
        )
        Command_Engine.command_failed(viewer, msg)
        Command_Engine.print_help(viewer, msg)
        return

    selected_file = os.path.basename(new_path)

    # Load the selected alignment file
    print(f"\nAttempting to load alignment: {selected_file}...")
    if hasattr(viewer, 'console_text'):
        viewer.console_text.text = f"Loading {selected_file}..."

    # Backup current state for safety rollback
    backup_msa_file = cfg.MSA_FILE
    backup_alignment = viewer.alignment
    backup_active_ref = viewer.active_reference

    cfg.MSA_FILE = new_path

    try:
        viewer.load_global_alignment()

        # A parseable partial or zero-overlap MSA is valid. Only a genuine loader
        # failure leaves aln as None and triggers rollback.
        if viewer.alignment is None or viewer.alignment.aln is None:
            raise ValueError("Alignment loader failed to return an alignment.")

        aligned_count = len(getattr(viewer.alignment, 'matched_headers', []))
        total_count = len(getattr(viewer, 'full_headers', []))
        reference_suffix = ""
        if getattr(viewer, 'active_reference', None) and not getattr(
            viewer.alignment,
            'has_reference',
            False,
        ):
            reference_suffix = "; reference inactive (occupancy mode)"

        success_msg = (
            f"Success: Loaded alignment '{selected_file}' "
            f"({aligned_count}/{total_count} network nodes aligned{reference_suffix})."
        )
        print(f"\n{success_msg}")
        if hasattr(viewer, 'console_text'):
            viewer.console_text.text = (
                f"Loaded {selected_file}: {aligned_count}/{total_count} aligned"
            )

        Command_Engine.command_succeeded(viewer, success_msg)

    except Exception as e:
        print(f"\nFailed to load alignment '{selected_file}': {e}")
        Command_Engine.command_failed(viewer, f"\nFailed to load alignment '{selected_file}': {e}")
        print("Reverting to previous alignment state...")

        # Rollback
        cfg.MSA_FILE = backup_msa_file
        viewer.alignment = backup_alignment
        viewer.active_reference = backup_active_ref

        if hasattr(viewer, 'console_text'):
            viewer.console_text.text = "Load failed. Reverted to previous alignment."
            Command_Engine.command_failed(viewer, viewer.console_text.text)
