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

"""Not available in the VR viewer: Tree View needs the desktop viewer.

Running it explains why and what to use instead, rather than crashing.

Tree View is a page of the Viewer web server. The main program's ``tree``
registers its Console button through ``web_ui.tree_backend``, asks the viewer to
open the page (``viewer.open_page``) and reports where the page is served. It
imports ``web_ui.Browser_Page`` for that, and ``Browser_Page`` reaches PySide6,
so the upstream module cannot even be loaded here: the compatibility check
reports it broken, and a command that is reachable but cannot load is the one
state that check refuses.

The VR viewer is headless and owns no web server, no browser and no Qt, and the
web UI is out of scope for this port, so there is nothing to open the page in.

This module shadows it so the user gets one clear sentence instead.
"""

import Command_Engine

MESSAGE = """Tree View is not available in the VR viewer.

Why:
  Tree View is a page served by the Viewer web server and shown in a browser
  tab: it draws the guide tree of the loaded alignment beside the network. The
  VR viewer is headless - no web server and no browser - and the web UI is out
  of scope for this port.

What to use instead:
  - Run 'tree' in the desktop EMAP-SSN viewer, which has the web UI. The tree
    it draws is the one the Embedding MSA tool saved in the Guide_Trees folder
    beside the alignment.
  - That tree is an ordinary NEXUS file, so it can also be opened outside
    EMAP-SSN.
"""


def run(viewer, args):
    Command_Engine.print_help(viewer, MESSAGE)
    Command_Engine.command_failed(viewer, "tree is not available in the VR viewer.")
