# Copyright 2026 Xuebin Feng
# Author affiliation: University of Toronto
# SPDX-License-Identifier: Apache-2.0

"""The suite does not open anything on the user's desktop.

The main program's guard (tests/desktop_openers.py in the project root, loaded by
tests/__init__.py) replaces the calls that open a folder, a page or a console, in
this process and in the VR Configuration GUI's subprocess, and fails a test that
reaches one it did not expect.
"""

import os
import sys
import unittest
import webbrowser

from tests import DESKTOP_OPENERS, openers


@unittest.skipUnless(DESKTOP_OPENERS, "opt_vr is not inside the main program here")
class InProcessTests(unittest.TestCase):
    def test_the_guard_is_installed_in_the_test_process(self):
        self.assertEqual(webbrowser.open.__module__, "desktop_openers")
        with openers.expecting() as calls:
            self.assertTrue(webbrowser.open("http://127.0.0.1:1/x"), "and no page is opened")
        self.assertEqual(len(calls), 1)

    def test_a_test_that_reaches_an_opener_fails(self):
        class Reaches(unittest.TestCase):
            def test_it(self):
                webbrowser.open("http://127.0.0.1:1/reached")

        result = unittest.TestResult()
        Reaches("test_it").run(result)
        self.assertEqual(len(result.failures), 1)
        self.assertIn("webbrowser.open('http://127.0.0.1:1/reached')", result.failures[0][1])


@unittest.skipUnless(DESKTOP_OPENERS, "opt_vr is not inside the main program here")
@unittest.skipUnless(sys.platform == "win32", "the VR Configuration GUI runs on Windows only")
class GuiScriptTests(unittest.TestCase):
    def test_a_gui_script_that_reaches_an_opener_fails_the_test(self):
        from tests.test_vr_config import run_gui_script

        with self.assertRaises(AssertionError) as caught:
            run_gui_script(
                """
                import webbrowser
                webbrowser.open("http://127.0.0.1:1/from-the-gui")
                """
            )
        self.assertIn("reached the desktop", str(caught.exception))
        self.assertIn("http://127.0.0.1:1/from-the-gui", str(caught.exception))

    def test_a_gui_script_that_opens_nothing_passes(self):
        from tests.test_vr_config import run_gui_script

        self.assertIn("quiet", run_gui_script('print("quiet")'))


if __name__ == "__main__":
    unittest.main()
