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

"""Tests for where the viewer and the VR client meet: finding, starting, talking.

The first classes pin how the viewer finds the installed client and what
command line it starts it with; they need no client. The last runs the real
server loop against the installed player, started the way the viewer starts
it, with the client's ``--selftest``: the player connects, reads the network,
drags it with a scripted grab, and exits 0 once the drag has reached Python and
the viewer's next packet has come back. It is skipped when ``player/`` holds no
client (run ``install_vr.bat``).
"""

import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

OPT_VR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VR_SRC = os.path.join(OPT_VR, "src")
TOOLS = os.path.join(OPT_VR, "tools")
for _path in (TOOLS, VR_SRC):
    if _path not in sys.path:
        sys.path.insert(0, _path)

_NEUTRAL = tempfile.NamedTemporaryFile(
    "w", suffix=".json", delete=False, encoding="utf-8"
)
json.dump({}, _NEUTRAL)
_NEUTRAL.close()
os.environ["SSN_VIEWER_SETTINGS_PATH"] = _NEUTRAL.name

import numpy as np  # noqa: E402

import _bootstrap_vr  # noqa: E402
import Settings_VR as cfg  # noqa: E402

_bootstrap_vr.install_settings_alias(cfg)

with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
    import EMAPSSN_Viewer_VR as vr_viewer  # noqa: E402

import Protocol_V1_VR as protocol  # noqa: E402

INSTALLED_EXE = os.path.join(OPT_VR, "player", "EMAP-SSN-VR.exe")


def client_folder(*names, manifest=None):
    """A throwaway folder holding empty files called `names`."""
    folder = tempfile.mkdtemp()
    for name in names:
        open(os.path.join(folder, name), "w").close()
    if manifest is not None:
        with open(os.path.join(folder, "vr_client.json"), "w", encoding="utf-8") as handle:
            json.dump(manifest, handle)
    return folder


class ConfiguredFolderTestCase(unittest.TestCase):
    def use_folder(self, folder):
        saved = getattr(cfg, "VR_APP_DIR", None)
        cfg.VR_APP_DIR = folder
        self.addCleanup(setattr, cfg, "VR_APP_DIR", saved)
        self.addCleanup(shutil.rmtree, folder, ignore_errors=True)


class FindClientTests(ConfiguredFolderTestCase):
    def test_the_player_is_found_and_the_console_wrapper_skipped(self):
        folder = client_folder("EMAP-SSN-VR.console.exe", "EMAP-SSN-VR.exe", "notes.txt")
        self.use_folder(folder)
        self.assertEqual(vr_viewer.find_vr_app(), os.path.join(folder, "EMAP-SSN-VR.exe"))

    def test_only_the_top_of_the_folder_is_searched(self):
        folder = client_folder()
        os.makedirs(os.path.join(folder, "source"))
        open(os.path.join(folder, "source", "tool.exe"), "w").close()
        self.use_folder(folder)
        with mock.patch.object(vr_viewer, "DEFAULT_PLAYER_DIR", "no_such_player_dir"):
            self.assertIsNone(vr_viewer.find_vr_app())

    def test_a_folder_without_a_client_falls_back_to_player(self):
        self.use_folder(client_folder())
        dirs = vr_viewer.vr_app_search_dirs()
        self.assertEqual(len(dirs), 2)
        self.assertEqual(os.path.normpath(dirs[1]), os.path.join(OPT_VR, "player"))

    def test_the_default_folder_is_searched_once(self):
        saved = getattr(cfg, "VR_APP_DIR", None)
        cfg.VR_APP_DIR = "player"
        self.addCleanup(setattr, cfg, "VR_APP_DIR", saved)
        self.assertEqual(len(vr_viewer.vr_app_search_dirs()), 1)


class LaunchCommandTests(ConfiguredFolderTestCase):
    def test_the_viewer_passes_its_endpoint_after_the_separator(self):
        self.assertEqual(
            vr_viewer.player_command("C:/p/EMAP-SSN-VR.exe", "127.0.0.1", "6123"),
            ["C:/p/EMAP-SSN-VR.exe", "--", "--host", "127.0.0.1", "--port", "6123"],
        )

    def test_a_wildcard_listen_address_is_dialled_on_the_loopback(self):
        for host in ("0.0.0.0", "", " 0.0.0.0 "):
            with self.subTest(host=host):
                self.assertEqual(vr_viewer.player_command("p.exe", host, 5005)[3], "127.0.0.1")

    def test_launch_starts_the_client_in_its_own_folder(self):
        folder = client_folder("EMAP-SSN-VR.exe", manifest={"version": "0.1.0"})
        self.use_folder(folder)
        with mock.patch.object(vr_viewer.subprocess, "Popen") as popen, \
                mock.patch.object(vr_viewer, "warn_about_vr_hardware"), \
                redirect_stdout(io.StringIO()):
            process = vr_viewer.launch_vr_app("127.0.0.1", 6123)
        exe = os.path.join(folder, "EMAP-SSN-VR.exe")
        self.assertIs(process, popen.return_value)
        self.assertEqual(popen.call_args.args[0], [exe, "--", "--host", "127.0.0.1", "--port", "6123"])
        self.assertEqual(popen.call_args.kwargs["cwd"], folder)

    def test_a_missing_client_says_to_run_the_installer(self):
        self.use_folder(client_folder())
        stream = io.StringIO()
        with mock.patch.object(vr_viewer, "DEFAULT_PLAYER_DIR", "no_such_player_dir"), \
                mock.patch.object(vr_viewer.subprocess, "Popen") as popen, \
                redirect_stdout(stream):
            self.assertIsNone(vr_viewer.launch_vr_app("127.0.0.1", 5005))
        popen.assert_not_called()
        self.assertIn("install_vr.bat", stream.getvalue())

    def test_a_stale_client_is_named_but_still_started(self):
        folder = client_folder("EMAP-SSN-VR.exe", manifest={"version": "0.1.0"})
        exe = os.path.join(folder, "EMAP-SSN-VR.exe")
        self.addCleanup(shutil.rmtree, folder, ignore_errors=True)
        pinned = {"version": "0.2.0", "tag": "vr-client-v0.2.0",
                  "asset": "EMAP-SSN-VR-Client-0.2.0-win64.zip", "sha256": "ab" * 32}
        for pin, expected in ((pinned, "0.2.0"), ({**pinned, "version": "0.1.0"}, None)):
            with self.subTest(pinned=pin["version"]), \
                    mock.patch.object(vr_viewer.Player_Build_VR, "read_release_pin", return_value=pin), \
                    mock.patch.object(vr_viewer.CONSOLE, "message") as message:
                self.assertEqual(vr_viewer.warn_about_stale_player(exe), "0.1.0")
                if expected:
                    note = message.call_args.args[0]
                    self.assertIn("0.1.0", note)
                    self.assertIn(expected, note)
                    self.assertIn("install_vr.bat", note)
                else:
                    message.assert_not_called()


@unittest.skipUnless(sys.platform == "win32" and os.path.isfile(INSTALLED_EXE),
                     "no VR client is installed in player/ (run install_vr.bat)")
class InstalledPlayerTests(unittest.TestCase):
    """The installed player against the production server loop."""

    N_NODES = 2000

    def setUp(self):
        saved = getattr(cfg, "EXIT_WITH_UNITY", True)
        cfg.EXIT_WITH_UNITY = False
        self.addCleanup(setattr, cfg, "EXIT_WITH_UNITY", saved)
        console = mock.patch.object(vr_viewer.CONSOLE, "message")
        self.console = console.start()
        self.addCleanup(console.stop)
        interrupt = mock.patch.object(vr_viewer._thread, "interrupt_main")
        interrupt.start()
        self.addCleanup(interrupt.stop)

    def build_viewer(self):
        rng = np.random.default_rng(7)
        headers = [f"sp|P{index:05d}|PROT{index}_TEST" for index in range(self.N_NODES)]
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            viewer = vr_viewer.HeadlessViewer(self.N_NODES, headers, list(headers), {})
        viewer.pos = ((rng.random((self.N_NODES, 3)) - 0.5) * 200.0).astype(np.float32)
        return viewer

    def test_the_selftest_drags_the_network_through_python_and_back(self):
        viewer = self.build_viewer()
        rng = np.random.default_rng(11)
        full = rng.integers(0, self.N_NODES, size=(8000, 2), dtype=np.int32)
        render = full[:3000]
        server = protocol.LoopbackServer(viewer, viewer.pos, render, full)
        self.addCleanup(server.close)

        # Once the client's drag has arrived, send the next packet: it carries
        # the transform back, and it is what the self-test waits for.
        echoed = threading.Event()

        def echo_when_dragged():
            deadline = time.monotonic() + 90
            while time.monotonic() < deadline and not echoed.is_set():
                if abs(float(viewer.transform_position[0]) - 0.5) < 1e-3:
                    viewer.update_nodes()
                    echoed.set()
                    return
                time.sleep(0.02)

        watcher = threading.Thread(target=echo_when_dragged, daemon=True)
        watcher.start()
        self.addCleanup(echoed.set)

        command = vr_viewer.player_command(INSTALLED_EXE, server.host, server.port)
        # Engine options go before the separator: no window, no OpenXR runtime.
        command[1:1] = ["--headless", "--xr-mode", "off"]
        command += ["--selftest", "--timeout", "60"]
        process = subprocess.Popen(command, cwd=os.path.dirname(INSTALLED_EXE),
                                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        try:
            output, _ = process.communicate(timeout=120)
        except subprocess.TimeoutExpired:
            process.kill()
            output, _ = process.communicate()
            self.fail(f"the player did not finish its self-test:\n{output}")

        verdict = [line for line in output.splitlines() if line.startswith("SELFTEST")]
        self.assertEqual(process.returncode, 0, output)
        self.assertTrue(verdict and verdict[-1].startswith("SELFTEST OK"), output)
        self.assertIn(f"nodes={self.N_NODES} render_edges=3000 full_edges=8000", verdict[-1])
        self.assertTrue(echoed.is_set(), "the viewer never received the drag")
        self.assertAlmostEqual(float(viewer.transform_position[0]), 0.5, places=3)
        messages = [call.args[0] for call in self.console.call_args_list if call.args]
        self.assertTrue(any(str(m).startswith("VR client connected from") for m in messages), messages)


if __name__ == "__main__":
    unittest.main()
