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

"""Tests for the command compatibility checker.

Run from the opt_vr directory:

    ../.venv/Scripts/python.exe -m unittest discover -s tests -t .

Two things are covered. The probes are unit tested against synthetic modules,
because a checker that quietly stops detecting anything is worse than no
checker at all - every probe has a positive *and* a negative case. Then one
integration test asserts the invariant that actually matters: every command the
dispatcher can reach is loadable. That test is the reason this file exists; the
rest keeps it honest.
"""

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

#: The submodule root; VR_SRC is its module tree, mirroring the main
#: program's project-root/src split.
OPT_VR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VR_SRC = os.path.join(OPT_VR, "src")
if VR_SRC not in sys.path:
    sys.path.insert(0, VR_SRC)

# Keep these tests independent of whatever the user last saved.
_NEUTRAL = tempfile.NamedTemporaryFile(
    "w", suffix=".json", delete=False, encoding="utf-8"
)
json.dump({}, _NEUTRAL)
_NEUTRAL.close()
os.environ["SSN_VIEWER_SETTINGS_PATH"] = _NEUTRAL.name

with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
    import Command_Compatibility_VR as cc  # noqa: E402


def _module(source):
    """Write ``source`` to a throwaway .py file and return its path."""
    handle = tempfile.NamedTemporaryFile(
        "w", suffix=".py", delete=False, encoding="utf-8"
    )
    handle.write(source)
    handle.close()
    return handle.name


class ViewerAttributeProbeTests(unittest.TestCase):
    """The AST probe must separate real requirements from guarded access."""

    def _required(self, source):
        return cc.required_viewer_attrs(_module(source))

    def test_plain_read_is_required(self):
        self.assertIn("full_headers", self._required("def run(viewer, args):\n"
                                                    "    return viewer.full_headers\n"))

    def test_hasattr_guard_makes_it_optional(self):
        source = (
            "def run(viewer, args):\n"
            "    if hasattr(viewer, 'canvas'):\n"
            "        viewer.canvas.update()\n"
        )
        self.assertNotIn("canvas", self._required(source))

    def test_getattr_with_default_is_optional(self):
        source = "def run(viewer, args):\n    return getattr(viewer, 'canvas', None)\n"
        self.assertNotIn("canvas", self._required(source))

    def test_getattr_without_default_is_required(self):
        """Two-argument getattr raises on a missing attribute, so it counts."""
        source = "def run(viewer, args):\n    return getattr(viewer, 'canvas')\n"
        self.assertIn("canvas", self._required(source))

    def test_attribute_the_command_assigns_is_not_required(self):
        source = (
            "def run(viewer, args):\n"
            "    viewer.scratch = 1\n"
            "    return viewer.scratch\n"
        )
        self.assertNotIn("scratch", self._required(source))

    def test_setattr_also_counts_as_assignment(self):
        source = (
            "def run(viewer, args):\n"
            "    setattr(viewer, 'scratch', 1)\n"
            "    return viewer.scratch\n"
        )
        self.assertNotIn("scratch", self._required(source))

    def test_attributes_of_other_objects_are_ignored(self):
        source = "def run(viewer, args):\n    return args.canvas\n"
        self.assertNotIn("canvas", self._required(source))

    def test_standin_viewer_keywords_are_not_requirements(self):
        """A SimpleNamespace snapshot is built by the command, not demanded."""
        source = (
            "from types import SimpleNamespace\n"
            "def _worker(viewer):\n"
            "    return viewer._job_output_path\n"
            "def run(viewer, args):\n"
            "    return _worker(SimpleNamespace(_job_output_path='out.xlsx'))\n"
        )
        self.assertNotIn("_job_output_path", self._required(source))

    def test_standin_rule_does_not_hide_ordinary_requirements(self):
        """Only SimpleNamespace counts; other calls must not suppress anything."""
        source = (
            "def run(viewer, args):\n"
            "    helper(canvas=1)\n"
            "    return viewer.canvas\n"
        )
        self.assertIn("canvas", self._required(source))


class ViewerSurfaceTests(unittest.TestCase):
    """The surface is derived from source, so it must track the real viewer."""

    @classmethod
    def setUpClass(cls):
        cls.surface = cc.viewer_surface()

    def test_constructor_attributes_are_present(self):
        for name in ("n_nodes", "metadata", "current_colors", "visible_mask"):
            self.assertIn(name, self.surface, name)

    def test_viewer_methods_are_present(self):
        for name in ("process_command", "update_nodes", "_save_state"):
            self.assertIn(name, self.surface, name)

    def test_desktop_only_attributes_are_absent(self):
        """These belong to the VisPy/Qt viewer and must not be claimed here."""
        for name in ("canvas", "view", "open_metadata_ui"):
            self.assertNotIn(name, self.surface, name)


class ImportProbeTests(unittest.TestCase):
    """The import probe must name the toolkit *and* keep sys.modules clean."""

    def test_clean_module_loads(self):
        path = _module("VALUE = 1\n")
        self.assertIsNone(cc.probe_import(path, "_probe_test_clean"))

    def test_gui_import_is_blocked_and_named(self):
        path = _module("import PySide6\n")
        blocker = cc.probe_import(path, "_probe_test_gui")
        self.assertIsNotNone(blocker)
        self.assertEqual(blocker.kind, cc.GUI)
        self.assertEqual(blocker.module, "PySide6")

    def test_gui_submodule_import_is_blocked(self):
        path = _module("from PySide6 import QtWidgets\n")
        blocker = cc.probe_import(path, "_probe_test_gui_sub")
        self.assertEqual(blocker.kind, cc.GUI)

    def test_missing_third_party_is_a_dependency_not_a_failure(self):
        """An uninstalled package says nothing about VR compatibility."""
        path = _module("import definitely_not_a_real_package_xyz\n")
        blocker = cc.probe_import(path, "_probe_test_dep")
        self.assertEqual(blocker.kind, cc.DEPENDENCY)

    def test_other_errors_are_reported_as_errors(self):
        path = _module("raise ValueError('boom')\n")
        blocker = cc.probe_import(path, "_probe_test_err")
        self.assertEqual(blocker.kind, cc.ERROR)
        self.assertEqual(blocker.module, "ValueError")

    def test_probe_does_not_leak_into_sys_modules(self):
        path = _module("VALUE = 1\n")
        cc.probe_import(path, "_probe_test_leak")
        self.assertNotIn("_probe_test_leak", sys.modules)

    def test_gui_packages_stay_unimported(self):
        """The finder must refuse Qt outright, not import and then complain."""
        path = _module("import PySide6\n")
        cc.probe_import(path, "_probe_test_no_qt")
        self.assertNotIn("PySide6", sys.modules)

    def test_project_module_is_distinguished_from_a_dependency(self):
        self.assertTrue(cc._is_project_module("Command_Engine"))
        self.assertFalse(cc._is_project_module("matplotlib"))


class VerdictTests(unittest.TestCase):
    """Verdict logic is pure, so it is tested without touching the filesystem."""

    def _report(self, **kwargs):
        kwargs.setdefault("name", "demo")
        return cc.CommandReport(**kwargs)

    def test_upstream_only_is_shared(self):
        report = self._report(upstream_path="up.py")
        self.assertEqual(report.state, cc.SHARED)
        self.assertEqual(report.status, cc.OK)

    def test_local_only_has_no_upstream_counterpart(self):
        report = self._report(local_path="local.py")
        self.assertEqual(report.state, cc.LOCAL_ONLY)
        self.assertEqual(report.status, cc.OK)

    def test_override_is_redundant_when_upstream_is_clean(self):
        report = self._report(upstream_path="up.py", local_path="local.py")
        self.assertEqual(report.state, cc.OVERRIDDEN)
        self.assertEqual(report.status, cc.REDUNDANT)

    def test_override_is_justified_when_upstream_needs_qt(self):
        report = self._report(
            upstream_path="up.py",
            local_path="local.py",
            upstream_blocker=cc.Blocker("PySide6", kind=cc.GUI),
        )
        self.assertEqual(report.status, cc.OK)
        self.assertIn("PySide6", report.reason)

    def test_override_is_justified_when_upstream_needs_missing_api(self):
        report = self._report(
            upstream_path="up.py",
            local_path="local.py",
            upstream_missing=("canvas",),
        )
        self.assertEqual(report.status, cc.OK)
        self.assertIn("canvas", report.reason)

    def test_unusable_upstream_with_no_override_is_broken(self):
        report = self._report(
            upstream_path="up.py", upstream_blocker=cc.Blocker("PySide6", kind=cc.GUI)
        )
        self.assertEqual(report.status, cc.BROKEN)

    def test_broken_local_override_is_broken(self):
        """A local copy that cannot load is not rescued by a healthy upstream."""
        report = self._report(
            upstream_path="up.py",
            local_path="local.py",
            local_blocker=cc.Blocker("ValueError", kind=cc.ERROR),
        )
        self.assertEqual(report.status, cc.BROKEN)

    def test_missing_dependency_is_inconclusive_not_broken(self):
        report = self._report(
            upstream_path="up.py",
            local_path="local.py",
            local_blocker=cc.Blocker("matplotlib", kind=cc.DEPENDENCY),
        )
        self.assertEqual(report.status, cc.DEPENDENCY)
        self.assertIn("inconclusive", report.reason)

    def test_dependency_on_upstream_blocks_a_redundant_verdict(self):
        """An unfinished probe must not be laundered into "delete this"."""
        report = self._report(
            upstream_path="up.py",
            local_path="local.py",
            upstream_blocker=cc.Blocker("matplotlib", kind=cc.DEPENDENCY),
        )
        self.assertEqual(report.status, cc.DEPENDENCY)

    def test_report_serialises(self):
        report = self._report(
            upstream_path="up.py",
            local_path="local.py",
            upstream_blocker=cc.Blocker("PySide6", "src/x.py", kind=cc.GUI),
        )
        payload = report.as_dict()
        self.assertEqual(payload["name"], "demo")
        self.assertEqual(payload["state"], cc.OVERRIDDEN)
        self.assertIn("PySide6", payload["upstream_blocker"])


class CommandSetIntegrationTests(unittest.TestCase):
    """The invariant this whole module exists to defend."""

    @classmethod
    def setUpClass(cls):
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            cls.reports = cc.analyse()
        cls.by_name = {report.name: report for report in cls.reports}

    def test_every_command_is_reachable(self):
        """No command may resolve to a module that cannot be loaded.

        This fires when upstream adds a Qt import to a command opt_vr shares,
        or when a local override breaks. Either way the VR viewer would fail at
        the prompt, and this is the cheapest place to find out.
        """
        broken = {
            report.name: report.reason
            for report in self.reports
            if report.status == cc.BROKEN
        }
        self.assertEqual(broken, {}, f"unreachable commands: {broken}")

    def test_probe_reached_a_verdict_for_every_command(self):
        """Guards against a missing dependency hiding a real incompatibility."""
        inconclusive = {
            report.name: report.reason
            for report in self.reports
            if report.status == cc.DEPENDENCY
        }
        self.assertEqual(
            inconclusive,
            {},
            "install the missing packages and re-run: " f"{inconclusive}",
        )

    def test_the_whole_upstream_command_set_is_covered(self):
        upstream = set(cc._command_modules(cc.UPSTREAM_COMMAND_DIR))
        self.assertTrue(upstream, "no upstream commands found")
        self.assertTrue(upstream.issubset(set(self.by_name)))

    def test_qt_bound_commands_are_detected(self):
        """A spot check that the probe still finds real Qt coupling."""
        report = self.by_name["meta"]
        self.assertIsNotNone(report.upstream_blocker)
        self.assertEqual(report.upstream_blocker.kind, cc.GUI)

    def test_desktop_render_commands_are_detected(self):
        """zoom drives the VisPy camera, which the Unity client replaces."""
        self.assertTrue(self.by_name["zoom"].upstream_missing)

    def test_table_renders(self):
        table = cc.render_table(self.reports)
        self.assertIn("COMMAND", table)
        self.assertIn("commands:", table)

    def test_check_mode_passes(self):
        buffer = io.StringIO()
        with redirect_stdout(buffer), redirect_stderr(buffer):
            exit_code = cc.main(["--check"])
        self.assertEqual(exit_code, 0, buffer.getvalue())


class ResolutionTests(unittest.TestCase):
    """The dispatcher must reach exactly the copy the checker sanctions.

    ``Viewer.process_command`` does ``importlib.import_module("commands.<name>")``,
    so these import through the same seam rather than trusting a directory
    listing - a stale override or leftover bytecode would not show up otherwise.
    """

    @classmethod
    def setUpClass(cls):
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            cls.reports = cc.analyse()
        cls.local_dir = os.path.normcase(cc.LOCAL_COMMAND_DIR)
        cls.upstream_dir = os.path.normcase(cc.UPSTREAM_COMMAND_DIR)

    def _origin(self, name):
        import importlib

        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            module = importlib.import_module(f"commands.{name}")
            importlib.reload(module)
        return module, os.path.normcase(
            os.path.dirname(os.path.abspath(module.__file__))
        )

    def test_no_redundant_override_remains(self):
        """A local copy upstream could serve is drift waiting to happen."""
        redundant = sorted(
            report.name for report in self.reports if report.status == cc.REDUNDANT
        )
        self.assertEqual(
            redundant,
            [],
            "these overrides duplicate a compatible upstream command and "
            f"should be deleted so fall-through serves them: {redundant}",
        )

    def test_shared_commands_resolve_to_the_main_program(self):
        shared = [
            report.name for report in self.reports if report.state == cc.SHARED
        ]
        self.assertTrue(shared, "expected at least one shared command")
        for name in shared:
            module, origin = self._origin(name)
            self.assertEqual(
                origin, self.upstream_dir, f"{name} did not come from src/commands"
            )
            self.assertTrue(callable(getattr(module, "run", None)), name)

    def test_overridden_commands_resolve_locally(self):
        overridden = [
            report.name
            for report in self.reports
            if report.state in (cc.OVERRIDDEN, cc.LOCAL_ONLY)
        ]
        for name in overridden:
            module, origin = self._origin(name)
            self.assertEqual(
                origin, self.local_dir, f"{name} did not come from opt_vr/commands"
            )
            self.assertTrue(callable(getattr(module, "run", None)), name)

    def test_no_stale_bytecode_shadows_a_shared_command(self):
        """Deleting a .py leaves __pycache__ behind; make sure it stays inert."""
        cache = os.path.join(cc.LOCAL_COMMAND_DIR, "__pycache__")
        if not os.path.isdir(cache):
            return
        local = set(cc._command_modules(cc.LOCAL_COMMAND_DIR))
        orphaned = sorted(
            entry
            for entry in os.listdir(cache)
            # Package bytecode (__init__) is not a command; _command_modules
            # skips underscore-prefixed sources, so skip them here to match.
            if entry.endswith(".pyc")
            and not entry.startswith("_")
            and entry.split(".")[0] not in local
        )
        self.assertEqual(orphaned, [], f"orphaned bytecode in {cache}: {orphaned}")


class SharedHelperContractTests(unittest.TestCase):
    """Shared commands call opt_vr's helpers, which must satisfy them.

    opt_vr shadows Command_Engine, Viewer_Utils_VR and EMAPSSN_Config, so a command
    served from src/commands calls *these* copies. A helper upstream grew but
    opt_vr never did is an AttributeError at the prompt that no import probe
    would catch, which is precisely how `select` would have broken.
    """

    @classmethod
    def setUpClass(cls):
        import ast as ast_module

        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            import Command_Engine
            import Settings_VR
            import Viewer_Utils_VR

        cls.ast = ast_module
        cls.providers = {
            "Command_Engine": Command_Engine,
            "utils": Viewer_Utils_VR,
            "Viewer_Utils_VR": Viewer_Utils_VR,
            "cfg": Settings_VR,
            "EMAPSSN_Config": Settings_VR,
        }
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            cls.shared = [
                report.name
                for report in cc.analyse()
                if report.state == cc.SHARED
            ]

    def _missing(self, path):
        with open(path, encoding="utf-8") as handle:
            tree = self.ast.parse(handle.read(), filename=path)
        gaps = set()
        for node in self.ast.walk(tree):
            if not isinstance(node, self.ast.Attribute):
                continue
            owner = node.value
            if not isinstance(owner, self.ast.Name):
                continue
            provider = self.providers.get(owner.id)
            if provider is None or not isinstance(node.ctx, self.ast.Load):
                continue
            if not hasattr(provider, node.attr):
                gaps.add(f"{owner.id}.{node.attr}")
        return sorted(gaps)

    def test_shared_commands_find_every_helper_they_call(self):
        gaps = {}
        for name in self.shared:
            path = os.path.join(cc.UPSTREAM_COMMAND_DIR, f"{name}.py")
            missing = self._missing(path)
            if missing:
                gaps[name] = missing
        self.assertEqual(gaps, {}, f"helpers missing from opt_vr: {gaps}")

    def test_selection_api_is_adopted_from_upstream(self):
        """These are re-exported, not forked; losing them re-breaks `select`."""
        import Command_Engine

        for name in (
            "SelectionExpressionError",
            "SelectionContextError",
            "SelectionClassification",
            "SelectionClassificationKind",
            "classify_selection_expression",
            "parse_selection_expression",
        ):
            self.assertTrue(hasattr(Command_Engine, name), name)

    def test_selection_error_is_a_value_error(self):
        """Existing `except ValueError` handlers must keep working."""
        import Command_Engine

        self.assertTrue(
            issubclass(Command_Engine.SelectionExpressionError, ValueError)
        )

    def test_resolve_directory_path_expands_a_leading_alias(self):
        import Settings_VR

        resolved = Settings_VR.resolve_directory_path(
            os.path.join("$analysis_result$", "Sequence_Logos")
        )
        self.assertTrue(os.path.isabs(resolved), resolved)
        self.assertTrue(resolved.endswith("Sequence_Logos"), resolved)

    def test_resolve_directory_path_leaves_other_paths_alone(self):
        import Settings_VR

        self.assertEqual(Settings_VR.resolve_directory_path("plain/path"), "plain/path")
        self.assertIsNone(Settings_VR.resolve_directory_path(None))


class SharedCommandSmokeTests(unittest.TestCase):
    """Run the shared commands for real, not just import them.

    Resolution proves which file loads and the helper contract is checked
    statically; neither proves the command survives contact with opt_vr's
    modules at runtime. These drive the dispatcher exactly as the terminal does
    and fail on any traceback, which is how a missing helper would show up.
    """

    #: Errors about absent data are expected - the fixture has no MSA and no
    #: bound cache. Interpreter-level errors are not.
    FORBIDDEN = ("Traceback", "AttributeError", "TypeError", "NameError")

    CASES = (
        "select P00001",
        "select $sele$",
        "select bogus{expr",
        "hide P00001",
        "query P00001",
        "group",
        "offset",
        "reset",
        "undo",
        "redo",
        "reference",
        "save",
        "label",
        "logo",
    )

    @classmethod
    def setUpClass(cls):
        from tests.test_opt_vr import build_viewer, run_command

        cls.run_command = staticmethod(run_command)
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            cls.viewer = build_viewer()

    def test_shared_commands_execute_without_a_traceback(self):
        for command in self.CASES:
            with self.subTest(command=command):
                output = self.run_command(self.viewer, command)
                hits = [token for token in self.FORBIDDEN if token in output]
                self.assertEqual(hits, [], f"{command!r} produced {hits}:\n{output}")

    def test_malformed_expression_is_reported_not_raised(self):
        """The silent-selection-failure path: classify, report, abort cleanly."""
        output = self.run_command(self.viewer, "select bogus{expr")
        self.assertIn("bogus{expr", output)
        self.assertNotIn("Traceback", output)

    def test_in_memory_selection_token_resolves(self):
        """`$sele$` must resolve from the mask, not a _sele.txt round trip."""
        output = self.run_command(self.viewer, "select $sele$")
        self.assertNotIn("Traceback", output)
        self.assertNotIn("_sele.txt", output)


if __name__ == "__main__":
    unittest.main()
