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

"""Tests for the VR viewer's lifecycle: one instance, and following Unity out.

Two viewers cannot usefully coexist - they drive the same Unity client through
an endpoint compiled into its build - so the second one has to refuse rather
than race the first for the port. And because the viewer exists to serve the
headset, it follows the client out by default, with a control to keep it alive
for debugging.
"""

import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from types import SimpleNamespace
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
import Single_Instance_VR as single_instance  # noqa: E402

_bootstrap_vr.install_settings_alias(cfg)

with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
    import EMAPSSN_Viewer_VR as viewer  # noqa: E402

#: A name of this test's own, so a real viewer running beside the suite is
#: neither disturbed by it nor able to fail it.
TEST_MUTEX = "Local\\EMAP-SSN-VR-Viewer-TestSuite"

WINDOWS_ONLY = unittest.skipUnless(
    sys.platform == "win32", "the instance lock is a Windows named mutex"
)


class SingleInstanceTests(unittest.TestCase):
    @WINDOWS_ONLY
    def test_the_first_caller_wins_and_the_second_is_refused(self):
        first = single_instance.acquire(TEST_MUTEX)
        self.addCleanup(single_instance.release, first)
        self.assertIsNotNone(first)
        self.assertIsNone(
            single_instance.acquire(TEST_MUTEX),
            "a second viewer must not be able to claim the headset",
        )

    @WINDOWS_ONLY
    def test_releasing_lets_the_next_viewer_start(self):
        first = single_instance.acquire(TEST_MUTEX)
        single_instance.release(first)
        second = single_instance.acquire(TEST_MUTEX)
        self.addCleanup(single_instance.release, second)
        self.assertIsNotNone(second)

    def test_releasing_nothing_is_harmless(self):
        single_instance.release(None)

    def test_the_refusal_says_what_to_do(self):
        message = single_instance.BUSY_MESSAGE
        self.assertIn("already running", message)
        self.assertIn("Close the other viewer", message)

    def test_the_lock_is_session_local(self):
        # A machine-wide name would make two desktop sessions on one host fight
        # over a headset neither of them shares.
        self.assertTrue(single_instance.MUTEX_NAME.startswith("Local\\"))

    @WINDOWS_ONLY
    def test_a_second_viewer_exits_before_loading_anything(self):
        """The refusal must not cost a minute of reading HDF5 first."""
        held = single_instance.acquire()
        self.addCleanup(single_instance.release, held)
        self.assertIsNotNone(held, "a real VR viewer is running; cannot test this")

        result = subprocess.run(
            [sys.executable, os.path.join(VR_SRC, "EMAPSSN_Viewer_VR.py")],
            capture_output=True,
            text=True,
            cwd=OPT_VR,
            timeout=300,
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("already running", result.stdout + result.stderr)
        self.assertNotIn("Loading layout cache", result.stdout)


class ExitWithUnityTests(unittest.TestCase):
    def setUp(self):
        self._saved = getattr(cfg, "EXIT_WITH_UNITY", None)
        self.addCleanup(setattr, cfg, "EXIT_WITH_UNITY", self._saved)

    def test_the_viewer_follows_unity_out_by_default(self):
        self.assertIs(cfg.VR_DEFAULTS["EXIT_WITH_UNITY"], True)
        del cfg.EXIT_WITH_UNITY
        self.addCleanup(setattr, cfg, "EXIT_WITH_UNITY", self._saved)
        self.assertTrue(
            viewer.should_exit_with_unity(),
            "an absent setting must not leave an orphan holding the port",
        )

    def test_the_control_can_keep_the_console_alive(self):
        cfg.EXIT_WITH_UNITY = False
        self.assertFalse(viewer.should_exit_with_unity())

    def test_the_setting_survives_a_json_round_trip(self):
        for written, expected in (("False", False), ("True", True), (False, False)):
            with self.subTest(written=written):
                self.assertIs(cfg._coerce("EXIT_WITH_UNITY", written), expected)

    def test_disconnect_keeps_listening_only_when_quit_is_off(self):
        import queue
        import socket
        import numpy as np

        for quit_with_unity in (False, True):
            with self.subTest(quit_with_unity=quit_with_unity):
                cfg.EXIT_WITH_UNITY = quit_with_unity
                client, peer = socket.socketpair()
                self.addCleanup(client.close)
                self.addCleanup(peer.close)
                # A real EOF from the peer drives client_reader_loop and the
                # production server's disconnect path, without a Unity app.
                peer.shutdown(socket.SHUT_WR)
                state = SimpleNamespace(
                    running=True, is_connected=False,
                    current_colors=np.ones((1, 4)), current_sizes=np.ones(1),
                    visible_mask=np.ones(1, dtype=bool),
                    get_global_settings=lambda: {}, get_transform_state=lambda: {},
                    update_queue=queue.Queue(),
                )
                listener = mock.Mock()
                listener.accept.side_effect = [
                    (client, ("local", 1)), OSError("test listener stopped")
                ]
                with mock.patch.object(viewer._thread, "interrupt_main") as interrupt, mock.patch.object(viewer.CONSOLE, "message"):
                    empty_edges = np.empty((0, 2), dtype=np.int32)
                    viewer.unity_server_loop(
                        listener, state, np.zeros((1, 3)), empty_edges, 1, 0, empty_edges
                    )
                self.assertEqual(state.running, not quit_with_unity)
                self.assertEqual(interrupt.call_count, int(quit_with_unity))
                self.assertEqual(listener.accept.call_count, 1 if quit_with_unity else 2)


class PortOwnershipTests(unittest.TestCase):
    """A clash on the endpoint is an error, not a silent takeover."""

    @staticmethod
    def viewer_source():
        import pathlib

        return pathlib.Path(VR_SRC, "EMAPSSN_Viewer_VR.py").read_text(encoding="utf-8")

    def test_the_listener_does_not_ask_to_share_its_port(self):
        source = self.viewer_source()
        listener = source[source.index("server_socket = socket.socket") :]
        listener = listener[: listener.index("server_socket.listen")]
        # Comments are stripped first: this block explains SO_REUSEADDR in
        # order to say why it is not used, and a plain search finds the
        # explanation rather than a call.
        code = "\n".join(
            line for line in listener.splitlines() if not line.strip().startswith("#")
        )
        # On Windows SO_REUSEADDR lets an unrelated process bind a port this
        # one is already serving and take the connections with it.
        self.assertNotIn("SO_REUSEADDR", code)
        self.assertIn("SO_EXCLUSIVEADDRUSE", code)

    def test_a_busy_port_is_explained(self):
        source = self.viewer_source()
        self.assertIn("Could not listen on", source)
        self.assertIn("rebuild the client to match", source)


if __name__ == "__main__":
    unittest.main()
