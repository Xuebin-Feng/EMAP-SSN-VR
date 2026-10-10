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

"""Tests for the run command (commands/run.py): the commands a .txt command
file holds, or a Python command script prints, reach the VR viewer unchanged.

run.py decodes the script's stdout as UTF-8, so the script must print UTF-8
whatever the viewer's environment says. A piped Python child on Windows writes
the ANSI code page (cp1252) unless PYTHONIOENCODING or PYTHONUTF8 is set, and
nothing in opt_vr sets them: _bootstrap_vr reconfigures only this process's
own streams, not a child's. A .txt file is decoded as Notepad decodes it: by
its byte-order mark, else as UTF-8, else in the ANSI code page. Upstream's
tests/test_run_command.py pins the same rules for the desktop viewer, and the
two that every script obeys: it holds at most 1000 commands, and the first
command that fails ends the run. A Python script runs in its own folder.
"""

import codecs
import os
import subprocess
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

from tests.test_opt_vr import build_viewer, run_command


# 'é' is in the Windows ANSI code page (cp1252) and used to arrive dropped;
# 'α' is not, and the script died with UnicodeEncodeError ('charmap').
# The last line checks that the script still sees the viewer's environment.
NON_ASCII_SCRIPT = """import os
print('select "café"')
print('select "α-amylase"')
print('select "' + os.environ['RUN_SCRIPT_MARKER'] + '"')
"""

# A byte that is not UTF-8 (cp1252 'é'), written past the script's text layer,
# as a process the script starts could write it.
RAW_BYTE_SCRIPT = r"""import sys
sys.stdout.buffer.write(b'select "caf\xe9"\n')
"""

# A command file as Windows editors save it. 'α' is not in cp1252, so only the
# Unicode encodings can hold all of it.
COMMANDS = 'select "café" // déjà vu\r\nselect "α-amylase"\r\n'
EXPECTED = ['select "café"', 'select "α-amylase"']
# Printed when a file falls back to the ANSI code page.
FALLBACK_NOTE = "is not UTF-8"


@contextmanager
def parent_environment(overrides):
    """Patch os.environ with ``overrides``, minus any Python encoding variable they don't set."""
    with mock.patch.dict(os.environ, overrides):
        for name in ("PYTHONIOENCODING", "PYTHONUTF8"):
            if name not in overrides:
                os.environ.pop(name, None)
        yield


class RunFixture:
    """Runs `run` as typed into the VR viewer, on the file at self.script."""

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.script = Path(directory.name) / "commands.py"
        self.viewer = build_viewer()

    def typed(self, quick=False):
        """Run `run` as typed into the VR viewer; return the commands run.py dispatched and what it printed.

        With quick, the commands after `run` are only recorded, as if each succeeded: a long script is fast."""
        command = f"run {self.script}"
        real = self.viewer.process_command

        def process_command(text, *args, **options):
            if quick and text != command:
                return None
            return real(text, *args, **options)

        with mock.patch.object(self.viewer, "process_command", side_effect=process_command) as dispatch:
            output = run_command(self.viewer, command)
        commands = [call.args[0] for call in dispatch.call_args_list]
        self.assertEqual(commands[0], command)
        return commands[1:], output


class FailedLineTests(RunFixture, unittest.TestCase):
    """The first line that fails ends the run, and the batch says which it was."""

    def test_a_failed_line_stops_the_script_and_names_the_line(self):
        for lines, dispatched, message in (
                # No command is named bogus; reset rejects its target.
                (("reset hide", "bogus_command_xyz", "reset colors", "reset sizes"),
                 ["reset hide", "bogus_command_xyz"],
                 "Batch stopped at command 2 of 4: 'bogus_command_xyz' failed. Not run: the remaining 2 commands."),
                (("reset bogus", "reset hide", "bogus"), ["reset bogus"],
                 "Batch stopped at command 1 of 3: 'reset bogus' failed. Not run: the remaining 2 commands."),
                (("reset hide", "bogus_command_xyz", "reset colors"), ["reset hide", "bogus_command_xyz"],
                 "Batch stopped at command 2 of 3: 'bogus_command_xyz' failed. Not run: the remaining 1 command."),
                # The last line leaves nothing out.
                (("reset hide", "bogus_command_xyz"), ["reset hide", "bogus_command_xyz"],
                 "Batch stopped at command 2 of 2: 'bogus_command_xyz' failed."),
                (("bogus_command_xyz",), ["bogus_command_xyz"],
                 "Batch stopped at command 1 of 1: 'bogus_command_xyz' failed.")):
            with self.subTest(lines=lines):
                self.script = self.script.with_suffix(".txt")
                self.script.write_text("\n".join(lines) + "\n", encoding="utf-8")
                commands, output = self.typed()
                # The lines after the failure are not dispatched.
                self.assertEqual(commands, dispatched, output)
                self.assertIn(message, output)
                self.assertNotIn("Batch execution", output)

    def test_comments_and_nested_run_lines_are_not_commands(self):
        self.script = self.script.with_suffix(".txt")
        self.script.write_text(
            "bogus_command_xyz\n# a comment line\nreset hide // trailing note\n", encoding="utf-8"
        )
        commands, output = self.typed()
        self.assertEqual(commands, ["bogus_command_xyz"], output)
        self.assertIn("Batch stopped at command 1 of 2: 'bogus_command_xyz' failed. Not run: the remaining 1 command.", output)

        self.script.write_text("run x.txt\nreset hide\nvr_run x.txt\nRUN x.txt\nbogus_command_xyz\n", encoding="utf-8")
        commands, output = self.typed()
        self.assertEqual(commands, ["reset hide", "bogus_command_xyz"], output)
        self.assertEqual(output.count("Recursive 'run' command in script ignored"), 3, output)
        self.assertIn("Batch stopped at command 2 of 2: 'bogus_command_xyz' failed.", output)

    def test_the_commands_a_python_script_prints_stop_at_the_first_failure_too(self):
        self.script.write_text(
            "print('reset hide')\nprint('bogus_command_xyz')\nprint('reset colors')\n", encoding="utf-8"
        )
        commands, output = self.typed()
        self.assertEqual(commands, ["reset hide", "bogus_command_xyz"], output)
        self.assertIn("Batch stopped at command 2 of 3: 'bogus_command_xyz' failed. Not run: the remaining 1 command.", output)

    def test_a_cancelled_line_stops_the_script_too(self):
        # As a cancelled command ends a request sent through the main program's command portal.
        import Command_Engine

        def process_command(text, *args, **options):
            if text.startswith("run "):
                return real(text, *args, **options)
            (Command_Engine.command_cancelled if text == "cancel" else Command_Engine.command_succeeded)(self.viewer, text)

        real = self.viewer.process_command
        self.script = self.script.with_suffix(".txt")
        self.script.write_text("one\ncancel\nthree\n", encoding="utf-8")
        with mock.patch.object(self.viewer, "process_command", side_effect=process_command) as dispatch:
            output = run_command(self.viewer, f"run {self.script}")
        self.assertEqual([call.args[0] for call in dispatch.call_args_list][1:], ["one", "cancel"])
        self.assertIn("Batch stopped at command 2 of 3: 'cancel' was cancelled. Not run: the remaining 1 command.", output)

    def test_a_clean_script_keeps_the_completed_message(self):
        self.script = self.script.with_suffix(".txt")
        self.script.write_text("reset hide\n", encoding="utf-8")
        commands, output = self.typed()
        self.assertEqual(commands, ["reset hide"], output)
        self.assertIn("Batch execution completed: 1 commands run.", output)
        self.assertNotIn("Batch stopped", output)


class CommandLimitTests(RunFixture, unittest.TestCase):
    """A script holds at most 1000 commands; a longer one is refused before any command runs."""

    def write(self, name, count):
        self.script = self.script.with_name(name)
        # Comment lines and nested run lines are not commands, so they do not count.
        lines = ["# a comment", "run x.txt"] + ['select "one"'] * count
        if name.endswith(".py"):
            self.script.write_text("".join(f"print({line!r})\n" for line in lines), encoding="utf-8")
        else:
            self.script.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def test_scripts_of_1000_commands_run_and_longer_ones_are_refused(self):
        for name in ("commands.txt", "commands.py"):
            for count, message in (
                    (1000, "Batch execution completed: 1000 commands run."),
                    (1001, "Error: The script holds 1001 commands, more than the 1000 a script may run. None were run."),
                    (5000, "Error: The script holds 5000 commands, more than the 1000 a script may run. None were run.")):
                with self.subTest(script=name, commands=count):
                    self.write(name, count)
                    commands, output = self.typed(quick=True)
                    self.assertEqual(len(commands), count if count <= 1000 else 0)
                    self.assertIn(message, output)
                    self.assertEqual("Batch" in output, count <= 1000, output)


class ScriptFolderTests(RunFixture, unittest.TestCase):
    """A Python script runs in its own folder, so a relative path in it names a file beside the script."""

    def test_a_script_runs_in_its_own_folder(self):
        folder = self.script.parent / "scripts"
        folder.mkdir()
        self.script = folder / "commands.py"
        self.assertNotEqual(os.path.realpath(os.getcwd()), os.path.realpath(folder))
        self.script.write_text(
            "import os\n"
            "print('select \"' + os.path.realpath(os.getcwd()) + '\"')\n"
            "open('written_beside_the_script.txt', 'w').close()\n",
            encoding="utf-8",
        )
        with mock.patch("subprocess.run", wraps=subprocess.run) as run:
            commands, output = self.typed()
        self.assertEqual(commands, [f'select "{os.path.realpath(folder)}"'], output)
        self.assertEqual(os.path.realpath(run.call_args.kwargs["cwd"]), os.path.realpath(folder))
        self.assertTrue((folder / "written_beside_the_script.txt").exists())

    def test_a_script_named_by_a_relative_path_still_runs(self):
        # The folder change must not turn the relative path into one that names nothing.
        folder = self.script.parent / "scripts"
        folder.mkdir()
        (folder / "commands.py").write_text(
            "import os\nprint('select \"' + os.path.basename(os.getcwd()) + '\"')\n", encoding="utf-8")
        previous = os.getcwd()
        self.addCleanup(os.chdir, previous)  # Before the temporary folder is removed, so it is not the working folder then.
        os.chdir(self.script.parent)
        output = run_command(self.viewer, f"run {os.path.join('scripts', 'commands.py')}")
        self.assertIn('[Run] Executing: select "scripts"', output)
        self.assertNotIn("Python script failed", output)


class ScriptOutputTests(RunFixture, unittest.TestCase):
    """A script's stdout is decoded as UTF-8, so the script must print UTF-8 whatever the viewer's environment says."""

    def test_non_ascii_commands_arrive_whatever_the_parent_encoding(self):
        self.script.write_text(NON_ASCII_SCRIPT, encoding="utf-8")
        expected = ['select "café"', 'select "α-amylase"', 'select "inherited"']
        for label, overrides in (
                # A piped child's Windows default (the ANSI code page), forced on
                # any platform. Only this case catches a PYTHONUTF8-only fix, or
                # an inherited PYTHONIOENCODING winning over the override.
                ("PYTHONIOENCODING=cp1252", {"PYTHONIOENCODING": "cp1252"}),
                # This platform's own default, which an inherited
                # PYTHONIOENCODING (Claude Code's shells export one) would mask.
                ("no encoding variables", {})):
            with self.subTest(environment=label), \
                    parent_environment({"RUN_SCRIPT_MARKER": "inherited", **overrides}):
                commands, output = self.typed()
                self.assertEqual(commands, expected, output)

    def test_bytes_that_are_not_utf8_stay_visible(self):
        # Dropping the byte would run select "caf", which also matches caffeine.
        self.script.write_text(RAW_BYTE_SCRIPT, encoding="utf-8")
        commands, output = self.typed()
        self.assertEqual(commands, ['select "caf�"'], output)


class CommandFileEncodingTests(RunFixture, unittest.TestCase):
    """A .txt command file is decoded as Notepad decodes it: by its byte-order mark,
    else as UTF-8 when it is UTF-8, else in the system's ANSI code page."""

    def setUp(self):
        super().setUp()
        self.script = self.script.with_name("commands.txt")

    def assert_commands(self, data, expected, code_page="cp1252", note=False):
        """A command file holding ``data`` yields ``expected`` when the ANSI code
        page is ``code_page``, and prints the fallback note only if ``note``."""
        self.script.write_bytes(data)
        # Patched on the locale module itself: process_command reloads commands.run.
        with mock.patch("locale.getencoding", return_value=code_page):
            commands, output = self.typed()
        self.assertEqual(commands, expected, output)
        self.assertEqual(FALLBACK_NOTE in output, note, output)

    def test_a_byte_order_mark_names_the_encoding(self):
        for label, data in (
                # Notepad's "UTF-8 with BOM"; PowerShell 5.1's Set-Content -Encoding UTF8.
                ("UTF-8", codecs.BOM_UTF8 + COMMANDS.encode("utf-8")),
                # PowerShell 5.1's > and Out-File default.
                ("UTF-16 LE", codecs.BOM_UTF16_LE + COMMANDS.encode("utf-16-le")),
                ("UTF-16 BE", codecs.BOM_UTF16_BE + COMMANDS.encode("utf-16-be")),
                # This mark begins with UTF-16 LE's.
                ("UTF-32 LE", codecs.BOM_UTF32_LE + COMMANDS.encode("utf-32-le")),
                ("UTF-32 BE", codecs.BOM_UTF32_BE + COMMANDS.encode("utf-32-be"))):
            with self.subTest(encoding=label):
                self.assert_commands(data, EXPECTED)

    def test_bytes_a_marked_file_cannot_decode_stay_visible(self):
        # Dropping the byte would run select "caf", which also matches caffeine.
        self.assert_commands(codecs.BOM_UTF8 + b'select "caf\xe9"\r\n', ['select "caf�"'])

    def test_utf8_without_a_mark_is_read_as_utf8(self):
        # Notepad's default today. Read as cp1252, 'é' would become 'Ã©'.
        self.assert_commands(COMMANDS.encode("utf-8"), EXPECTED)

    def test_other_files_are_read_in_the_ansi_code_page(self):
        for label, data, code_page, expected in (
                # Older Notepad's and PowerShell 5.1 Set-Content's default on Western Windows.
                ("cp1252", 'select "café" // déjà vu\r\n'.encode("cp1252"), "cp1252", ['select "café"']),
                # The system's own code page, which isn't cp1252 everywhere.
                ("cp1251", 'select "фосфатаза"\r\n'.encode("cp1251"), "cp1251", ['select "фосфатаза"']),
                # Linux and macOS: the locale encoding is UTF-8, so the byte shows as U+FFFD.
                ("UTF-8 locale", 'select "café"\r\n'.encode("cp1252"), "utf-8", ['select "caf�"'])):
            with self.subTest(code_page=label):
                self.assert_commands(data, expected, code_page=code_page, note=True)

    def test_lines_end_at_any_newline(self):
        # As readlines() on a text-mode file splits them.
        self.assert_commands(b'select "a"\rselect "b"\nselect "c"\r\n',
                             ['select "a"', 'select "b"', 'select "c"'])


class NotAScriptFileTests(RunFixture, unittest.TestCase):
    """A name that is not a script file is refused without being opened."""

    def test_a_folder_is_named_as_a_folder(self):
        folder = self.script.parent
        output = run_command(self.viewer, f"run {folder}")
        self.assertIn("is a folder", output)
        self.assertNotIn("Permission denied", output)
        self.assertNotIn("Batch execution", output)

    def test_a_device_name_is_not_opened(self):
        # 'con' would wait on the keyboard and block the viewer; 'NUL' is the
        # same kind of name, and reading it succeeds with no lines, so a
        # regression shows as "Batch execution" rather than as a hang.
        output = run_command(self.viewer, "run NUL")
        self.assertIn("does not exist", output)
        self.assertNotIn("Batch execution", output)


if __name__ == "__main__":
    unittest.main()
