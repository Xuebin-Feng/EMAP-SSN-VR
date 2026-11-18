# Copyright 2026 Xuebin Feng
# Author affiliation: University of Toronto
# SPDX-License-Identifier: Apache-2.0

"""A viewer a VR test builds keeps its command history outside the project.

The viewer appends every command it is given to a history file in the history
folder, and with default settings that folder is Cache_Files_VR at the project
root. The test modules load neutral settings (tests/neutral_settings.py) that
move the cache folder into a temporary directory, so running them leaves the
user's checkout as it was. Each case here builds a viewer the way one test
module does and checks where its history file is.
"""

import io
import os
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from types import SimpleNamespace

OPT_VR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VR_SRC = os.path.join(OPT_VR, "src")
if VR_SRC not in sys.path:
    sys.path.insert(0, VR_SRC)

from tests.neutral_settings import install as _install_neutral_settings  # noqa: E402

_NEUTRAL = _install_neutral_settings(only_if_unset=True)  # removed when this process exits

import _bootstrap_vr  # noqa: E402
import Settings_VR as cfg  # noqa: E402

from tests import test_command_behaviour, test_opt_vr, test_player_integration, test_protocol_v1  # noqa: E402


def inside(path, folder):
    """Whether `path` is `folder` or lies under it, compared as the platform does."""
    path = os.path.normcase(os.path.realpath(path))
    folder = os.path.normcase(os.path.realpath(folder))
    try:
        return os.path.commonpath([path, folder]) == folder
    except ValueError:  # another drive
        return False


class HistoryOutsideTheProjectTests(unittest.TestCase):
    def check(self, viewer):
        project = _bootstrap_vr.PROJECT_ROOT
        self.assertFalse(inside(viewer.history_file, project), viewer.history_file)
        self.assertFalse(inside(cfg.HISTORY_DIR, project), cfg.HISTORY_DIR)

    def test_the_history_folder_is_in_a_temporary_folder(self):
        self.assertFalse(inside(cfg.HISTORY_DIR, _bootstrap_vr.PROJECT_ROOT), cfg.HISTORY_DIR)
        self.assertFalse(inside(cfg.CACHE_FILE_DIR, _bootstrap_vr.PROJECT_ROOT), cfg.CACHE_FILE_DIR)

    def test_the_shared_builder(self):
        self.check(test_opt_vr.build_viewer())

    def test_the_aligned_builder(self):
        self.check(test_command_behaviour.aligned_viewer())

    def test_the_protocol_builder(self):
        self.check(test_protocol_v1.build_viewer(6))

    def test_the_player_builder(self):
        stand_in = SimpleNamespace(N_NODES=6)
        self.check(test_player_integration.InstalledPlayerTests.build_viewer(stand_in))

    def test_a_viewer_built_in_the_test_body(self):
        headers = ["a", "b", "c"]
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            viewer = test_opt_vr.vr_viewer.HeadlessViewer(3, headers, list(headers), {})
        self.check(viewer)


if __name__ == "__main__":
    unittest.main()
