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

"""Explain that figure export is not wired up yet, instead of crashing.

The main program's ``print`` renders the VisPy canvas: it reads
``viewer.canvas``, drives ``viewer.view.camera`` and calls ``canvas.render()``
to grab pixels. None of that exists here - the VR viewer is headless and the
headset owns the viewpoint - so the upstream command dies with an
AttributeError before writing anything, which reads as a bug rather than as
"wrong viewer".

This module shadows it so the user gets one clear sentence instead. Figure
export from a VR session is wanted and is deliberately deferred rather than
abandoned: because the layout is three dimensional and there is no camera to
screen-grab, a VR figure has to be rebuilt from the state arrays and projected
onto a chosen plane, which is a different command from upstream's rather than
a port of it. Until that is designed, refusing plainly beats shipping a
figure whose framing and projection nobody has agreed on.
"""

import Command_Engine

MESSAGE = """print is not available in the VR viewer yet.

Why:
  Upstream's 'print' is a screenshot: it points the desktop viewer's VisPy
  camera at the network and grabs the canvas pixels. This process is headless
  and the headset owns the viewpoint, so there is no canvas to capture and no
  camera whose framing a figure could inherit.

What to use instead, for now:
  - Open the same layout in the desktop EMAP-SSN viewer and run 'print' there.
    'save' writes a cache that carries colours, sizes, clusters, groups and
    hidden nodes across, so the figure matches this session's state.
  - 'export' writes the sequence subsets themselves as FASTA files.
"""


def run(viewer, args):
    Command_Engine.print_help(viewer, MESSAGE)
    Command_Engine.command_failed(viewer, "print is not available in the VR viewer yet.")
