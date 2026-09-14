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

"""VR viewer commands, with fall-through to the main program's command set.

A command is a module in this package exposing ``run(viewer, args)``; the
module basename is the command name. That is the same contract the desktop
viewer uses, so the two command sets are interchangeable.

This package's search path is extended with the main program's
``src/commands`` directory. A module defined here wins, and anything not
overridden resolves to the upstream implementation. That gives a single
migration seam: as an upstream command is verified against the VR
architecture, the local copy is simply deleted and upstream's takes over with
no dispatcher change.

Not every upstream command can work here - some drive the VisPy canvas or a Qt
dialog that does not exist in a headless process. Those fail at import with a
clear "missing dependency" message rather than silently misbehaving.
"""

import os

import _bootstrap

_UPSTREAM_COMMANDS = os.path.join(_bootstrap.SRC_DIR, "commands")
if os.path.isdir(_UPSTREAM_COMMANDS) and _UPSTREAM_COMMANDS not in __path__:
    __path__.append(_UPSTREAM_COMMANDS)
