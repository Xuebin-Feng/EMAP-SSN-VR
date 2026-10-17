# Copyright 2026 Xuebin Feng
# Licensed under the Apache License, Version 2.0.

"""Generate a layout with the shared pipeline, then launch the VR viewer.

The shared generator's --launch-viewer path targets the desktop viewer and
rewrites settings using its schema. Keep the private VR snapshot intact here.
"""

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

import _bootstrap_vr


def generate(layout_settings, *, delete_settings=False):
    """Use the shared pipeline and return its actual published cache path.

    With ``delete_settings`` the settings file is deleted as soon as it is
    read, before the long generation in which the window may be closed.
    """
    from Layout_Cache_Generator import LayoutGenerationSettings, generate_layout_cache

    settings = LayoutGenerationSettings.from_json_file(layout_settings)
    if delete_settings:
        Path(layout_settings).unlink(missing_ok=True)
    return str(generate_layout_cache(settings).cache_path)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("layout_settings")
    parser.add_argument("--delete-settings", action="store_true")
    args = parser.parse_args(argv)
    snapshot = os.environ.get("SSN_VIEWER_SETTINGS_PATH")
    viewer = Path(_bootstrap_vr.VR_SRC_DIR) / "EMAPSSN_Viewer_VR.py"
    launch_snapshot = None
    try:
        if not snapshot or not Path(snapshot).is_file():
            parser.error("A VR viewer snapshot is required in SSN_VIEWER_SETTINGS_PATH.")
        try:
            with open(snapshot, encoding="utf-8") as handle:
                settings = json.load(handle)
        finally:
            # Deleted before generation: a closed window or a failed run
            # leaves no snapshot behind.
            Path(snapshot).unlink(missing_ok=True)
        cache_path = generate(args.layout_settings, delete_settings=args.delete_settings)
        print(cache_path, flush=True)
        # Automatic cache naming can change while generation is running.
        # Use the pipeline's published path, retaining every other VR value.
        settings["TARGET_CACHE_PATH"] = cache_path
        settings["TARGET_CACHE_MODE"] = "existing"
        descriptor, launch_snapshot = tempfile.mkstemp(prefix="ssn_viewer_", suffix=".json")
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(settings, handle, indent=4)
        viewer_env = dict(os.environ)
        viewer_env["SSN_VIEWER_SETTINGS_PATH"] = launch_snapshot
        for key in ("SSN_TARGET_CACHE", "SSN_TARGET_CACHE_PATH", "SSN_TARGET_CACHE_MODE"):
            viewer_env.pop(key, None)
        return subprocess.call(
            [sys.executable, "-u", str(viewer), "--settings", launch_snapshot, "--delete-settings"],
            # As the desktop viewer starts: relative paths a command is given
            # resolve against the project root, as the settings' do.
            cwd=_bootstrap_vr.PROJECT_ROOT,
            env=viewer_env,
        )
    except Exception as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    finally:
        # The viewer normally consumes this file; also clean it up if it
        # fails before that point.
        if launch_snapshot:
            Path(launch_snapshot).unlink(missing_ok=True)
        if args.delete_settings:
            Path(args.layout_settings).unlink(missing_ok=True)


if __name__ == "__main__":
    _bootstrap_vr.require_windows("The EMAP-SSN VR layout launcher")
    raise SystemExit(main())
