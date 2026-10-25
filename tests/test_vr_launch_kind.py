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

"""VR Configuration as a kind of the main program's Windows launcher (Desktop_Launcher_VR.py).

The kind is declared in opt_vr: its single-instance key, taskbar identity, splash name and art, texts, batch file, monitor
and the hardware check as a step of the start. A machine that cannot drive a headset is a warning, not a failure: the
splash opens its details by itself with the check's output in the warning colour, the start goes on, and the splash stays
at Ready until Close is pressed. The launch tests run the main program's real Launch object against a scratch copy of the
project (a fake dependency check, a fake hardware check, a fake window, the real monitor scripts) with the splash drawn
nowhere, and no process they start has a window; the real window, the real hardware check and the real look of the splash
are not started here.
"""

import dataclasses
import os
import shutil
import sys
import tempfile
import textwrap
import time
import unittest
import xml.etree.ElementTree as ElementTree
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

#: The submodule root; VR_SRC is its module tree.
OPT_VR = Path(__file__).resolve().parents[1]
VR_SRC = OPT_VR / "src"
BIN_DIR = VR_SRC / "bin"
for _path in (str(BIN_DIR), str(VR_SRC)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import _bootstrap_vr  # noqa: E402

PROJECT_ROOT = Path(_bootstrap_vr.PROJECT_ROOT)



def load_modules():
    """Import what needs Qt when a test first runs, not when the module is collected.

    The VR suite keeps Qt out of its process on purpose: tests of the settings and command layers assert that
    PySide6 is not in sys.modules, and they run (alphabetically) before this module's tests do, so importing
    it at collection would fail them. The Configuration window itself is run in a subprocess for the same reason.
    """
    global QCoreApplication, QTranslator, QPixmap, QLocalServer, QApplication
    global Desktop_Launcher_Monitor_VR, VR, Detect_GPU_VR, Desktop_App, Desktop_Launcher, Desktop_Launcher_Monitor
    global Splash, Launch
    if "VR" in globals():
        return
    from PySide6.QtCore import QCoreApplication, QTranslator
    from PySide6.QtGui import QPixmap
    from PySide6.QtNetwork import QLocalServer
    from PySide6.QtWidgets import QApplication

    import Desktop_Launcher_Monitor_VR
    import Desktop_Launcher_VR as VR
    import Detect_GPU_VR
    from desktop import Desktop_App, Desktop_Launcher, Desktop_Launcher_Monitor, Splash
    from desktop.Desktop_Launcher import Launch


DESKTOP_LAUNCHER_BATCH = BIN_DIR / "EMAPSSN_Desktop_Launcher_VR.bat"
CATALOG_DIR = VR_SRC / "resources" / "languages"


def read(path):
    return Path(path).read_text(encoding="utf-8", errors="replace")


def use_short_socket_folder(test):
    """POSIX: make Qt's temp folder short for a test that listens on a real local socket.

    A local socket is a Unix socket file named ``<temp folder>/<name>``, and a Unix socket path may hold 103
    characters on macOS (107 on Linux), which the test run's own temp folder (tests/session_folder.py in the
    main program) overshoots: 112 to 120 and more. Qt reads TMPDIR whenever it makes the path, for the
    server and for a launcher's connection alike. Windows' local sockets are named pipes, with no such limit.
    """
    if os.name == "nt":
        return
    folder = tempfile.mkdtemp(prefix="ssn-", dir="/tmp")
    test.addCleanup(shutil.rmtree, folder, True)
    test.enterContext(mock.patch.dict(os.environ, {"TMPDIR": folder}))


class Registered(unittest.TestCase):
    """A test that starts with VR Configuration registered, and leaves nothing registered behind."""

    @classmethod
    def setUpClass(cls):
        load_modules()

    def setUp(self):
        self.addCleanup(Desktop_Launcher.LAUNCH_KINDS.pop, "vr", None)
        self.addCleanup(Splash.SUBTITLES.pop, "vr", None)
        self.addCleanup(Splash.LOGO_FILES.pop, "vr", None)
        self.addCleanup(Desktop_Launcher_Monitor.EXTRA_APPLICATIONS.pop, "vr", None)
        self.kind = VR.register()


class KindDeclarationTests(Registered):
    def test_registering_adds_vr_to_the_launcher_the_splash_and_the_monitor_and_nothing_else(self):
        self.assertIs(self.kind, VR.VR_KIND)
        self.assertIs(Desktop_Launcher.LAUNCH_KINDS["vr"], VR.VR_KIND)
        self.assertEqual(sorted(Desktop_Launcher.LAUNCH_KINDS), ["session", "tools", "viewer", "vr"])
        self.assertEqual(Splash.SUBTITLES["vr"], "VR Configuration")
        self.assertIn("vr", Desktop_Launcher_Monitor.EXTRA_APPLICATIONS)
        VR.register()  # again: it replaces its own entries
        self.assertEqual(sorted(Desktop_Launcher.LAUNCH_KINDS), ["session", "tools", "viewer", "vr"])

    def test_it_is_a_checked_kind_with_the_vr_windows_key_and_the_hardware_step(self):
        kind = self.kind
        self.assertEqual((kind.name, kind.splash_kind, kind.check), ("vr", "vr", True))
        self.assertEqual(kind.steps, (VR.HARDWARE_STEP,))
        self.assertEqual(kind.catalogs, ((CATALOG_DIR, "emapssn_vr"),))
        self.assertEqual(kind.batch_file, DESKTOP_LAUNCHER_BATCH)
        self.assertTrue(DESKTOP_LAUNCHER_BATCH.is_file())

    def test_a_second_click_finds_the_window_by_the_key_it_registers_which_is_not_configs(self):
        import Single_Instance_Probe_VR as probe

        key = self.kind.application_id
        self.assertEqual(key, "SSN_VR_Config")
        self.assertEqual(key, probe.VR_CONFIG_APPLICATION_ID)  # the batch file's probe asks the same
        self.assertIn(f'SingleInstanceController("{key}", app)', read(VR_SRC / "EMAPSSN_Config_VR.py"))
        self.assertNotEqual(key, Desktop_Launcher.LAUNCH_KINDS["viewer"].application_id)
        for root in (PROJECT_ROOT, Path("C:/elsewhere")):
            self.assertEqual(Desktop_Launcher.single_instance_server_name(key, root),
                             Desktop_App._single_instance_server_name(key, root))

    def test_a_listening_vr_window_is_brought_forward_and_configs_is_not_mistaken_for_it(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
            use_short_socket_folder(self)
            application = QApplication.instance() or QApplication([])
            name = Desktop_Launcher.single_instance_server_name(self.kind.application_id, folder)
            activated = []
            server = QLocalServer()
            QLocalServer.removeServer(name)
            self.assertTrue(server.listen(name), server.errorString())
            self.addCleanup(server.close)
            server.newConnection.connect(lambda: activated.append(server.nextPendingConnection().readAll()))
            self.assertFalse(Desktop_Launcher.activate_existing_instance("viewer", folder))
            self.assertTrue(Desktop_Launcher.activate_existing_instance("vr", folder))
            deadline = time.monotonic() + 3
            while not activated and time.monotonic() < deadline:
                application.processEvents()
            self.assertEqual(len(activated), 1)

    def test_the_launcher_and_the_shortcut_and_the_window_share_one_taskbar_identity_that_is_not_configs(self):
        identity = self.kind.app_user_model_id
        self.assertEqual(identity, Desktop_App.APP_USER_MODEL_IDS["vr_config"])
        self.assertIn('set_app_user_model_id(APP_USER_MODEL_IDS["vr_config"])', read(VR_SRC / "EMAPSSN_Config_VR.py"))
        self.assertIn(f"-AppId {identity}", read(OPT_VR / "install_vr.bat"))
        self.assertNotEqual(identity, Desktop_App.APP_USER_MODEL_IDS["config"])
        self.assertNotEqual(identity, Desktop_App.APP_USER_MODEL_IDS["tools"])

    def test_the_hardware_check_is_the_script_the_batch_file_runs_in_the_same_way(self):
        step = VR.HARDWARE_STEP
        self.assertEqual(step.label, "Checking VR hardware…")
        command = step.command(PROJECT_ROOT, "C:/py/python.exe")
        self.assertEqual(command, ["C:/py/python.exe", "-u", str(VR_SRC / "Detect_GPU_VR.py")])
        self.assertTrue((VR_SRC / "Detect_GPU_VR.py").is_file())
        self.assertIn('set "HARDWARE_CHECK=%OPT_VR_ROOT%\\src\\Detect_GPU_VR.py"', read(BIN_DIR / "EMAPSSN_VR.bat"))
        self.assertIn("--check-hardware", read(DESKTOP_LAUNCHER_BATCH))
        # The batch file warns in these words and then pauses; the splash warns in them and stays at Ready.
        self.assertIn("will still open, but a headset may not work on this machine", read(DESKTOP_LAUNCHER_BATCH))
        self.assertEqual(step.warning, "EMAP-SSN VR Configuration will still open, but a headset may not work on this machine.")
        self.assertIn(step.warning.split(" will ")[1].rstrip("."), read(DESKTOP_LAUNCHER_BATCH))

    def test_a_check_that_is_not_ready_exits_non_zero_so_each_of_its_verdicts_is_a_warning(self):
        self.assertEqual(Detect_GPU_VR.EXIT_CODES[Detect_GPU_VR.READY], 0)
        for verdict in (Detect_GPU_VR.NO_RUNTIME, Detect_GPU_VR.UNSUPPORTED_GPU, Detect_GPU_VR.UNKNOWN):
            with self.subTest(verdict=verdict):
                self.assertNotEqual(Detect_GPU_VR.EXIT_CODES[verdict], 0)

    def test_the_vr_batch_file_is_the_console_launch_and_gets_the_kind_like_configs_does(self):
        command = Desktop_Launcher.visible_console_command(PROJECT_ROOT, "vr")
        self.assertEqual(command[1:3], ["/d", "/c"])
        self.assertEqual(Path(command[3]), DESKTOP_LAUNCHER_BATCH)
        self.assertEqual(command[4], "vr")
        self.assertEqual(Desktop_Launcher.visible_console_command(PROJECT_ROOT, "viewer")[3],
                         str(PROJECT_ROOT / Desktop_Launcher.BATCH_FILE))  # Config's is still Config's

    def test_the_console_option_runs_it_in_this_console_with_no_splash(self):
        with mock.patch.object(Desktop_Launcher.subprocess, "call", return_value=4) as call, mock.patch.object(
            Desktop_Launcher, "QApplication"
        ) as application:
            self.assertEqual(VR.main(["vr", "--console", "--root", str(PROJECT_ROOT)]), 4)
        application.assert_not_called()
        self.assertEqual(Path(call.call_args.args[0][3]), DESKTOP_LAUNCHER_BATCH)
        self.assertEqual(call.call_args.args[0][4], "vr")

    def test_a_launcher_failure_before_anything_shows_is_the_stubs_cue_for_the_console(self):
        with mock.patch.object(Desktop_Launcher, "main", side_effect=RuntimeError("boom")), mock.patch.object(
            Desktop_Launcher.sys, "stderr"
        ):
            self.assertEqual(VR.main(["vr"]), Desktop_Launcher.EXIT_FALLBACK)
        self.assertEqual(Desktop_Launcher.EXIT_FALLBACK, 3)

    def test_the_main_programs_launcher_splash_and_monitor_name_nothing_of_vr(self):
        for name in ("Desktop_Launcher.py", "Splash.py", "Desktop_Launcher_Monitor.py"):
            source = read(PROJECT_ROOT / "src" / "desktop" / name)
            for word in ("Detect_GPU_VR", "EMAPSSN_Config_VR", "Launcher_VR", "Monitor_VR", "SSN_VR_Config", "vrconfig"):
                with self.subTest(file=name, word=word):
                    self.assertNotIn(word, source)


class SplashTextsTests(Registered):
    """The splash's name, art and texts for VR Configuration."""

    def test_the_splash_names_the_window_under_the_product_and_draws_the_vr_art_at_the_small_size(self):
        application = QApplication.instance() or QApplication([])
        Splash.load_fonts(None)
        logo = Splash.LOGOS / Splash.LOGO_FILES["vr"]
        self.assertEqual(logo, VR.SPLASH_LOGO)
        self.assertTrue(logo.is_file())
        self.assertLess(logo.stat().st_size, 300 * 1024)  # a 512 px copy: the shipped art decodes to 75 MB
        pixmap = QPixmap(str(logo))
        self.assertEqual((pixmap.width(), pixmap.height()), (512, 512))
        window = Splash.SplashWindow("vr")
        self.addCleanup(window.deleteLater)
        self.assertFalse(window.logo.isNull())
        self.assertEqual(window.logo.toImage(), pixmap.toImage())
        self.assertNotEqual(window.logo.toImage(), QPixmap(str(Splash.LOGOS / "splash_logo_viewer_512.png")).toImage())
        window.setAttribute(Splash.Qt.WidgetAttribute.WA_DontShowOnScreen, True)
        window.show()
        application.processEvents()
        window.grab()  # it draws

    def test_the_texts_are_in_vrs_catalog_under_the_splash_context_and_not_in_the_main_one(self):
        texts = {VR.SUBTITLE, VR.CHECKING_HARDWARE, VR.HARDWARE_WARNING}
        self.assertEqual(len(texts), 3)
        found = {
            (context.findtext("name"), message.findtext("source"))
            for context in ElementTree.parse(CATALOG_DIR / "emapssn_vr.ts").getroot().iter("context")
            for message in context.iter("message")
        }
        for text in texts:
            with self.subTest(text=text):
                self.assertIn(("Splash", text), found)
                self.assertNotIn(f"<source>{text}</source>",
                                 read(PROJECT_ROOT / "src" / "resources" / "languages" / "emapssn.ts"))

    def test_the_chinese_drafts_are_there_compiled_and_shown_by_the_splash_with_the_catalogs_the_kind_names(self):
        QApplication.instance() or QApplication([])
        theirs = ElementTree.parse(CATALOG_DIR / "zh_CN" / "emapssn_vr_zh_CN.ts").getroot()
        drafted = {message.findtext("source"): message.findtext("translation")
                   for context in theirs.iter("context") if context.findtext("name") == "Splash"
                   for message in context.iter("message")}
        for text in (VR.SUBTITLE, VR.CHECKING_HARDWARE, VR.HARDWARE_WARNING):
            with self.subTest(text=text):
                self.assertTrue(drafted.get(text), "a draft is in the Chinese catalog")
        compiled = QTranslator()
        self.assertTrue(compiled.load(str(CATALOG_DIR / "zh_CN" / "emapssn_vr_zh_CN.qm")))
        for text in (VR.SUBTITLE, VR.CHECKING_HARDWARE, VR.HARDWARE_WARNING):
            self.assertEqual(compiled.translate("Splash", text), drafted[text])
        translators = [Splash.install_catalog("zh_CN"), *Splash.install_extra_catalogs("zh_CN", self.kind.catalogs)]
        try:
            self.assertEqual(Splash.tr(VR.SUBTITLE), drafted[VR.SUBTITLE])  # VR's own text, from VR's catalog
            self.assertEqual(Splash.tr("Show details"), "显示详情")          # the splash's own, from the main one
            self.assertEqual(QCoreApplication.translate("Splash", VR.HARDWARE_WARNING), drafted[VR.HARDWARE_WARNING])
        finally:
            for translator in translators:
                if translator is not None:
                    QCoreApplication.removeTranslator(translator)
        self.assertEqual(Splash.tr(VR.SUBTITLE), "VR Configuration")  # English where there is no catalog

    def test_the_status_the_window_reports_are_the_main_programs_texts_which_are_translated_already(self):
        source = read(VR_SRC / "EMAPSSN_Config_VR.py")
        self.assertIn("Startup_Status.report(Startup_Status.LOADING_PYTORCH, 0.45)", source)
        self.assertIn("Startup_Status.report(Startup_Status.BUILDING_WINDOW, 0.8)", source)
        self.assertLess(source.index("Startup_Status.report(Startup_Status.LOADING_PYTORCH"),
                        source.index("Hardware_Acceleration as Hardware_Utils"))  # before PyTorch loads
        self.assertLess(source.index("Startup_Status.report(Startup_Status.BUILDING_WINDOW"),
                        source.index("window = ConfigGUI()"))


# --- the launch, against a scratch copy of the project

COPIED_MAIN = (
    "src/desktop/__init__.py", "src/desktop/Desktop_Launcher_Monitor.py", "src/utilities/__init__.py",
    "src/utilities/Localization.py",
)
COPIED_VR = ("src/_bootstrap_vr.py", "src/commands/__init__.py", "src/bin/Desktop_Launcher_Monitor_VR.py")

# The monitor of the scratch tree gets this in place of utilities/Terminal_Launcher.py: a crash it reports the old way
# must leave a record in the state folder and never open a terminal on the screen of whoever runs the tests.
STUB_TERMINAL_LAUNCHER = textwrap.dedent(
    '''
    import json
    import os
    from enum import Enum

    class HoldMode(str, Enum):
        NEVER = "never"
        ALWAYS = "always"
        ON_ERROR = "on_error"

    class TerminalUnavailableError(RuntimeError):
        pass

    def launch_in_terminal(command, *, cwd, env=None, hold=HoldMode.NEVER, title=None, platform_name=None, **ignored):
        with open(os.path.join(str(cwd), "terminal.requested"), "w", encoding="utf-8") as handle:
            json.dump({"title": title, "hold": str(hold.value)}, handle)
    '''
)
# EMAPSSN_Config_VR.py as a stand-in: it reports as the real one does, says where it runs, and becomes ready.
FAKE_VR_WINDOW = textwrap.dedent(
    '''
    import json, os, sys, time
    def report(text, fraction=None):
        with open(os.environ["SSN_STARTUP_STATUS_FILE"], "ab") as handle:
            handle.write((json.dumps({"text": text, "fraction": fraction, "values": {}}) + "\\n").encode())
    print("fake VR window starts in " + os.path.basename(os.getcwd()), flush=True)
    report("Loading PyTorch\\u2026", 0.45)
    if os.environ.get("FAKE_WINDOW") == "fail":
        print("Traceback (most recent call last):", file=sys.stderr, flush=True)
        print("ValueError: the VR window broke", file=sys.stderr, flush=True)
        sys.exit(1)
    report("Building the window\\u2026", 0.8)
    time.sleep(float(os.environ.get("FAKE_WINDOW_DELAY", "0.2")))
    with open(os.environ["SSN_GUI_READY_FILE"], "w") as handle:
        handle.write("ready\\n")
    time.sleep(float(os.environ.get("FAKE_WINDOW_STAY", "0.5")))
    '''
)
# Detect_GPU_VR.py as a stand-in: the lines the real one prints, and the exit code it is told to give.
FAKE_HARDWARE_CHECK = textwrap.dedent(
    '''
    import os, sys
    print("VR hardware: a fake GPU with a fake runtime.", flush=True)
    print("  [ok] a fake GPU", flush=True)
    if os.environ.get("FAKE_HARDWARE_EXIT", "0") != "0":
        print("       and this is why it is not enough", flush=True)
    sys.exit(int(os.environ.get("FAKE_HARDWARE_EXIT", "0")))
    '''
)
FAKE_CHECK = textwrap.dedent(
    '''
    import os, sys
    print("Managed Python: fake", flush=True)
    print("Dependency environment is ready (fake).", flush=True)
    sys.exit(int(os.environ.get("FAKE_CHECK_EXIT", "0")))
    '''
)


def make_tree(test):
    """A project folder with the real monitor scripts of both programs, a fake dependency check, a fake hardware check
    and a fake VR window, and its opt_vr beside it."""
    directory = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
    test.addCleanup(directory.cleanup)
    root = Path(directory.name)
    for relative in COPIED_MAIN:
        (root / relative).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(PROJECT_ROOT / relative, root / relative)
    for relative in COPIED_VR:
        (root / "opt_vr" / relative).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(OPT_VR / relative, root / "opt_vr" / relative)
    (root / "src" / "utilities" / "Terminal_Launcher.py").write_text(STUB_TERMINAL_LAUNCHER, encoding="utf-8")
    (root / "src" / "Install_Dependencies.py").write_text(FAKE_CHECK, encoding="utf-8")
    (root / "opt_vr" / "src" / "EMAPSSN_Config_VR.py").write_text(FAKE_VR_WINDOW, encoding="utf-8")
    (root / "opt_vr" / "src" / "Detect_GPU_VR.py").write_text(FAKE_HARDWARE_CHECK, encoding="utf-8")
    (root / "opt_vr" / "src" / "bin" / "EMAPSSN_Desktop_Launcher_VR.bat").write_text("@echo off\r\n", encoding="utf-8")
    (root / "app_settings.json").write_text('{"LANGUAGE": "en"}', encoding="utf-8")
    return root


class LaunchCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        load_modules()
        cls.app = QApplication.instance() or QApplication([])
        Splash.load_fonts(None)

    def setUp(self):
        self.root = make_tree(self)
        patcher = mock.patch.dict(os.environ, {"SSN_APP_SETTINGS_PATH": str(self.root / "app_settings.json")})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.stop_children)
        # VR Configuration as it registers itself, then pointed at the scratch copy: its kind (the batch file), its
        # hardware script, its window and the monitor script that starts it. Its steps and strings are its own.
        self.addCleanup(Desktop_Launcher.LAUNCH_KINDS.pop, "vr", None)
        self.addCleanup(Splash.SUBTITLES.pop, "vr", None)
        self.addCleanup(Splash.LOGO_FILES.pop, "vr", None)
        self.addCleanup(Desktop_Launcher_Monitor.EXTRA_APPLICATIONS.pop, "vr", None)
        VR.register()
        opt_vr = self.root / "opt_vr"
        Desktop_Launcher_Monitor.register_application(
            "vr", opt_vr / "src" / "EMAPSSN_Config_VR.py", opt_vr,
            monitor=opt_vr / "src" / "bin" / "Desktop_Launcher_Monitor_VR.py")
        patcher = mock.patch.object(VR, "HARDWARE_CHECK", opt_vr / "src" / "Detect_GPU_VR.py")
        patcher.start()
        self.addCleanup(patcher.stop)
        Desktop_Launcher.register_kind(dataclasses.replace(
            VR.VR_KIND, batch_file=opt_vr / "src" / "bin" / "EMAPSSN_Desktop_Launcher_VR.bat"))

    def stop_children(self):
        import psutil

        for process in psutil.process_iter(["pid", "cmdline"]):
            try:
                if str(self.root) in " ".join(process.info["cmdline"] or []):
                    process.kill()
            except (psutil.Error, OSError):
                pass

    def launch(self, *, environment=None, **options):
        options.setdefault("show", False)
        options.setdefault("uv", "uv")
        launch = Launch("vr", self.root, python=sys.executable, popen=mock.Mock(name="popen"), **options)
        self.codes = []
        launch.finished.connect(self.codes.append)
        self.addCleanup(lambda: launch.splash is not None and launch.splash.deleteLater())
        patcher = mock.patch.dict(os.environ, environment or {})
        patcher.start()
        self.addCleanup(patcher.stop)
        return launch

    def run_launch(self, launch, seconds=60):
        launch.begin()
        deadline = time.monotonic() + seconds
        while not self.codes and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.01)
        return self.codes[0] if self.codes else None

    def run_until(self, launch, condition, seconds=60):
        launch.begin()
        deadline = time.monotonic() + seconds
        while not condition() and time.monotonic() < deadline and not self.codes:
            self.app.processEvents()
            time.sleep(0.01)
        self.assertTrue(condition(), "the condition was not met")

    def watch_statuses(self):
        seen = []
        original = Launch.open_splash

        def watching(launch):
            original(launch)
            shown = launch.splash.show_text
            launch.splash.show_text = lambda text, fraction=None: (seen.append((text, fraction)), shown(text, fraction))

        patcher = mock.patch.object(Launch, "open_splash", watching)
        patcher.start()
        self.addCleanup(patcher.stop)
        return seen


class LaunchTests(LaunchCase):
    def test_a_machine_that_can_drive_a_headset_starts_with_a_step_on_the_bar_and_the_splash_closes_itself(self):
        seen = self.watch_statuses()
        launch = self.launch(environment={"FAKE_WINDOW_STAY": "0.1"})
        self.assertEqual(self.run_launch(launch), 0)
        texts = [text for text, _ in seen]
        order = [texts.index(text) for text in ("Dependency environment is ready (fake).", "Checking VR hardware…",
                                                "Starting…", "Loading PyTorch…", "Building the window…")]
        self.assertEqual(order, sorted(order))  # the check, the step, then the window's own two
        self.assertEqual(dict(seen)["Checking VR hardware…"], Splash.FRACTION_CHECKED)
        self.assertEqual(dict(seen)["Starting…"], Splash.FRACTION_STARTED)
        self.assertLess(dict(seen)["Starting…"], dict(seen)["Loading PyTorch…"])  # the bar never has to go back
        for step in ("splash_shown", "check_finished", "step_1_started", "step_1_ended", "monitor_started", "gui_ready",
                     "finished"):
            self.assertIn(step, launch.marks)
        self.assertEqual(launch.warnings, [])
        self.assertNotIn("ready_kept_open", launch.marks)  # nobody had the details open: it closed itself
        self.assertEqual(launch.splash.kind, "vr")
        self.assertFalse(launch.splash.error)

    def test_the_window_runs_in_opt_vr_through_the_vr_monitor_and_its_output_is_in_the_details(self):
        launch = self.launch(environment={"FAKE_WINDOW_STAY": "5"})
        launch.begin()
        launch.splash.set_details_open(True)
        deadline = time.monotonic() + 60
        while "gui_ready" not in launch.marks and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.01)
        self.assertIn("gui_ready", launch.marks)
        lines = launch.splash.details.toPlainText().splitlines()
        self.assertEqual(lines[:2], ["Managed Python: fake", "Dependency environment is ready (fake)."])
        self.assertEqual(lines[2:4], ["VR hardware: a fake GPU with a fake runtime.", "  [ok] a fake GPU"])
        self.assertIn("fake VR window starts in opt_vr", lines)  # in the submodule's folder, as before
        self.assertTrue(launch.state_dir.name.startswith("vr_"))
        self.assertEqual(Path(launch.monitor.args[2]), self.root / "opt_vr" / "src" / "bin" / "Desktop_Launcher_Monitor_VR.py")
        self.assertEqual(launch.monitor.args[3:6], ["--failure-report", "dialog", "vr"])
        self.assertEqual([launch.splash.details.kind_of(index) for index in range(4)], ["info"] * 4)
        launch.splash.close_button.click()
        self.assertEqual(self.codes, [0])

    def a_machine_that_cannot(self, exit_code):
        """A launch whose hardware check exits with ``exit_code``: the window opens all the same, the details open by
        themselves with the check's lines and the warning in the warning colour, and the splash waits at Ready."""
        launch = self.launch(environment={"FAKE_HARDWARE_EXIT": exit_code, "FAKE_WINDOW_STAY": "8"})
        self.run_until(launch, lambda: "gui_ready" in launch.marks)
        splash = launch.splash
        self.assertEqual(launch.warnings, ["Checking VR hardware…"])
        self.assertEqual(launch.marks["warnings"], ["Checking VR hardware…"])
        lines = splash.details.toPlainText().splitlines()
        at = lines.index("VR hardware: a fake GPU with a fake runtime.")
        end = lines.index("fake VR window starts in opt_vr")  # the start went on
        self.assertEqual(lines[at:at + 3], ["VR hardware: a fake GPU with a fake runtime.", "  [ok] a fake GPU",
                                            "       and this is why it is not enough"])
        # The sentence that replaces the batch file's pause, wrapped to the section's width.
        self.assertEqual(" ".join(part.strip() for part in lines[at + 3:end]), VR.HARDWARE_WARNING)
        self.assertEqual([splash.details.kind_of(index) for index in range(at, end)], ["warning"] * (end - at))
        self.assertEqual(splash.details.kind_of(at - 1), "info")  # the dependency check's last line is no warning
        self.assertEqual(splash.details.kind_of(end), "info")     # nor is the window's own
        self.finish_at_ready(launch)

    def test_an_unsupported_gpu_is_a_warning_the_details_open_with_the_output_in_the_warning_colour(self):
        self.a_machine_that_cannot(str(Detect_GPU_VR.EXIT_CODES[Detect_GPU_VR.UNSUPPORTED_GPU]))

    def test_a_missing_openxr_runtime_is_the_same_warning(self):
        self.a_machine_that_cannot(str(Detect_GPU_VR.EXIT_CODES[Detect_GPU_VR.NO_RUNTIME]))

    def test_a_gpu_it_cannot_tell_is_the_same_warning(self):
        self.a_machine_that_cannot(str(Detect_GPU_VR.EXIT_CODES[Detect_GPU_VR.UNKNOWN]))

    def finish_at_ready(self, launch):
        """The splash is open at Ready and stays until Close is pressed; then the launch ends well."""
        splash = launch.splash
        for _ in range(50):  # a second: nothing closes it
            self.app.processEvents()
            time.sleep(0.02)
        self.assertEqual(self.codes, [], "the launch ended on its own")
        self.assertTrue(splash.isVisible())
        self.assertTrue(splash.details_open)
        self.assertTrue(splash.ready)
        self.assertEqual(splash.status, "Ready")
        self.assertIn("ready_kept_open", launch.marks)
        self.assertNotIn("finished", launch.marks)
        self.assertTrue(splash.close_button.isVisibleTo(splash))
        self.assertTrue((launch.state_dir / "terminal.dismissed").is_file())  # the monitor knows the launcher is done
        splash.close_button.click()
        self.assertEqual(self.codes, [0])
        self.assertIn("finished", launch.marks)

    def test_a_check_that_cannot_run_is_a_warning_too_and_the_window_still_opens(self):
        (self.root / "opt_vr" / "src" / "Detect_GPU_VR.py").unlink()  # python cannot open the file
        launch = self.launch(environment={"FAKE_WINDOW_STAY": "8"})
        self.run_until(launch, lambda: "gui_ready" in launch.marks)
        self.assertEqual(launch.warnings, ["Checking VR hardware…"])
        text = launch.splash.details.toPlainText()
        self.assertIn("Detect_GPU_VR.py", text)  # python's own complaint
        self.assertIn("EMAP-SSN VR Configuration will still open", text)
        self.finish_at_ready(launch)

    def test_a_reader_who_hides_the_details_has_the_splash_close_at_ready_as_it_does_for_anyone(self):
        launch = self.launch(environment={"FAKE_HARDWARE_EXIT": "10", "FAKE_WINDOW_STAY": "0.1", "FAKE_WINDOW_DELAY": "1.5"})
        self.run_until(launch, lambda: "step_1_ended" in launch.marks)
        self.assertTrue(launch.splash.details_open)
        launch.splash.set_details_open(False)
        deadline = time.monotonic() + 60
        while not self.codes and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.01)
        self.assertEqual(self.codes, [0])
        self.assertNotIn("ready_kept_open", launch.marks)

    def test_a_dependency_check_that_needs_setup_hands_over_to_the_vr_batch_file_and_runs_no_step(self):
        launch = self.launch(environment={"FAKE_CHECK_EXIT": "10"})
        self.assertEqual(self.run_launch(launch), 0)
        launch.popen.assert_called_once()
        command = launch.popen.call_args.args[0]
        self.assertEqual(Path(command[-2]), self.root / "opt_vr" / "src" / "bin" / "EMAPSSN_Desktop_Launcher_VR.bat")
        self.assertEqual(command[-1], "vr")
        self.assertNotIn("step_1_started", launch.marks)
        self.assertNotIn("monitor_started", launch.marks)
        self.assertEqual(list((self.root / "temp").glob("vr_*")), [])

    def test_a_missing_managed_python_hands_over_to_it_before_any_check_runs(self):
        launch = Launch("vr", self.root, python=self.root / ".venv" / "nothing.exe", uv="uv", show=False, popen=mock.Mock())
        launch.finished.connect(lambda code: None)
        self.addCleanup(lambda: launch.splash is not None and launch.splash.deleteLater())
        launch.begin()
        launch.popen.assert_called_once()
        self.assertEqual(Path(launch.popen.call_args.args[0][-2]).name, "EMAPSSN_Desktop_Launcher_VR.bat")
        self.assertNotIn("check_started", launch.marks)
        self.assertNotIn("step_1_started", launch.marks)

    def test_an_open_vr_window_is_brought_forward_and_nothing_else_starts(self):
        use_short_socket_folder(self)
        name = Desktop_Launcher.single_instance_server_name("SSN_VR_Config", self.root)
        activated = []
        server = QLocalServer()
        QLocalServer.removeServer(name)
        self.assertTrue(server.listen(name), server.errorString())
        self.addCleanup(server.close)
        server.newConnection.connect(lambda: activated.append(server.nextPendingConnection().readAll()))
        launch = self.launch()
        self.assertEqual(self.run_launch(launch, seconds=10), 0)
        deadline = time.monotonic() + 3
        while not activated and time.monotonic() < deadline:
            self.app.processEvents()
        self.assertEqual(len(activated), 1)
        self.assertIn("activated_existing", launch.marks)
        self.assertIsNone(launch.splash)  # no splash, no check, no step
        self.assertNotIn("check_started", launch.marks)
        self.assertNotIn("step_1_started", launch.marks)

    def test_a_second_click_while_the_first_is_starting_ends_without_a_splash(self):
        held = Desktop_Launcher.acquire_launch_lock(self.root, "vr")
        self.assertIsNotNone(held)
        self.addCleanup(held.unlock)
        launch = self.launch()
        self.assertEqual(self.run_launch(launch, seconds=10), 0)
        self.assertIn("launch_in_progress", launch.marks)
        self.assertIsNone(launch.splash)

    def test_a_window_that_fails_before_it_is_ready_is_the_error_view_not_a_warning(self):
        launch = self.launch(environment={"FAKE_WINDOW": "fail"})
        launch.begin()
        deadline = time.monotonic() + 60
        while not launch.splash.error and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.01)
        self.assertTrue(launch.splash.error)
        self.assertIn("ValueError: the VR window broke", launch.splash.details.toPlainText())
        self.assertEqual(launch.splash.kind, "vr")
        self.assertIn("EMAP-SSN VR Configuration", launch.splash.error_title)  # it names the window the user clicked
        launch.splash.close_button.click()
        self.assertEqual(self.codes, [0])


if __name__ == "__main__":
    unittest.main()
