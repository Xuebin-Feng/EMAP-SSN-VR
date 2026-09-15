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

"""Let only one VR viewer run at a time.

Two viewers cannot usefully coexist. They drive the same headset through the
same Unity client, and they listen on the same endpoint - which the client
dials by an address compiled into its build, so it cannot be told to reach the
other one. A second viewer therefore does not give you a second view; it gives
you two processes fighting over one client, with whichever won the bind
receiving the connection.

The desktop program takes the opposite position deliberately: its Config and
Tools windows guard themselves with Qt's ``SingleInstanceController``, and its
viewer may legitimately be opened more than once because each instance owns its
own window. Nothing here owns a window.

A Windows named mutex is used rather than a lock file because the kernel
releases it when the holding process dies, however it died. A lock file would
need staleness detection, and a stale lock that refuses to start the viewer is
a worse failure than the one being prevented.

The handle has to outlive this call - closing it releases the mutex - so the
caller keeps what ``acquire`` returns for as long as it wants to stay the only
instance.
"""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes

#: Session-local, so two different desktop sessions on one machine - a remote
#: desktop beside a console login - each get their own viewer.
MUTEX_NAME = "Local\\EMAP-SSN-VR-Viewer"

_ERROR_ALREADY_EXISTS = 183

BUSY_MESSAGE = (
    "Another EMAP-SSN VR viewer is already running.\n"
    "Only one can run at a time: both would drive the same Unity client and "
    "listen on the same endpoint.\n"
    "Close the other viewer, then start this one again."
)


def _kernel32():
    library = ctypes.WinDLL("kernel32", use_last_error=True)
    library.CreateMutexW.argtypes = (wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR)
    library.CreateMutexW.restype = wintypes.HANDLE
    library.CloseHandle.argtypes = (wintypes.HANDLE,)
    library.CloseHandle.restype = wintypes.BOOL
    return library


def acquire(name=MUTEX_NAME):
    """Claim the single-instance handle, or return None if one is held.

    Returning None rather than raising keeps the decision with the caller: the
    viewer turns it into an explanation and a clean exit, while a test only
    wants to know which of two calls won.
    """
    if sys.platform != "win32":
        # Nothing to guard: every VR entry point refuses to start off Windows
        # long before this is reached.
        return None
    library = _kernel32()
    ctypes.set_last_error(0)
    handle = library.CreateMutexW(None, True, name)
    if not handle:
        raise OSError(ctypes.get_last_error(), "Could not create the VR instance lock")
    if ctypes.get_last_error() == _ERROR_ALREADY_EXISTS:
        # Someone else owns it. Drop this handle or the mutex would outlive
        # the process that failed to take it.
        library.CloseHandle(handle)
        return None
    return handle


def release(handle):
    """Give the single-instance handle back, so another viewer may start."""
    if not handle or sys.platform != "win32":
        return
    _kernel32().CloseHandle(handle)
