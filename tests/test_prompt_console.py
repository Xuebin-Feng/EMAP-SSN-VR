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

"""Tests for keeping Unity's background messages off the command prompt.

The Unity server thread prints while the main thread is sitting on "> " with a
possibly half-typed command. Printed straight to stdout, the message lands
after the prompt, so the prompt scrolls away and the cursor is left on a bare
line - which reads as a terminal that has stopped accepting input.

What these pin is the repair: the prompt is erased before the message and
redrawn after it, the typed characters survive, and the terminal loop never
writes to stdout behind the console's back.
"""

import io
import json
import os
import pathlib
import sys
import tempfile
import threading
import unittest
from contextlib import redirect_stderr, redirect_stdout

OPT_VR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VR_SRC = os.path.join(OPT_VR, "src")
if VR_SRC not in sys.path:
    sys.path.insert(0, VR_SRC)

_NEUTRAL = tempfile.NamedTemporaryFile(
    "w", suffix=".json", delete=False, encoding="utf-8"
)
json.dump({}, _NEUTRAL)
_NEUTRAL.close()
os.environ["SSN_VIEWER_SETTINGS_PATH"] = _NEUTRAL.name

import _bootstrap_vr  # noqa: E402
import Settings_VR as cfg  # noqa: E402

_bootstrap_vr.install_settings_alias(cfg)

with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
    import EMAPSSN_Viewer_VR as viewer  # noqa: E402


def console():
    stream = io.StringIO()
    return viewer.PromptConsole(stream), stream


class MessageAroundPromptTests(unittest.TestCase):
    def test_a_message_erases_the_prompt_and_puts_it_back(self):
        terminal, stream = console()
        typed = []
        terminal.show_prompt("> ", typed)
        terminal.message("Unity connected from ('127.0.0.1', 52546)")

        self.assertEqual(
            stream.getvalue(),
            "> " + "\r  \r" + "Unity connected from ('127.0.0.1', 52546)\n" + "> ",
        )

    def test_a_half_typed_command_survives_the_message(self):
        """Losing what was typed would be a worse cure than the disease."""
        terminal, stream = console()
        typed = []
        terminal.show_prompt("> ", typed)
        for character in "colo":
            typed.append(character)
            terminal.echo(character)
        terminal.message("Unity connected")

        rendered = stream.getvalue()
        self.assertTrue(rendered.endswith("> colo"))
        # Six columns erased: two of prompt, four of command.
        self.assertIn("\r" + " " * 6 + "\r", rendered)

    def test_the_prompt_is_not_redrawn_once_the_line_is_finished(self):
        # Between Enter and the next prompt the terminal is printing command
        # output; a redraw there would interleave with it.
        terminal, stream = console()
        terminal.show_prompt("> ", [])
        terminal.end_prompt()
        stream.truncate(0)
        stream.seek(0)
        terminal.message("Unity client disconnected")
        self.assertEqual(stream.getvalue(), "Unity client disconnected\n")

    def test_a_message_before_any_prompt_is_printed_plainly(self):
        terminal, stream = console()
        terminal.message("Server listening on 127.0.0.1:5005")
        self.assertEqual(stream.getvalue(), "Server listening on 127.0.0.1:5005\n")

    def test_trailing_newlines_do_not_stack_up(self):
        terminal, stream = console()
        terminal.message("done\n")
        self.assertEqual(stream.getvalue(), "done\n")

    def test_multi_line_messages_keep_their_own_breaks(self):
        terminal, stream = console()
        terminal.message("first\nsecond")
        self.assertEqual(stream.getvalue(), "first\nsecond\n")


class ConcurrencyTests(unittest.TestCase):
    def test_keystrokes_and_messages_do_not_interleave(self):
        """A message must not land between the prompt and its echoed keys."""

        class SlowStream(io.StringIO):
            """Widen the window in which a write could be interrupted."""

            def write(self, text):
                result = super().write(text)
                if text and not text.startswith("\r"):
                    threading.Event().wait(0.001)
                return result

        stream = SlowStream()
        terminal = viewer.PromptConsole(stream)
        typed = []
        terminal.show_prompt("> ", typed)

        def type_command():
            for character in "spectrum":
                typed.append(character)
                terminal.echo(character)

        def announce():
            for index in range(8):
                terminal.message(f"message {index}")

        threads = [
            threading.Thread(target=type_command),
            threading.Thread(target=announce),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        rendered = stream.getvalue()
        # Whatever the ordering, every message owns a whole line and the final
        # thing on screen is the prompt with everything that was typed.
        for index in range(8):
            self.assertIn(f"message {index}\n", rendered)
        self.assertTrue(rendered.endswith("> spectrum"))


class TerminalLoopTests(unittest.TestCase):
    """The loop must not write to stdout behind the console's back."""

    @staticmethod
    def loop_source():
        source = pathlib.Path(VR_SRC, "EMAPSSN_Viewer_VR.py").read_text(
            encoding="utf-8"
        )
        start = source.index("def terminal_loop(")
        return source[start : source.index("\ndef ", start + 1)]

    def test_the_loop_writes_only_through_the_console(self):
        self.assertNotIn("sys.stdout.write", self.loop_source())

    def test_history_recall_keeps_the_list_the_console_holds(self):
        # Rebinding cmd_chars would leave the console redrawing a stale line.
        source = self.loop_source()
        self.assertNotIn("cmd_chars = list(new_cmd)", source)
        self.assertIn("cmd_chars[:] = list(new_cmd)", source)

    def test_the_background_threads_report_through_the_console(self):
        source = pathlib.Path(VR_SRC, "EMAPSSN_Viewer_VR.py").read_text(
            encoding="utf-8"
        )
        for name in ("client_reader_loop", "unity_server_loop"):
            with self.subTest(thread=name):
                start = source.index(f"def {name}(")
                body = source[start : source.index("\ndef ", start + 1)]
                self.assertNotIn("print(", body)
                self.assertIn("CONSOLE.message(", body)


if __name__ == "__main__":
    unittest.main()
