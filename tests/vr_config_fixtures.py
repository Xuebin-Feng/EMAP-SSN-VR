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

"""Shared helpers for testing the VR Configuration GUI (``EMAPSSN_Config_VR.py``).

Provides both:

* ``vr_config_session(...)``: runs ``EMAPSSN_Config_VR.py`` in-process on Qt's
  ``offscreen`` platform inside an isolated throwaway project directory, guarded
  by a process-wide ``sys.addaudithook`` so this checkout's own settings files
  are never touched, and restores Qt translations, theme, working directory,
  environment, streams, and ``sys.excepthook`` on exit.
* ``run_gui_script(...)`` / ``report_from(...)``: runs a snippet in a separate
  offscreen subprocess when a test specifically verifies child-process
  behaviour (such as ``test_desktop_openers.GuiScriptTests``).

Not collected by ``unittest``; import with ``from tests.vr_config_fixtures import ...``.
Qt and PyTorch are imported lazily inside the in-process GUI helpers so that
Qt-free test modules (such as ``test_desktop_openers``) can import
``run_gui_script`` without pulling ``PySide6`` into a headless test process.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from unittest import mock

#: The submodule root; VR_SRC is its module tree, mirroring the main
#: program's project-root/src split.
OPT_VR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VR_SRC = os.path.join(OPT_VR, "src")
if VR_SRC not in sys.path:
    sys.path.insert(0, VR_SRC)

import _bootstrap_vr  # noqa: E402
from tests import DESKTOP_OPENERS  # noqa: E402

#: Absolute path to the VR Configuration GUI entry point.
CONFIG_PATH = os.path.join(VR_SRC, "EMAPSSN_Config_VR.py")

#: Snapshot of the real checkout root before any test patches ``_bootstrap_vr``.
REAL_PROJECT_ROOT = _bootstrap_vr.PROJECT_ROOT
REAL_OPT_VR_DIR = _bootstrap_vr.OPT_VR_DIR

#: This checkout's own settings files, which belong to whoever runs the suite.
#: No GUI test or script may read or write them.
USER_SETTINGS_FILES = (
    os.path.join(OPT_VR, "viewer_settings_vr.json"),
    os.path.join(REAL_PROJECT_ROOT, "viewer_settings.json"),
    os.path.join(REAL_PROJECT_ROOT, "app_settings.json"),
)
_USER_SETTINGS_SET = frozenset(os.path.normcase(os.path.abspath(p)) for p in USER_SETTINGS_FILES)

#: Installed before anything else in a GUI subprocess script. An audit hook sees
#: every open, rename and delete the process makes, whichever module worked out
#: the path, and raising from it stops the call before the file is touched.
SETTINGS_GUARD = textwrap.dedent(
    """
    import os, sys
    _refused = []

    def _guard(event, args):
        if event in ("open", "os.remove", "os.truncate"):
            paths = args[:1]
        elif event == "os.rename":  # os.replace raises this one too
            paths = args[:2]
        else:
            return
        for path in paths:
            if isinstance(path, int):  # a descriptor, checked when it was opened
                continue
            path = os.fsdecode(path)
            if os.path.normcase(os.path.abspath(path)) in _USER_FILES:
                _refused.append(f"{event} {path}")
                print(f"Refused {event} of {path}", file=sys.stderr)
                raise PermissionError(f"GUI tests may not touch {path}")

    sys.addaudithook(_guard)
    """
)

# ---------------------------------------------------------------------------
# Process-wide in-process state (lazily initialized on first GUI test)
# ---------------------------------------------------------------------------

_AUDIT_HOOK_INSTALLED = False
_SETTINGS_GUARD_DEPTH = 0
_SETTINGS_REFUSED: list[str] = []
_COMPILED_CONFIG_CODE = None
_QT_PRELOADED = False
_TRANSLATION_FIXTURES = None
_APPLIED_THEME: tuple[str, bool] | None = None


def _install_settings_audit_hook() -> None:
    """Install the in-process settings audit hook once per interpreter."""
    global _AUDIT_HOOK_INSTALLED
    if _AUDIT_HOOK_INSTALLED:
        return

    def _guard(event, args):
        if _SETTINGS_GUARD_DEPTH <= 0:
            return
        if event in ("open", "os.remove", "os.truncate"):
            paths = args[:1]
        elif event == "os.rename":
            paths = args[:2]
        else:
            return
        for path in paths:
            if isinstance(path, int):
                continue
            decoded = os.fsdecode(path)
            if os.path.normcase(os.path.abspath(decoded)) in _USER_SETTINGS_SET:
                _SETTINGS_REFUSED.append(f"{event} {decoded}")
                raise PermissionError(f"GUI tests may not touch {decoded}")

    sys.addaudithook(_guard)
    _AUDIT_HOOK_INSTALLED = True


def _ensure_qt_application():
    """Preload PyTorch before PySide6 and return the shared offscreen QApplication."""
    global _QT_PRELOADED
    if sys.platform != "win32":
        raise unittest.SkipTest("the VR Configuration GUI runs on Windows only")
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    os.environ["QT_API"] = "pyside6"
    if not _QT_PRELOADED:
        # On Windows, PyTorch must load before PySide6/OpenGL initializes,
        # otherwise torch's c10.dll can fail to load.
        from utilities import Hardware_Acceleration as _preload  # noqa: F401
        _QT_PRELOADED = True
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def _get_compiled_config_code():
    """Compile EMAPSSN_Config_VR.py once for repeated in-process execution."""
    global _COMPILED_CONFIG_CODE
    if _COMPILED_CONFIG_CODE is None:
        with open(CONFIG_PATH, encoding="utf-8") as handle:
            source = handle.read()
        _COMPILED_CONFIG_CODE = compile(source, CONFIG_PATH, "exec")
    return _COMPILED_CONFIG_CODE


def load_translation_fixtures():
    """Load the parent repository's ``tests/translation_fixtures.py`` helper."""
    global _TRANSLATION_FIXTURES
    if _TRANSLATION_FIXTURES is None:
        fixtures_path = os.path.join(
            os.path.dirname(_bootstrap_vr.SRC_DIR), "tests", "translation_fixtures.py"
        )
        spec = importlib.util.spec_from_file_location("translation_fixtures", fixtures_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _TRANSLATION_FIXTURES = module
    return _TRANSLATION_FIXTURES


def flush_events(app, count: int = 4) -> None:
    """Process pending Qt events ``count`` times."""
    for _ in range(count):
        app.processEvents()


def resize_config_panel(window, app, width: int, flush_count: int = 4) -> None:
    """Resize a Config window so its tab panel reaches ``width`` pixels."""
    window.resize(width + 360, 850)
    window.main_split.setSizes([width + 4, 326])
    flush_events(app, flush_count)
    delta = width - window.tabs.currentWidget().width()
    left, right = window.main_split.sizes()
    window.main_split.setSizes([left + delta, right - delta])
    flush_events(app, flush_count)


def finish_statistics(window, timeout: float = 60.0) -> None:
    """Wait for ``window.run_statistics()``'s worker thread and deliver its signal."""
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    deadline = time.monotonic() + timeout
    while window._statistics_request is not None:
        if time.monotonic() > deadline:
            raise AssertionError("the network statistics did not finish")
        app.processEvents()
        time.sleep(0.005)
    app.processEvents()


def _close_widget_safely(widget) -> None:
    """Stop any Config timers, close, and schedule deletion if the Qt wrapper is valid."""
    import shiboken6

    if widget is None or not shiboken6.isValid(widget):
        return
    timer = getattr(widget, "_cache_recheck_timer", None)
    if timer is not None and shiboken6.isValid(timer):
        timer.stop()
    try:
        widget.close()
    except RuntimeError:
        return
    if shiboken6.isValid(widget):
        widget.deleteLater()


def _drain_deferred_deletes(app) -> None:
    """Drain pending Qt callbacks first, then destroy ``deleteLater()`` widgets."""
    from PySide6.QtCore import QCoreApplication, QEvent

    for _ in range(3):
        app.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


def _apply_theme_if_needed(app, color, high_contrast=False) -> None:
    """Apply the Studio theme only when the active colour/contrast actually differs."""
    global _APPLIED_THEME
    from desktop import Studio_Theme

    want = (color, bool(high_contrast))
    if (
        _APPLIED_THEME == want
        and Studio_Theme.theme_color() == want[0]
        and Studio_Theme.high_contrast() == want[1]
        and bool(app.styleSheet())
    ):
        return
    Studio_Theme.apply_studio_theme(app, want[0], high_contrast=want[1])
    _APPLIED_THEME = (Studio_Theme.theme_color(), Studio_Theme.high_contrast())


@dataclass
class VRConfigSession:
    """Live in-process VR Configuration GUI instance and its module namespace."""

    window: object
    namespace: dict
    app: object
    project_root: str
    opt_vr_dir: str

    def finish_statistics(self, window=None, timeout: float = 60.0) -> None:
        finish_statistics(self.window if window is None else window, timeout=timeout)


@contextlib.contextmanager
def vr_config_session(project_root: str | None = None, pseudo_translation: bool = False):
    """Build ``EMAPSSN_Config_VR.py`` in-process in an isolated project root.

    Mirrors ``run_gui_script`` without spawning a cold Python + torch + PySide6
    subprocess:

    * Runs with ``QT_QPA_PLATFORM=offscreen`` and ``SSN_NO_CONSOLE_CAPTURE=1``.
    * Points ``_bootstrap_vr.PROJECT_ROOT`` and ``_bootstrap_vr.OPT_VR_DIR`` at
      a throwaway project folder (or ``project_root`` if supplied) so no real
      checkout settings file is ever read or written.
    * Activates the ``SETTINGS_GUARD`` audit hook for the duration of the block.
    * Restores translations (English), Studio theme (default, non-high-contrast),
      ``sys.excepthook``, standard streams, ``os.getcwd()``, ``os.environ``,
      ``_bootstrap_vr`` paths, and closes/deletes every top-level window opened
      during the session.
    """
    global _SETTINGS_GUARD_DEPTH, _APPLIED_THEME

    if sys.platform != "win32":
        raise unittest.SkipTest("the VR Configuration GUI runs on Windows only")

    app = _ensure_qt_application()
    _install_settings_audit_hook()

    from PySide6.QtWidgets import QApplication
    from desktop import Desktop_App, Studio_Theme

    throwaway = None
    if project_root is None:
        throwaway = tempfile.TemporaryDirectory(prefix="ssn_vr_gui_", ignore_cleanup_errors=True)
        project_root = throwaway.name

    opt_vr_dir = os.path.join(project_root, "opt_vr")
    os.makedirs(opt_vr_dir, exist_ok=True)

    original_cwd = os.getcwd()
    original_project_root = _bootstrap_vr.PROJECT_ROOT
    original_opt_vr_dir = _bootstrap_vr.OPT_VR_DIR
    original_excepthook = sys.excepthook
    original_streams = [
        (stream, stream.encoding, stream.errors)
        for stream in (sys.stdout, sys.stderr)
        if hasattr(stream, "reconfigure")
    ]
    env_keys = (
        "QT_QPA_PLATFORM",
        "SSN_VIEWER_SETTINGS_PATH",
        "SSN_VIEWER_EXPLICIT_SETTINGS",
        "SSN_PSEUDO_TRANSLATION",
        "SSN_APP_SETTINGS_PATH",
        "SSN_NO_CONSOLE_CAPTURE",
    )
    saved_env = {key: os.environ.get(key) for key in env_keys}
    before_widgets = set(app.topLevelWidgets())
    before_redrawn = list(Desktop_App._redrawn_windows)

    refused_start = len(_SETTINGS_REFUSED)
    window = None
    namespace = None

    def _startup_apply_theme(target_app, color=None, *, high_contrast=None):
        want_color = Studio_Theme.theme_color() if color is None else color
        want_hc = Studio_Theme.high_contrast() if high_contrast is None else bool(high_contrast)
        _apply_theme_if_needed(target_app, want_color, high_contrast=want_hc)

    try:
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        os.environ.pop("SSN_VIEWER_SETTINGS_PATH", None)
        os.environ.pop("SSN_VIEWER_EXPLICIT_SETTINGS", None)
        os.environ.pop("SSN_PSEUDO_TRANSLATION", None)
        if pseudo_translation:
            os.environ["SSN_PSEUDO_TRANSLATION"] = "1"
        os.environ["SSN_APP_SETTINGS_PATH"] = os.path.join(project_root, "app_settings.json")
        os.environ["SSN_NO_CONSOLE_CAPTURE"] = "1"

        _bootstrap_vr.PROJECT_ROOT = project_root
        _bootstrap_vr.OPT_VR_DIR = opt_vr_dir
        _SETTINGS_GUARD_DEPTH += 1

        namespace = {"__name__": "__main__", "__file__": CONFIG_PATH}
        with mock.patch.object(QApplication, "exec", return_value=0), \
             mock.patch.object(sys, "exit", return_value=None), \
             mock.patch.object(Desktop_App, "apply_studio_theme", side_effect=_startup_apply_theme), \
             mock.patch.object(Desktop_App, "show_window_in_front", side_effect=lambda win: win.show()):
            exec(_get_compiled_config_code(), namespace)

        window = namespace["window"]
        yield VRConfigSession(
            window=window,
            namespace=namespace,
            app=app,
            project_root=project_root,
            opt_vr_dir=opt_vr_dir,
        )
    finally:
        # Drain any 0 ms layout timers queued by show()/resize() while widgets
        # are still alive, then close and destroy every window opened during
        # this session before resetting state or deleting throwaway directories.
        flush_events(app, 4)
        to_close = []
        if window is not None:
            to_close.append(window)
        for redrawn in Desktop_App._redrawn_windows:
            if redrawn not in before_redrawn and redrawn not in to_close:
                to_close.append(redrawn)
        for widget in app.topLevelWidgets():
            if widget not in before_widgets and widget not in to_close:
                to_close.append(widget)
        for widget in to_close:
            _close_widget_safely(widget)
        to_close.clear()
        Desktop_App._redrawn_windows[:] = before_redrawn
        window = None
        namespace = None
        _drain_deferred_deletes(app)

        # Reset process-wide Qt translation and theme state for the next test.
        if Desktop_App.installed_language() is not None:
            Desktop_App.install_translations(app, "en")
        _APPLIED_THEME = (Studio_Theme.theme_color(), Studio_Theme.high_contrast())
        _apply_theme_if_needed(app, Studio_Theme.DEFAULT_THEME_COLOR, high_contrast=False)
        _drain_deferred_deletes(app)

        # Restore interpreter and process state before deleting throwaway dirs.
        sys.excepthook = original_excepthook
        for stream, encoding, errors in original_streams:
            stream.reconfigure(encoding=encoding, errors=errors)
        _bootstrap_vr.PROJECT_ROOT = original_project_root
        _bootstrap_vr.OPT_VR_DIR = original_opt_vr_dir
        os.chdir(original_cwd)
        for key, value in saved_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

        _SETTINGS_GUARD_DEPTH = max(0, _SETTINGS_GUARD_DEPTH - 1)
        refused = _SETTINGS_REFUSED[refused_start:]
        del _SETTINGS_REFUSED[refused_start:]

        if throwaway is not None:
            throwaway.cleanup()

    if refused:
        raise AssertionError("Touched the user's settings: " + "; ".join(refused))


# ---------------------------------------------------------------------------
# Subprocess runner (retained for tests that verify child-process behaviour)
# ---------------------------------------------------------------------------

def run_gui_script(body, project_root=None, pseudo_translation=False):
    """Build the GUI in an offscreen subprocess and run `body` against it.

    The GUI never sees this checkout's settings. It runs as if opt_vr sat at
    `<project_root>/opt_vr`, so its settings file and every relative
    directory resolve there: a throwaway folder, unless a test passes its own
    to inspect afterwards. `body` runs under SETTINGS_GUARD, and the run fails
    if anything still tried to read or write the real settings files. The
    GUI starts in English unless pseudo_translation asks for the test-only
    pseudo-language, whatever the shell running the tests has set.
    """
    if sys.platform != "win32":
        # The GUI refuses to start anywhere else (_bootstrap_vr), so every
        # test that runs it is skipped, as the player and lock tests are.
        raise unittest.SkipTest("the VR Configuration GUI runs on Windows only")
    if project_root is None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as throwaway:
            return run_gui_script(body, throwaway, pseudo_translation)
    working_directory = os.path.join(project_root, "opt_vr")
    os.makedirs(working_directory, exist_ok=True)
    guard = f"_USER_FILES = {set(map(os.path.normcase, USER_SETTINGS_FILES))!r}\n"
    script = guard + SETTINGS_GUARD + textwrap.dedent(
        """
        import json, os, runpy, sys
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        sys.path.insert(0, {vr_src!r})
        # The main suite's guard: nothing the GUI does may open a folder, a page or a console.
        if {openers!r}:
            import importlib.util
            _spec = importlib.util.spec_from_file_location("desktop_openers", {openers!r})
            _openers_module = importlib.util.module_from_spec(_spec)
            _spec.loader.exec_module(_openers_module)
            _openers_module.install()
        import _bootstrap_vr  # puts the parent src tree on sys.path
        # The GUI derives its own paths from these two when it is loaded.
        _bootstrap_vr.PROJECT_ROOT = {project_root!r}
        _bootstrap_vr.OPT_VR_DIR = {opt_vr!r}
        from unittest import mock
        from utilities import Hardware_Acceleration as _preload  # torch before Qt
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance() or QApplication([])
        with mock.patch.object(QApplication, "exec", return_value=0), \\
             mock.patch.object(sys, "exit", return_value=None):
            namespace = runpy.run_path(
                os.path.join({vr_src!r}, "EMAPSSN_Config_VR.py"), run_name="__main__"
            )
        window = namespace["window"]
        Config = type("Config", (), namespace)

        def finish_statistics(window, timeout=60.0):
            # run_statistics works on a worker thread; wait for it, inside any patch its reads need.
            import time
            deadline = time.monotonic() + timeout
            while window._statistics_request is not None:
                if time.monotonic() > deadline:
                    raise AssertionError("the network statistics did not finish")
                app.processEvents()
                time.sleep(0.005)
            app.processEvents()
        """
    ).format(
        vr_src=VR_SRC, project_root=project_root, opt_vr=working_directory, openers=DESKTOP_OPENERS
    ) + textwrap.dedent(body) + textwrap.dedent(
        """
        window.close()
        if _refused:
            raise SystemExit("Touched the user's settings: " + "; ".join(_refused))
        """
    )
    environment = dict(os.environ)
    environment["QT_QPA_PLATFORM"] = "offscreen"
    # Start from the GUI's own default settings path. Sibling test modules
    # point SSN_VIEWER_SETTINGS_PATH at a neutral temp file, and inheriting it
    # would make these tests describe that file instead of the submodule's.
    environment.pop("SSN_VIEWER_SETTINGS_PATH", None)
    environment.pop("SSN_PSEUDO_TRANSLATION", None)
    if pseudo_translation:
        environment["SSN_PSEUDO_TRANSLATION"] = "1"
    # The language setting, too, comes from the throwaway project.
    environment["SSN_APP_SETTINGS_PATH"] = os.path.join(project_root, "app_settings.json")
    # The entry point's first step keeps what the process prints for the Console window, in a log under the
    # checkout's temp/logs: not for a script that only borrows the GUI's main block, or every test would write
    # one there (and push the real logs out of the ten kept).
    environment["SSN_NO_CONSOLE_CAPTURE"] = "1"
    # Whatever the GUI or `body` makes with tempfile (scripts call mkdtemp for their fixture
    # folders) lands in a folder removed after the run, not in the user's temporary folder.
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as scratch:
        for name in ("TEMP", "TMP", "TMPDIR"):
            environment[name] = scratch
        result = subprocess.run(
            [sys.executable, "-u", "-c", script],
            capture_output=True, text=True, env=environment, cwd=working_directory,
            timeout=900,
        )
    if result.returncode != 0:
        raise AssertionError(
            f"GUI subprocess failed:\n{result.stdout}\n{result.stderr}"
        )
    if "Desktop openers reached" in result.stderr:
        # The guard printed it as the process ended: the GUI asked the desktop to open something.
        raise AssertionError(f"The GUI script reached the desktop:\n{result.stderr}")
    return result.stdout


def report_from(body, **options):
    return json.loads(run_gui_script(body, **options).split("@@", 1)[1])
