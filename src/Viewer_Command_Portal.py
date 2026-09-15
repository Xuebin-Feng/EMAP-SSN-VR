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

"""Qt-free stand-in for the main program's command portal.

Upstream commands call ``Command_Engine.command_succeeded`` and friends on
every code path, and those delegate to ``Viewer_Command_Portal.report``. The
main program's module imports PySide6 for its ``QObject``-based portal, which
would drag Qt into this headless process, so opt_vr ships this shim instead.
Because opt_vr precedes ``src`` on ``sys.path``, ``import
Viewer_Command_Portal`` resolves here.

The semantics that matter are preserved exactly: ``report`` is a no-op unless
an execution context is bound, and interactive typing never binds one. The VR
viewer therefore behaves like the desktop viewer's manual path - the user sees
terminal output, and the structured request/response channel stays inert.

That structured channel belongs to the web UI and MCP server, both explicitly
out of scope for the VR port. If either is ever wired up here, this shim is
the single place to grow.
"""

from __future__ import annotations

import os
import sys
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone

CURRENT = ContextVar("viewer_command_context", default=None)


def now():
    return datetime.now(timezone.utc).isoformat()


class CommandInteractionError(RuntimeError):
    """Raised when a command needs user input that this front end cannot give."""


def install_output_capture():
    """No-op: the VR viewer has no structured output channel to tee into.

    Kept so upstream code that calls it during start-up does not fail.
    """
    return None


@contextmanager
def bind(context):
    token = CURRENT.set(context)
    try:
        yield
    finally:
        CURRENT.reset(token)


def report(status=None, message=None, artifact=None, viewer=None):
    """Forward an outcome to the bound context, if any.

    Nothing is bound during interactive use, so this is a no-op in the VR
    terminal - which is what makes it safe for upstream commands to call it
    unconditionally.
    """
    context = CURRENT.get()
    if context is None:
        return
    portal = getattr(context, "portal", None)
    if viewer is not None and portal is not None:
        if getattr(portal, "viewer", None) is not viewer:
            return
    context.report(status, message, artifact)


@contextmanager
def user_interaction(viewer, description):
    """Guard a command that needs a dialog the VR viewer cannot show."""
    context = CURRENT.get()
    if context is not None:
        headless = (
            os.environ.get("SSN_VIEWER_HEADLESS") == "1"
            or os.environ.get("QT_QPA_PLATFORM") == "offscreen"
        )
        if headless:
            raise CommandInteractionError(
                f"{description} requires a visible Viewer and user input."
            )
    yield


def get_portal(viewer):
    """No portal exists in the VR viewer; upstream callers tolerate None."""
    return None
