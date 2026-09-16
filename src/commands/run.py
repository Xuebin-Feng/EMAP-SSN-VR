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

"""Run a command script, matching the desktop viewer everywhere it can.

Two deliberate differences from upstream, both forced by the environment:

* **The script is named on the command line.** Upstream takes no argument and
  opens a Qt file dialog on ``viewer.canvas.native``. There is no Qt and no
  canvas in this process, so the path is an argument instead. Everything after
  the file is chosen - comment stripping, the recursion guard, ``.py`` handling
  and every message - follows upstream exactly.

* **No agent hand-off.** Upstream checks ``Viewer_Command_Portal.CURRENT`` and,
  inside a model-driven request, hands a ``.py`` script to ``ScriptTracker`` or
  a ``.txt`` script to ``context.children()`` rather than running it inline.
  Nothing in the VR process ever binds that context - the portal here is a set
  of no-op shims, and ``agent`` is a stub that explains the web UI is
  desktop-only - so those branches would be unreachable code referencing a
  context type this process never constructs. They belong back here on the day
  an agent does drive the VR viewer, not before.
"""

import os

import Command_Engine

USAGE = (
    "Usage: run <script_path>\n"
    "Description: Executes a list of commands in sequence from a text file or a "
    "Python script.\n"
    "  - For .txt files: Executes each line as a command.\n"
    "  - For .py files: Executes the Python script in a subprocess and runs the "
    "commands outputted to stdout.\n"
    "Note: The desktop viewer opens a file dialog here. This viewer is headless, "
    "so name the script on the command line.\n"
    "Example:\n"
    "  run my_script.txt"
)


def run(viewer, args):
    if args and args[0].lower() in ['help', '-h', '--help']:
        Command_Engine.print_help(viewer, USAGE, report_message=False)
        Command_Engine.command_succeeded(viewer, 'Help information printed to the terminal.')
        return

    if not args:
        msg = "Error: Please name the script to run.\n" + USAGE
        Command_Engine.command_failed(viewer, msg)
        Command_Engine.print_help(viewer, msg)
        return

    # The command line is whitespace-split before it reaches us, so a Windows
    # path containing spaces arrives as several args. Rejoin them (and drop any
    # surrounding quotes) when that spelling names a real file.
    joined_path = ' '.join(args).strip().strip('"')
    file_path = joined_path if os.path.exists(joined_path) else args[0]

    if not os.path.exists(file_path):
        msg = f"Error: File '{file_path}' does not exist."
        Command_Engine.command_failed(viewer, msg)
        Command_Engine.print_help(viewer, msg)
        return

    # Read/execute the file and extract commands
    try:
        commands_lines = []
        _, ext = os.path.splitext(file_path)

        if ext.lower() == '.py':
            import subprocess
            import sys

            print(f"[Run] Executing Python script: {file_path}")

            # Execute python script in a subprocess using the current python executable
            result = subprocess.run(
                [sys.executable, file_path],
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='ignore'
            )

            if result.returncode != 0:
                stderr_output = result.stderr.strip()
                msg = f"Error: Python script failed (exit code {result.returncode}):\n{stderr_output}"
                Command_Engine.command_failed(viewer, msg)
                Command_Engine.print_help(viewer, msg)
                return

            commands_lines = result.stdout.splitlines()
        else:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                commands_lines = f.readlines()

        # Execute the commands in sequence
        executed_count = 0
        for line in commands_lines:
            # Split by // to remove any trailing comment
            cmd_line = line.split('//')[0].strip()
            if not cmd_line:
                continue

            parts = cmd_line.split()
            if not parts:
                continue

            command_name = parts[0].lower()
            # Viewer.process_command strips a 'vr_' prefix before dispatching,
            # so 'vr_run' has to be caught here too or the guard is bypassed
            # and a self-referencing script recurses until RecursionError.
            if command_name.startswith('vr_'):
                command_name = command_name[3:]
            if command_name == 'run':
                print("Warning: Recursive 'run' command in script ignored to prevent infinite loop.")
                continue

            print(f"[Run] Executing: {cmd_line}")
            # Upstream calls Command_Engine._dispatch_user_command here, which
            # is the desktop viewer's own inner dispatch. The VR viewer owns
            # dispatch instead, and going through it keeps the 'vr_' prefix and
            # the module-reload behaviour identical to a typed command.
            viewer.process_command(cmd_line, record_history=False)
            executed_count += 1

        msg = f"Batch execution completed: {executed_count} commands run."
        Command_Engine.print_help(viewer, msg)

    except Exception as e:
        msg = f"Error reading/executing command file: {e}"
        Command_Engine.command_failed(viewer, msg)
        Command_Engine.print_help(viewer, msg)
        return
    Command_Engine.command_succeeded(viewer, msg)
