# Copyright 2026 Xuebin Feng
# Author affiliation: University of Toronto
# SPDX-License-Identifier: Apache-2.0

"""opt_vr regression tests.

Importing this package keeps a test run off the user's desktop: the main program's
guard (tests/desktop_openers.py in the project root) replaces the calls that open
a folder, a page or a console window, and fails a test that reaches one it did not
expect. It is loaded by path, as opt_vr's tests already borrow
tests/translation_fixtures.py, and nothing happens where opt_vr sits without the
main program around it.

VR tests write only to temporary folders. Every test module loads the neutral
settings of neutral_settings.py, which put the cache folder (and so the command
history, saved configs and saved layouts) in a temporary directory, and this
package points SSN_LOG_DIR (the console logs of a window or launcher a test
starts) at one too. Nothing a test does may create or change a file inside the
project folder.
test_temp_history_vr checks that a viewer from each builder keeps its history
outside it. The VR Configuration GUI runs in a subprocess; see
run_gui_script in test_vr_config.
"""
import atexit
import importlib.util
import os
import tempfile

if not os.environ.get("SSN_LOG_DIR"):
    # Without this, a test that starts a window or launcher writes its console log to temp/logs in the project.
    _LOGS = tempfile.TemporaryDirectory(prefix="ssn_vr_logs_")  # removed when this process exits
    atexit.register(_LOGS.cleanup)
    os.environ["SSN_LOG_DIR"] = _LOGS.name

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
