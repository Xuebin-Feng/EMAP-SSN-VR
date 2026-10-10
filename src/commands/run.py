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

Three deliberate differences from upstream, all forced by the environment:

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

* **A ``.py`` script runs in the foreground.** The desktop viewer runs it on a
  background thread so its GUI stays responsive, and hands the output back on
  the GUI thread. Here a command runs on the terminal loop's own thread, and the
  VR client is served by other threads, so waiting for the script blocks
  nothing but the prompt, as every other command does. Nothing needs handing
  back, and the commands it printed run once it has ended.

Everything else is shared with the desktop viewer, rule for rule: a script runs
in its own folder, holds at most 1000 commands, and ends at the first command
that fails.
"""

import codecs
import io
import locale
import os

import Command_Engine
from Viewer_Command_Portal import MAX_SCRIPT_COMMANDS

USAGE = (
    "Usage: run <script_path>\n"
    "Description: Executes a list of commands in sequence from a text file or a "
    "Python script.\n"
    "  - For .txt files: Executes each line as a command.\n"
    "  - For .py files: Executes the Python script in a subprocess, in the "
    "script's own folder, and runs the commands outputted to stdout.\n"
    "  - The first command that fails stops the run; the commands after it are "
    "not run.\n"
    f"  - A script may hold at most {MAX_SCRIPT_COMMANDS} commands; a longer one "
    "is refused before any command runs.\n"
    "Note: The desktop viewer opens a file dialog here. This viewer is headless, "
    "so name the script on the command line.\n"
    "Example:\n"
    "  run my_script.txt"
)

# A byte-order mark names a .txt file's encoding. UTF-32 LE's mark begins with
# UTF-16 LE's, so the UTF-32 marks are checked first.
BYTE_ORDER_MARKS = (
    (codecs.BOM_UTF32_LE, 'utf-32'), (codecs.BOM_UTF32_BE, 'utf-32'),
    (codecs.BOM_UTF8, 'utf-8-sig'),
    (codecs.BOM_UTF16_LE, 'utf-16'), (codecs.BOM_UTF16_BE, 'utf-16'),
)


def read_command_lines(file_path):
    """Lines of a .txt command file, decoded the way Notepad decodes it.

    A byte-order mark names the encoding. A file without one is UTF-8 if it
    decodes as UTF-8, and otherwise in the system's legacy encoding: the ANSI
    code page on Windows, older Notepad's and PowerShell 5.1 Set-Content's
    default. Bytes that still don't decode show as U+FFFD; dropping them would
    turn select "café" into select "caf", which also matches caffeine.
    """
    with open(file_path, 'rb') as f:
        data = f.read()
    encoding = next((name for mark, name in BYTE_ORDER_MARKS if data.startswith(mark)), None)
    if encoding is None:
        try:
            data.decode('utf-8')
            encoding = 'utf-8'
        except UnicodeDecodeError:
            encoding = locale.getencoding()
            print(f"[Run] {file_path} is not UTF-8; reading it as {encoding}, "
                  "with U+FFFD for any byte that doesn't decode.")
    # Universal newlines, as readlines() on a text-mode file splits them.
    return io.StringIO(data.decode(encoding, errors='replace'), newline=None).readlines()


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
    # isfile, not exists: a folder or a Windows device name such as 'con' exists
    # too, and opening 'con' would wait on the keyboard and block the viewer.
    joined_path = ' '.join(args).strip().strip('"')
    file_path = joined_path if os.path.isfile(joined_path) else args[0]

    if os.path.isdir(file_path):
        msg = f"Error: '{file_path}' is a folder. Name a script file inside it."
        Command_Engine.command_failed(viewer, msg)
        Command_Engine.print_help(viewer, msg)
        return

    if not os.path.isfile(file_path):
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

            # Execute python script in a subprocess using the current python executable.
            # Its output is decoded as UTF-8, so the child must print UTF-8; a piped
            # child otherwise uses the Windows ANSI code page. Bad bytes show as U+FFFD.
            # It runs in its own folder, so a relative path in it names a file beside
            # the script, wherever the viewer was started. The path is made absolute
            # first, as the folder change would otherwise move a relative one.
            script_path = os.path.abspath(file_path)
            # No stdin: a script calling input() would otherwise wait on the
            # VR terminal's own stdin, and the terminal with it.
            result = subprocess.run(
                [sys.executable, script_path],
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='replace',
                env={**os.environ, 'PYTHONIOENCODING': 'utf-8'},
                cwd=os.path.dirname(script_path),
            )

            if result.returncode != 0:
                stderr_output = result.stderr.strip()
                msg = f"Error: Python script failed (exit code {result.returncode}):\n{stderr_output}"
                Command_Engine.command_failed(viewer, msg)
                Command_Engine.print_help(viewer, msg)
                return

            commands_lines = result.stdout.splitlines()
        else:
            commands_lines = read_command_lines(file_path)

        # The commands the script holds: blank lines, # lines, trailing // comments and
        # nested run lines are left out, as upstream leaves them out.
        commands = []
        for line in commands_lines:
            cmd_line = Command_Engine.script_command(line)
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
            commands.append(cmd_line)

        total = len(commands)
        if total > MAX_SCRIPT_COMMANDS:
            msg = (f"Error: The script holds {total} commands, more than the "
                   f"{MAX_SCRIPT_COMMANDS} a script may run. None were run.")
            Command_Engine.command_failed(viewer, msg)
            Command_Engine.print_help(viewer, msg, report_message=False)
            return

        # Execute the commands in sequence, up to the first one that fails.
        for index, cmd_line in enumerate(commands, 1):
            print(f"[Run] Executing: {cmd_line}")
            # Upstream calls Command_Engine._dispatch_user_command here, which
            # is the desktop viewer's own inner dispatch. The VR viewer owns
            # dispatch instead, and going through it keeps the 'vr_' prefix and
            # the module-reload behaviour identical to a typed command.
            # A command failed whether it reported the failure or the dispatch
            # itself failed; one cancelled ends the run too, as upstream's does.
            with Command_Engine.recorded_outcome() as outcome:
                dispatched = viewer.process_command(cmd_line, record_history=False)
            if dispatched is False or outcome['status'] in ('failed', 'cancelled'):
                cancelled = outcome['status'] == 'cancelled'
                remaining = total - index
                msg = (f"Batch stopped at command {index} of {total}: '{cmd_line}' "
                       f"{'was cancelled' if cancelled else 'failed'}.")
                if remaining:
                    msg += f" Not run: the remaining {remaining} command{'s' if remaining != 1 else ''}."
                if cancelled:
                    Command_Engine.command_cancelled(viewer, msg)
                else:
                    Command_Engine.command_failed(viewer, msg)
                Command_Engine.print_help(viewer, msg, report_message=False)
                return

        msg = f"Batch execution completed: {total} commands run."
        Command_Engine.print_help(viewer, msg)

    except Exception as e:
        msg = f"Error reading/executing command file: {e}"
        Command_Engine.command_failed(viewer, msg)
        Command_Engine.print_help(viewer, msg)
        return
    Command_Engine.command_succeeded(viewer, msg)
