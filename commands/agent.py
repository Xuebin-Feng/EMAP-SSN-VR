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

"""Explain that the LLM agent is desktop-only, instead of crashing.

The main program's ``agent`` is a thin portal onto ``web_ui.agent_backend``:
every path through it needs the Viewer web server. ``agent`` on its own calls
``viewer.open_agent_ui()`` to open a browser tab, and forwarding a message
calls ``viewer.broadcast_event()`` to stream the agent's replies to that tab.
Neither method exists on ``HeadlessViewer``, and the web UI is explicitly out
of scope for this port, so the upstream command cannot be made to work here -
it raises AttributeError and dumps a traceback over the terminal, which is the
only output surface the VR viewer has.

This module shadows it so the user gets one clear sentence instead.
"""

import Command_Engine

MESSAGE = """The LLM agent is not available in the VR viewer.

Why:
  The agent is driven entirely through the Viewer's browser UI - it opens a
  web page and streams the model's replies back to it over the web server.
  The VR viewer is headless: it has no browser UI and no web server, and the
  web UI is out of scope for this port.

What to use instead:
  - Run the agent in the desktop EMAP-SSN viewer, which has the web UI. A
    layout saved there with 'save' can be loaded back into VR.
  - Type the commands directly here. 'help' lists every command available in
    this viewer, and 'help <command>' describes one.
"""


def run(viewer, args):
    Command_Engine.print_help(viewer, MESSAGE)
