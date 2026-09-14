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

"""Decide which upstream commands the VR viewer can share.

``opt_vr/commands`` falls through to ``src/commands``, so every command sits in
one of three states: shared from upstream, overridden locally, or local-only.
Picking the state by hand does not scale - the previous fork drifted precisely
because nobody re-checked the overrides after upstream moved on. This module
answers the question mechanically, with two probes per command.

**Import probe.** The module is executed behind a meta-path finder that refuses
the GUI toolkits a headless process can never load. A command that reaches
PySide6 or VisPy - directly or anywhere in its import chain - is reported with
the blocking module *and* the project file that pulled it in. Nothing else is
banned: ``desktop.Viewer_State`` is Qt-free and imports cleanly, so the probe
measures real coupling instead of a package blocklist that would go stale.

**Viewer API probe.** Every ``viewer.<attr>`` the module reads is collected from
its AST and checked against the surface the VR viewer actually offers.
Attributes the command assigns itself, and attributes it guards with ``hasattr``
or three-argument ``getattr``, are not requirements - that is the idiom upstream
uses for optional UI hooks, and counting it as a hard dependency would condemn
commands that already degrade gracefully. The viewer surface is derived from
``Viewer.py`` and its siblings by AST rather than from a hand-maintained list,
so it tracks the VR viewer automatically.

Neither probe runs a command, so a clean verdict means "loads, and only touches
API the VR viewer has", not "behaves correctly". This is a drift alarm, not a
substitute for the test suite.

Run it directly for a report::

    python opt_vr/Command_Compatibility.py
    python opt_vr/Command_Compatibility.py --format json
    python opt_vr/Command_Compatibility.py --check

``--check`` enforces the one invariant that must always hold: every command the
dispatcher can reach is loadable. Redundant overrides are reported but never
fail the run, because deleting one is a judgement call rather than a fix.
"""

from __future__ import annotations

import argparse
import ast
import contextlib
import importlib.util
import io
import json
import os
import sys
from dataclasses import dataclass

import _bootstrap

# Imported before probing: this registers the Qt-free stand-in under the name
# upstream modules import as EMAPSSN_Config, which is what lets them load here
# at all. Probing without it would blame PySide6 for nearly every command.
import Settings  # noqa: F401

# matplotlib selects a Qt backend when PySide6 is installed, which would make
# the deny finder blame plotting commands for a toolkit they never asked for.
os.environ.setdefault("MPLBACKEND", "Agg")

PROJECT_ROOT = _bootstrap.PROJECT_ROOT
OPT_VR_DIR = _bootstrap.OPT_VR_DIR
SRC_DIR = _bootstrap.SRC_DIR

UPSTREAM_COMMAND_DIR = os.path.join(SRC_DIR, "commands")
LOCAL_COMMAND_DIR = os.path.join(OPT_VR_DIR, "commands")

#: Toolkits that cannot exist in a process whose renderer is the Unity client.
GUI_PACKAGES = ("PySide6", "PyQt5", "PyQt6", "vispy")

#: Modules that attach attributes to the viewer object at runtime.
VIEWER_PROVIDERS = ("Viewer.py", "Command_Engine.py", "Viewer_Command_Portal.py")

#: The class the VR runtime hands to ``run(viewer, args)``.
VIEWER_CLASS = "HeadlessViewer"

#: The dispatcher contract is ``run(viewer, args)`` for every command module.
VIEWER_PARAM = "viewer"

#: Constructors used to build a stand-in viewer for a background worker.
STANDIN_FACTORIES = ("SimpleNamespace",)

SHARED = "shared"
OVERRIDDEN = "overridden"
LOCAL_ONLY = "local-only"

OK = "ok"
REDUNDANT = "redundant"
BROKEN = "broken"
DEPENDENCY = "dependency"

#: Why a module would not load. Only ``GUI`` is an architectural verdict:
#: ``DEPENDENCY`` means the probe could not finish because a third-party package
#: is not installed, which says nothing about VR compatibility either way.
GUI = "gui"
ERROR = "error"

#: Directories whose modules are the project's own.
_PROJECT_MODULE_DIRS = (SRC_DIR, os.path.join(SRC_DIR, "utilities"), OPT_VR_DIR)

_SELF = os.path.abspath(__file__)


class DesktopOnlyImport(ImportError):
    """Raised by the probe when a command reaches a GUI toolkit."""

    def __init__(self, module_name):
        super().__init__(f"{module_name} is unavailable in a headless VR process")
        self.module_name = module_name


class _GuiDenyFinder:
    """Refuse the GUI toolkits, leaving the importing frame on the traceback."""

    def __init__(self, denied):
        self._denied = frozenset(denied)

    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".")[0] in self._denied:
            raise DesktopOnlyImport(fullname)
        return None


@dataclass(frozen=True)
class Blocker:
    """Why a module would not load, and which project file is responsible."""

    module: str
    source: str | None = None
    detail: str | None = None
    kind: str = ERROR

    def __str__(self):
        if self.kind == DEPENDENCY:
            text = f"{self.module} (not installed)"
        elif self.kind == GUI:
            text = self.module
        else:
            text = f"{self.module}: {self.detail}" if self.detail else self.module
        return f"{text} via {self.source}" if self.source else text


def _relative(path):
    return os.path.relpath(path, PROJECT_ROOT).replace(os.sep, "/")


def _is_project_module(name):
    """True when ``name`` is one of the project's own modules rather than a package.

    A project module that cannot be found is a path bug and counts as a real
    failure; a third-party package that cannot be found is an environment gap.
    """
    root = (name or "").split(".")[0]
    if not root:
        return False
    return any(
        os.path.isfile(os.path.join(directory, root + ".py"))
        or os.path.isdir(os.path.join(directory, root))
        for directory in _PROJECT_MODULE_DIRS
    )


def _blame_frame(traceback_obj):
    """Deepest project frame on a traceback - the file that asked for the import."""
    blamed = None
    while traceback_obj is not None:
        filename = traceback_obj.tb_frame.f_code.co_filename
        absolute = os.path.abspath(filename)
        if (
            absolute.startswith(PROJECT_ROOT)
            and absolute != _SELF
            and "importlib" not in filename
        ):
            blamed = absolute
        traceback_obj = traceback_obj.tb_next
    return _relative(blamed) if blamed else None


# --------------------------------------------------------------------------
# AST probes
# --------------------------------------------------------------------------

def _parse(path):
    with open(path, encoding="utf-8") as handle:
        return ast.parse(handle.read(), filename=path)


def _attribute_access(tree, owners):
    """Return (loaded, stored) attribute names used on any name in ``owners``."""
    loaded, stored = set(), set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Attribute):
            continue
        if not isinstance(node.value, ast.Name) or node.value.id not in owners:
            continue
        if isinstance(node.ctx, ast.Load):
            loaded.add(node.attr)
        else:
            stored.add(node.attr)
    return loaded, stored


def _builtin_access(tree, owners):
    """Classify hasattr/getattr/setattr calls made against ``owners``.

    Returns ``(optional, stored, loaded)``. ``hasattr(viewer, "x")`` and
    ``getattr(viewer, "x", default)`` mean the command copes when the attribute
    is absent, so they are optional. Two-argument ``getattr`` raises on a
    missing attribute, so it stays a genuine requirement.
    """
    optional, stored, loaded = set(), set(), set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
            continue
        args = node.args
        if len(args) < 2:
            continue
        if not (isinstance(args[0], ast.Name) and args[0].id in owners):
            continue
        if not (isinstance(args[1], ast.Constant) and isinstance(args[1].value, str)):
            continue
        attr = args[1].value
        if node.func.id == "hasattr":
            optional.add(attr)
        elif node.func.id == "getattr":
            (optional if len(args) >= 3 else loaded).add(attr)
        elif node.func.id == "setattr":
            stored.add(attr)
    return optional, stored, loaded


def _standin_supplied(tree):
    """Attributes the module supplies on a stand-in viewer it builds itself.

    A command that hands work to a background worker passes a ``SimpleNamespace``
    snapshot, and the worker's parameter is also called ``viewer`` - so its
    attributes look like demands on the real viewer when they are nothing of the
    sort. Only this one constructor is treated this way; a broader rule would
    start hiding genuine desktop-only requirements.
    """
    supplied = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name):
            name = func.id
        elif isinstance(func, ast.Attribute):
            name = func.attr
        else:
            continue
        if name in STANDIN_FACTORIES:
            supplied |= {keyword.arg for keyword in node.keywords if keyword.arg}
    return supplied


def required_viewer_attrs(path):
    """Viewer attributes ``path`` reads without guarding or assigning them first."""
    tree = _parse(path)
    owners = {VIEWER_PARAM}
    loaded, stored = _attribute_access(tree, owners)
    optional, setattr_stored, getattr_loaded = _builtin_access(tree, owners)
    return frozenset(
        (loaded | getattr_loaded)
        - stored
        - setattr_stored
        - optional
        - _standin_supplied(tree)
    )


def viewer_surface(providers=VIEWER_PROVIDERS):
    """Attributes and methods the VR viewer offers, read straight from source."""
    names = set(dir(object))
    for filename in providers:
        path = os.path.join(OPT_VR_DIR, filename)
        if not os.path.isfile(path):
            continue
        tree = _parse(path)

        # Attributes any helper attaches to a parameter named `viewer`.
        _, stored = _attribute_access(tree, {VIEWER_PARAM})
        _, setattr_stored, _ = _builtin_access(tree, {VIEWER_PARAM})
        names |= stored | setattr_stored

        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef) or node.name != VIEWER_CLASS:
                continue
            names |= {
                child.name
                for child in node.body
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
            }
            _, self_stored = _attribute_access(node, {"self"})
            names |= self_stored
    return frozenset(names)


# --------------------------------------------------------------------------
# Import probe
# --------------------------------------------------------------------------

def _rollback(before):
    """Leave imported modules cached; only the probe's own alias is removed.

    An earlier version evicted every project module each probe had loaded, so
    that each command was probed against a cold import graph. That turned out
    to be both unnecessary and harmful.

    Unnecessary, because the question being asked is whether importing a
    command reaches a GUI toolkit, and those imports are at module level: a
    shared module that would have pulled in Qt fails on the first probe that
    touches it and is never cached, so a cached module is by definition one
    that already answered "no".

    Harmful, because evicting a module makes it collectable while numba, torch
    and h5py still hold references into its globals. Probing fifty modules that
    way segfaulted the interpreter during shutdown roughly half the time -
    after the verdict was printed, but early enough to replace the exit code
    with 139, which made the --check gate untrustworthy.
    """
    return


def probe_import(path, alias, denied=GUI_PACKAGES):
    """Execute ``path`` headless. Returns a Blocker, or None when it loads."""
    finder = _GuiDenyFinder(denied)
    sys.meta_path.insert(0, finder)
    before = dict(sys.modules)
    noise = io.StringIO()
    try:
        spec = importlib.util.spec_from_file_location(alias, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[alias] = module
        # Several modules announce themselves on import ("Numba JIT Detected").
        # Probing 50 modules would bury the report in that banner traffic.
        with contextlib.redirect_stdout(noise), contextlib.redirect_stderr(noise):
            spec.loader.exec_module(module)
        return None
    except DesktopOnlyImport as error:
        return Blocker(error.module_name, _blame_frame(sys.exc_info()[2]), kind=GUI)
    except ModuleNotFoundError as error:
        missing = error.name or ""
        return Blocker(
            missing or type(error).__name__,
            _blame_frame(sys.exc_info()[2]),
            str(error) or None,
            kind=ERROR if _is_project_module(missing) else DEPENDENCY,
        )
    except Exception as error:
        return Blocker(
            type(error).__name__,
            _blame_frame(sys.exc_info()[2]),
            str(error) or None,
            kind=ERROR,
        )
    finally:
        sys.meta_path.remove(finder)
        # The alias is an artifact of the probe itself, so it goes regardless of
        # where the file lives - _rollback only sweeps the project tree.
        sys.modules.pop(alias, None)
        _rollback(before)


# --------------------------------------------------------------------------
# Verdicts
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class CommandReport:
    """One command, probed on both sides of the fall-through."""

    name: str
    upstream_path: str | None = None
    local_path: str | None = None
    upstream_blocker: Blocker | None = None
    upstream_missing: tuple = ()
    local_blocker: Blocker | None = None
    local_missing: tuple = ()

    @property
    def upstream_usable(self):
        return (
            self.upstream_path is not None
            and self.upstream_blocker is None
            and not self.upstream_missing
        )

    @property
    def local_usable(self):
        return (
            self.local_path is not None
            and self.local_blocker is None
            and not self.local_missing
        )

    @property
    def state(self):
        """Where the command resolves from today."""
        if self.local_path and self.upstream_path:
            return OVERRIDDEN
        if self.local_path:
            return LOCAL_ONLY
        return SHARED

    @property
    def effective_blocker(self):
        """The blocker on whichever copy the dispatcher would actually reach."""
        return self.local_blocker if self.local_path else self.upstream_blocker

    @property
    def inconclusive(self):
        """True when a probe stopped at an uninstalled third-party package."""
        return any(
            blocker is not None and blocker.kind == DEPENDENCY
            for blocker in (self.upstream_blocker, self.local_blocker)
        )

    @property
    def status(self):
        """``broken`` if the command cannot run; ``redundant`` if it need not exist."""
        effective_ok = self.local_usable if self.local_path else self.upstream_usable
        blocker = self.effective_blocker
        if not effective_ok and not (blocker and blocker.kind == DEPENDENCY):
            return BROKEN
        # An unfinished probe cannot tell compatible from incompatible, and must
        # not be laundered into a clean verdict.
        if self.inconclusive:
            return DEPENDENCY
        if self.state == OVERRIDDEN and self.upstream_usable:
            return REDUNDANT
        return OK

    @property
    def reason(self):
        if self.status == BROKEN:
            side = "local" if self.local_path else "upstream"
            blocker = self.effective_blocker
            missing = self.local_missing if self.local_path else self.upstream_missing
            if blocker:
                return f"{side} copy fails to load: {blocker}"
            return f"{side} copy needs viewer API: {', '.join(missing)}"
        if self.status == DEPENDENCY:
            if self.local_blocker and self.local_blocker.kind == DEPENDENCY:
                return f"inconclusive - local copy needs {self.local_blocker}"
            return f"inconclusive - upstream copy needs {self.upstream_blocker}"
        if self.status == REDUNDANT:
            return "upstream copy is compatible; local override adds nothing"
        if self.state == SHARED:
            return "upstream copy is compatible"
        if self.state == LOCAL_ONLY:
            return "no upstream counterpart"
        if self.upstream_blocker:
            return f"upstream needs {self.upstream_blocker}"
        return "upstream needs viewer API: " + ", ".join(self.upstream_missing)

    def as_dict(self):
        return {
            "name": self.name,
            "state": self.state,
            "status": self.status,
            "reason": self.reason,
            "upstream_blocker": (
                str(self.upstream_blocker) if self.upstream_blocker else None
            ),
            "upstream_missing": list(self.upstream_missing),
            "local_blocker": str(self.local_blocker) if self.local_blocker else None,
            "local_missing": list(self.local_missing),
        }


def _command_modules(directory):
    if not os.path.isdir(directory):
        return {}
    return {
        os.path.splitext(entry)[0]: os.path.join(directory, entry)
        for entry in sorted(os.listdir(directory))
        if entry.endswith(".py") and not entry.startswith("_")
    }


def analyse(names=None, surface=None):
    """Probe every command and return one CommandReport each, sorted by name."""
    upstream = _command_modules(UPSTREAM_COMMAND_DIR)
    local = _command_modules(LOCAL_COMMAND_DIR)
    surface = viewer_surface() if surface is None else surface

    selected = sorted(set(upstream) | set(local)) if names is None else sorted(names)
    reports = []
    for name in selected:
        upstream_path = upstream.get(name)
        local_path = local.get(name)
        reports.append(
            CommandReport(
                name=name,
                upstream_path=upstream_path,
                local_path=local_path,
                upstream_blocker=(
                    probe_import(upstream_path, f"_probe_upstream_{name}")
                    if upstream_path
                    else None
                ),
                upstream_missing=(
                    tuple(sorted(required_viewer_attrs(upstream_path) - surface))
                    if upstream_path
                    else ()
                ),
                local_blocker=(
                    probe_import(local_path, f"_probe_local_{name}")
                    if local_path
                    else None
                ),
                local_missing=(
                    tuple(sorted(required_viewer_attrs(local_path) - surface))
                    if local_path
                    else ()
                ),
            )
        )
    return reports


# --------------------------------------------------------------------------
# Reporting
# --------------------------------------------------------------------------

_STATUS_MARK = {OK: " ", REDUNDANT: "~", BROKEN: "!", DEPENDENCY: "?"}


def render_table(reports, verbose=False):
    width = max([len(report.name) for report in reports] + [len("COMMAND")])
    lines = [
        f"  {'COMMAND'.ljust(width)}  {'STATE'.ljust(11)}  {'STATUS'.ljust(10)}  REASON",
        f"  {'-' * width}  {'-' * 11}  {'-' * 10}  {'-' * 44}",
    ]
    for report in reports:
        lines.append(
            f"{_STATUS_MARK[report.status]} {report.name.ljust(width)}  "
            f"{report.state.ljust(11)}  {report.status.ljust(10)}  {report.reason}"
        )
        if verbose and report.upstream_missing:
            lines.append(
                f"  {' ' * width}  upstream misses: "
                + ", ".join(report.upstream_missing)
            )

    counts = {OK: 0, REDUNDANT: 0, BROKEN: 0, DEPENDENCY: 0}
    for report in reports:
        counts[report.status] += 1
    shared = sum(1 for report in reports if report.state == SHARED)
    lines.append("")
    lines.append(
        f"  {len(reports)} commands: {shared} shared, "
        f"{counts[REDUNDANT]} redundant override(s), {counts[BROKEN]} broken, "
        f"{counts[DEPENDENCY]} inconclusive"
    )
    if counts[REDUNDANT]:
        lines.append(
            "  Redundant overrides can be deleted; fall-through then serves them "
            "from src/commands."
        )
    if counts[DEPENDENCY]:
        missing = sorted(
            {
                blocker.module
                for report in reports
                for blocker in (report.upstream_blocker, report.local_blocker)
                if blocker is not None and blocker.kind == DEPENDENCY
            }
        )
        lines.append(
            "  Install to finish the probe: " + " ".join(missing)
        )
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="Command_Compatibility",
        description="Report which upstream commands the VR viewer can share.",
    )
    parser.add_argument(
        "names", nargs="*", help="commands to probe (default: all of them)"
    )
    parser.add_argument(
        "--format", choices=("table", "json"), default="table", help="output format"
    )
    parser.add_argument(
        "--verbose", action="store_true", help="list the missing viewer attributes"
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="exit non-zero if any command is unreachable",
    )
    options = parser.parse_args(argv)

    reports = analyse(options.names or None)
    if options.format == "json":
        print(json.dumps([report.as_dict() for report in reports], indent=2))
    else:
        print(render_table(reports, verbose=options.verbose))

    if options.check:
        unresolved = [report.name for report in reports if report.status == DEPENDENCY]
        if unresolved:
            # Say so rather than passing quietly: these were never really checked.
            print(
                f"\nNot verified ({len(unresolved)} inconclusive): "
                + ", ".join(unresolved),
                file=sys.stderr,
            )
        broken = [report.name for report in reports if report.status == BROKEN]
        if broken:
            print(f"\nUnreachable commands: {', '.join(broken)}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
