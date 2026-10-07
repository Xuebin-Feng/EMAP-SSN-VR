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

"""Tests for the run command (commands/run.py): the commands a Python command
script prints reach the VR viewer unchanged.

run.py decodes the script's stdout as UTF-8, so the script must print UTF-8
whatever the viewer's environment says. A piped Python child on Windows writes
the ANSI code page (cp1252) unless PYTHONIOENCODING or PYTHONUTF8 is set, and
nothing in opt_vr sets them: _bootstrap_vr reconfigures only this process's
own streams, not a child's. Upstream's tests/test_run_command.py pins the same
rule for the desktop viewer.
"""

import os
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


@contextmanager
def parent_environment(overrides):
    """Patch os.environ with ``overrides``, minus any Python encoding variable they don't set."""
    with mock.patch.dict(os.environ, overrides):
        for name in ("PYTHONIOENCODING", "PYTHONUTF8"):
            if name not in overrides:
                os.environ.pop(name, None)
        yield


class ScriptOutputTests(unittest.TestCase):
    """A script's stdout is decoded as UTF-8, so the script must print UTF-8 whatever the viewer's environment says."""

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.script = Path(directory.name) / "commands.py"
        self.viewer = build_viewer()

    def typed(self):
        """Run `run` as typed into the VR viewer; return the commands run.py dispatched and what it printed."""
        command = f"run {self.script}"
        with mock.patch.object(
            self.viewer, "process_command", wraps=self.viewer.process_command
        ) as dispatch:
            output = run_command(self.viewer, command)
        commands = [call.args[0] for call in dispatch.call_args_list]
        self.assertEqual(commands[0], command)
        return commands[1:], output

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


if __name__ == "__main__":
    unittest.main()
