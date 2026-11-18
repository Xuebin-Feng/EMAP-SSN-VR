# Copyright 2026 Xuebin Feng
# Author affiliation: University of Toronto
# SPDX-License-Identifier: Apache-2.0

"""The neutral VR settings every VR test module loads, and where they write.

A test module must not read whatever the user last saved, so it points
SSN_VIEWER_SETTINGS_PATH at a settings file made here. The file holds one
choice: the cache folder (CACHE_FILE_DIR) is a folder inside the same
temporary directory. Everything the VR program keeps under ``$cache_file$``
(the command history, the saved configs, the saved layouts) follows it, so a
viewer a test builds writes nowhere inside the project. The temporary
directory is under TMP, which tests/run_sections.py in the project root
points at a private folder it deletes and checks after each section.
"""

import atexit
import json
import os
import tempfile

#: The settings key and the folder name the temporary cache takes.
CACHE_KEY = "CACHE_FILE_DIR"
CACHE_FOLDER = "Cache_Files_VR"


def install(only_if_unset=False):
    """Make the neutral settings file and name it in SSN_VIEWER_SETTINGS_PATH.

    Returns the temporary directory (removed when this process exits), which a
    test may also use for its own scratch files. With ``only_if_unset`` a path
    already named in the environment stays, as the first module imported sets
    it for the whole run.
    """
    directory = tempfile.TemporaryDirectory(prefix="ssn_vr_neutral_")
    atexit.register(directory.cleanup)
    path = os.path.join(directory.name, "viewer_settings.json")
    with open(path, "w", encoding="utf-8") as handle:
        json.dump({CACHE_KEY: os.path.join(directory.name, CACHE_FOLDER)}, handle)
    if only_if_unset:
        os.environ.setdefault("SSN_VIEWER_SETTINGS_PATH", path)
    else:
        os.environ["SSN_VIEWER_SETTINGS_PATH"] = path
    return directory
