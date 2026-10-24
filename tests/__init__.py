# Copyright 2026 Xuebin Feng
# Author affiliation: University of Toronto
# SPDX-License-Identifier: Apache-2.0

"""opt_vr regression tests.

Importing this package keeps a test run off the user's desktop: the main program's
guard (tests/desktop_openers.py in the project root) replaces the calls that open
a folder, a page or a console window, and fails a test that reaches one it did not
expect. It is loaded by path, as opt_vr's tests already borrow
tests/translation_fixtures.py, and nothing happens where opt_vr sits without the
main program around it. The VR Configuration GUI runs in a subprocess; see
run_gui_script in test_vr_config.
"""
import importlib.util
import os

#: The path of the main program's guard and the module loaded from it; "" and None where
#: opt_vr is used on its own.
DESKTOP_OPENERS = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "tests", "desktop_openers.py"
)
openers = None
if not os.path.isfile(DESKTOP_OPENERS):
    DESKTOP_OPENERS = ""
else:
    _spec = importlib.util.spec_from_file_location("desktop_openers", DESKTOP_OPENERS)
    openers = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(openers)
    openers.install()
