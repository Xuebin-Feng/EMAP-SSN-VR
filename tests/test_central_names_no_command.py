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

"""VR's central code names no command.

What a command is, does or says belongs to its module (its own declarations), the
way the main program's tests/test_command_declarations.py
(CentralCodeNamesNoCommandTests) holds for its central code. This reads the
source of VR's central files and fails when one of them

* holds a string that is a command's name (code, not a docstring or comment),
* holds a table (a dict, set, list or tuple) of two or more command names, or
* imports a command module.

The names are the modules of the main program's src/commands and of opt_vr's own,
so a command added later is covered without editing this test. ALLOWED lists the
few strings that are command names only by coincidence, each with its reason.
"""

import ast
import collections
import os
import unittest

OPT_VR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VR_SRC = os.path.join(OPT_VR, "src")
MAIN_SRC = os.path.join(os.path.dirname(OPT_VR), "src")

CENTRAL_FILES = (
    "Command_Engine.py",
    "EMAPSSN_Viewer_VR.py",
    "_bootstrap_vr.py",
    "Command_Compatibility_VR.py",
)

#: (file, string) -> why the string is not a command being named.
ALLOWED = {
    ("EMAPSSN_Viewer_VR.py", "run"): "the entry point every command module must have (hasattr(module, 'run')), not a command",
    ("EMAPSSN_Viewer_VR.py", "console"): "part of the file name of Godot's console wrapper (<name>.console.exe), not a command",
    ("EMAPSSN_Viewer_VR.py", "alignment"): "the viewer's own attribute holding the loaded alignment (getattr(self, 'alignment')), not a command",
    ("EMAPSSN_Viewer_VR.py", "embedding"): "the viewer's own attribute holding the loaded embedding, not a command",
    ("Command_Engine.py", "alignment"): "the viewer attribute holding the loaded alignment (getattr(viewer, 'alignment')), not a command",
    ("Command_Engine.py", "embedding"): "the viewer attribute holding the loaded embedding, not a command",
}


def command_names():
    """Every command module's name, in the main program's commands and in opt_vr's."""
    names = set()
    for folder in (os.path.join(MAIN_SRC, "commands"), os.path.join(VR_SRC, "commands")):
        for filename in os.listdir(folder):
            if filename.endswith(".py") and not filename.startswith("_"):
                names.add(filename[:-3])
    return names


def command_words_in(source, names):
    """Counter of (kind, name) for every way ``source`` names a command in code."""
    tree = ast.parse(source)
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
                    and isinstance(body[0].value.value, str):
                docstrings.add(id(body[0].value))

    def name_of(node):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings:
            text = node.value.strip().lower()
            if text in names:
                return text
        return None

    found = collections.Counter()
    for node in ast.walk(tree):
        spoken = name_of(node)
        if spoken:
            found[("string", spoken)] += 1
        if isinstance(node, (ast.Dict, ast.Set, ast.List, ast.Tuple)):
            elements = node.keys if isinstance(node, ast.Dict) else node.elts
            listed = sorted({name_of(item) for item in elements if item is not None} - {None})
            if len(listed) >= 2:
                found[("table", ", ".join(listed))] += 1
        if isinstance(node, ast.ImportFrom) and node.module:
            parts = node.module.split(".")
            if parts[0] == "commands":
                if len(parts) > 1 and parts[1] in names:
                    found[("import", parts[1])] += 1
                for alias in node.names:
                    if alias.name in names:
                        found[("import", alias.name)] += 1
        if isinstance(node, ast.Import):
            for alias in node.names:
                parts = alias.name.split(".")
                if parts[0] == "commands" and len(parts) > 1 and parts[1] in names:
                    found[("import", parts[1])] += 1
    return found


class CentralCodeNamesNoCommandTests(unittest.TestCase):
    NAMES = {"jobs", "zoom", "run", "undo", "reset", "color"}

    def test_the_scanner_finds_each_way_of_naming_a_command(self):
        # Positive controls: without them a scanner that finds nothing would pass every file.
        source = (
            '"""A docstring that says zoom."""\n'
            "from commands import zoom\n"
            "import commands.run\n"
            "from commands.undo import steps\n"
            "# a comment that says jobs\n"
            "def f(name):\n"
            "    '''jobs in a docstring'''\n"
            "    if name == 'zoom':\n"
            "        return ('jobs', 'undo')\n"
            "    return {'reset': 1, 'color': 2, 'other': 3}\n"
            "print('a jobs sentence')\n"
        )
        self.assertEqual(command_words_in(source, self.NAMES), collections.Counter({
            ("import", "zoom"): 1, ("import", "run"): 1, ("import", "undo"): 1,
            ("string", "zoom"): 1, ("string", "jobs"): 1, ("string", "undo"): 1,
            ("string", "reset"): 1, ("string", "color"): 1,
            ("table", "jobs, undo"): 1, ("table", "color, reset"): 1,
        }))

    def test_the_names_are_read_from_both_command_folders(self):
        names = command_names()
        self.assertIn("select", names)  # the main program's
        self.assertIn("jobs", names)  # opt_vr's own
        self.assertNotIn("__init__", names)

    def test_every_allowed_entry_is_still_needed(self):
        names = command_names()
        used = set()
        for filename in CENTRAL_FILES:
            with open(os.path.join(VR_SRC, filename), encoding="utf-8") as handle:
                for (kind, name) in command_words_in(handle.read(), names):
                    used.add((filename, name))
        for entry, reason in ALLOWED.items():
            with self.subTest(entry=entry):
                self.assertTrue(reason)
                self.assertIn(entry, used, "no longer found: remove it from ALLOWED")

    def test_central_code_names_no_command(self):
        names = command_names()
        for filename in CENTRAL_FILES:
            with self.subTest(file=filename):
                with open(os.path.join(VR_SRC, filename), encoding="utf-8") as handle:
                    found = command_words_in(handle.read(), names)
                unexpected = sorted(
                    f"{kind} {name}" for (kind, name) in found
                    if not (kind == "string" and (filename, name) in ALLOWED)
                )
                self.assertEqual(unexpected, [], f"{filename} names a command")


if __name__ == "__main__":
    unittest.main()
