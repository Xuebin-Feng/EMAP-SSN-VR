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

"""The test modules and the tools leave nothing in the user's temporary folder.

Each used to make a "neutral settings" file (``tmpXXXXXXXX.json`` holding ``{}``)
when it was imported, and never deleted it, so every full run left about ten of
them behind, with the scripts and folders of a few tests. Each case here runs one
of them in a process whose temporary folder is a new empty one, and expects that
folder to be empty afterwards.
"""

import os
import subprocess
import sys
import tempfile
import unittest

OPT_VR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

IMPORT_TOOL = (
    "import sys; sys.path[:0] = [{src!r}, {tools!r}]; import {module}"
)


class TemporaryFolderTests(unittest.TestCase):
    def leftovers_of(self, arguments):
        """What running ``python <arguments>`` leaves in a temporary folder of its own."""
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as scratch:
            environment = {**os.environ, "TEMP": scratch, "TMP": scratch, "TMPDIR": scratch}
            result = subprocess.run(
                [sys.executable, *arguments], cwd=OPT_VR, env=environment,
                capture_output=True, text=True, timeout=600,
            )
            leftovers = sorted(os.listdir(scratch))
        self.assertEqual(result.returncode, 0, result.stdout[-1500:] + result.stderr[-1500:])
        return leftovers

    def test_test_modules_leave_nothing(self):
        # One module that makes the neutral settings file, one that writes throwaway
        # scripts, one that builds throwaway folders, and (on Windows) one whose GUI
        # scripts make their fixture folders.
        targets = ["tests.test_protocol_v1", "tests.test_command_compatibility", "tests.test_player_build"]
        if sys.platform == "win32":
            targets.append("tests.test_vr_config.VRAtomicWriteTests")
        for target in targets:
            with self.subTest(target=target):
                self.assertEqual(self.leftovers_of(["-m", "unittest", target]), [])

    def test_tools_leave_nothing(self):
        for module in ("Protocol_Fixtures_VR", "Synthetic_Server_VR"):
            with self.subTest(module=module):
                code = IMPORT_TOOL.format(
                    src=os.path.join(OPT_VR, "src"), tools=os.path.join(OPT_VR, "tools"), module=module
                )
                self.assertEqual(self.leftovers_of(["-c", code]), [])


if __name__ == "__main__":
    unittest.main()
