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

"""List the available commands, or describe one.

The terminal banner has always told users to type ``help``, but no such
command existed, so it printed "Unknown command: help".

Descriptions are read from the main program's ``desktop/Command_Metadata.py``
rather than duplicated here, so VR help text cannot drift from the desktop
viewer's. That module is descriptive only and imports no handlers and no Qt.
"""

import ast
import os

import Command_Engine

try:
    from desktop.Command_Metadata import COMMAND_METADATA, get_command_metadata
except Exception:  # pragma: no cover - only if the parent checkout is broken
    COMMAND_METADATA = {}

    def get_command_metadata(name):
        raise KeyError(name)


def _available_commands():
    """Every importable command, and whether VR overrides it.

    ``commands.__path__`` holds this package's directory followed by the main
    program's ``src/commands``, so the same search order the dispatcher uses is
    reproduced here.
    """
    import commands

    local_dir = os.path.dirname(os.path.abspath(__file__))
    found = {}
    for entry in commands.__path__:
        try:
            names = sorted(os.listdir(entry))
        except OSError:
            continue
        is_local = os.path.abspath(entry) == local_dir
        for filename in names:
            if not filename.endswith(".py") or filename.startswith("_"):
                continue
            name = filename[:-3]
            # First path entry wins, matching import resolution.
            found.setdefault(name, is_local)
    return found


#: Fallback for VR-only commands whose module has no docstring to read.
LOCAL_SUMMARIES = {
    "help": "List the available commands, or describe one.",
}


def _local_docstring(name):
    """First line of a local command module's docstring, read without importing.

    Parsing the source keeps `help` cheap and side-effect free: listing every
    command must not execute any of them.
    """
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), f"{name}.py")
    try:
        with open(path, encoding="utf-8") as handle:
            tree = ast.parse(handle.read())
    except (OSError, SyntaxError, ValueError):
        return ""
    doc = ast.get_docstring(tree)
    if not doc:
        return ""
    first = doc.strip().splitlines()[0].strip()
    return first


def _summary(name, is_local=False):
    """Describe a command, preferring the local override's own words.

    A VR command that shadows an upstream one usually does something
    different - `agent` and `esmfold` explain they are desktop-only, `print`
    writes a file instead of rendering a canvas - so showing the upstream
    one-liner for them would actively mislead.
    """
    if is_local:
        local = _local_docstring(name) or LOCAL_SUMMARIES.get(name)
        if local:
            return local
    try:
        return get_command_metadata(name)["summary"]
    except Exception:
        return LOCAL_SUMMARIES.get(name, "")


def _describe(name, is_local=False):
    lines = [f"{name}"]
    if is_local:
        # A local override's own docstring beats upstream's description, which
        # may describe behaviour this command deliberately does not have.
        local = _local_docstring(name) or LOCAL_SUMMARIES.get(name)
        if local:
            lines.append(f"  {local}")
            lines.append("")
            lines.append("  (VR-specific implementation)")
            return "\n".join(lines)
    try:
        metadata = get_command_metadata(name)
    except Exception:
        local = LOCAL_SUMMARIES.get(name)
        lines.append(f"  {local}" if local else "  (no description available)")
        return "\n".join(lines)

    lines.append(f"  {metadata['summary']}")
    arguments = metadata.get("arguments") or []
    if arguments:
        lines.append("")
        lines.append("  Arguments:")
        for item in arguments:
            lines.append(f"    {item['name']}")
            lines.append(f"      {item['description']}")
            choices = item.get("choices") or []
            if choices:
                rendered = []
                for choice in choices:
                    aliases = choice.get("aliases") or []
                    rendered.append(
                        choice["value"] + (f" ({', '.join(aliases)})" if aliases else "")
                    )
                lines.append(f"      Choices: {', '.join(rendered)}")
    return "\n".join(lines)


def run(viewer, args):
    if args:
        name = args[0].lower().lstrip("-")
        if name.startswith("vr_"):
            name = name[3:]
        available = _available_commands()
        if name not in available and name not in COMMAND_METADATA:
            Command_Engine.print_help(
                viewer, f"Unknown command: {name}. Type 'help' for the full list."
            )
            return
        Command_Engine.print_help(
            viewer, _describe(name, available.get(name, False))
        )
        return

    available = _available_commands()
    if not available:
        Command_Engine.print_help(viewer, "No commands were found.")
        return

    width = max(len(name) for name in available)
    lines = [
        "EMAP-SSN VR viewer commands",
        "",
        "  Type 'help <command>' for arguments and options.",
        "",
    ]
    for name in sorted(available):
        marker = " " if available[name] else "*"
        summary = _summary(name, available[name])
        lines.append(f"  {marker} {name.ljust(width)}  {summary}")

    lines.append("")
    lines.append(
        "  * = provided by the main EMAP-SSN program; not VR-specific, and may "
        "behave differently"
    )
    lines.append("    outside a desktop viewer.")
    Command_Engine.print_help(viewer, "\n".join(lines))
