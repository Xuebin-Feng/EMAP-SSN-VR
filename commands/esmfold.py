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

"""Explain that structure prediction is desktop-only, instead of crashing.

The main program's ``esmfold`` is wired to the Viewer web server from end to
end. It registers a sidebar button through ``web_ui.esmfold_backend``, asks
the viewer for ``get_web_url("/api/action")`` - the address the background
folding worker posts its results back to - and finishes by opening the Mol*
structure viewer in a browser tab. It also imports ``QMessageBox`` to report
failures in a Qt dialog.

None of that survives here: the VR viewer is headless, owns no web server and
no Qt, and the web UI is out of scope for this port. Run through the
fall-through, the upstream command raises AttributeError inside the backend
registration and prints a traceback before it ever reaches the folding step,
which reads as a bug rather than as "wrong viewer".

This module shadows it so the user gets one clear sentence instead.
"""

import Command_Engine

MESSAGE = """ESM3 structure prediction is not available in the VR viewer.

Why:
  Folding is driven through the Viewer web server: the background worker
  reports progress back to a /api/action URL, and the predicted structure is
  displayed in the Mol* viewer in a browser tab. The VR viewer is headless -
  no web server, no browser, and no channel to Unity for 3D structures - and
  the web UI is out of scope for this port.

What to use instead:
  - Select the nodes in the desktop EMAP-SSN viewer and run 'esmfold' there.
    Structures land in the shared Analysis Results directory, so a VR session
    and a desktop session fold into the same place.
  - To take sequences out of this session, 'export' writes cluster or group
    subsets as FASTA files you can fold with any external tool.
"""


def run(viewer, args):
    Command_Engine.print_help(viewer, MESSAGE)
