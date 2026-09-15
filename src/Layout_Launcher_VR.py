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

import _bootstrap_vr


def generate(layout_settings):
    """Use the shared pipeline and return its actual published cache path."""
    from Layout_Cache_Generator import LayoutGenerationSettings, generate_layout_cache

    settings = LayoutGenerationSettings.from_json_file(layout_settings)
    return str(generate_layout_cache(settings).cache_path)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("layout_settings")
    parser.add_argument("--delete-settings", action="store_true")
    args = parser.parse_args(argv)
    snapshot = os.environ.get("SSN_VIEWER_SETTINGS_PATH")
    if not snapshot or not Path(snapshot).is_file():
        parser.error("A VR viewer snapshot is required in SSN_VIEWER_SETTINGS_PATH.")

    viewer = Path(_bootstrap_vr.VR_SRC_DIR) / "EMAPSSN_Viewer_VR.py"
    try:
        with open(snapshot, encoding="utf-8") as handle:
            settings = json.load(handle)
        cache_path = generate(args.layout_settings)
        print(cache_path, flush=True)
        # Automatic cache naming can change while generation is running.
        # Use the pipeline's published path, retaining every other VR value.
        settings["TARGET_CACHE_PATH"] = cache_path
        settings["TARGET_CACHE_MODE"] = "existing"
        with open(snapshot, "w", encoding="utf-8") as handle:
            json.dump(settings, handle, indent=4)
        viewer_env = dict(os.environ)
        for key in ("SSN_TARGET_CACHE", "SSN_TARGET_CACHE_PATH", "SSN_TARGET_CACHE_MODE"):
            viewer_env.pop(key, None)
        return subprocess.call(
            [sys.executable, "-u", str(viewer), "--settings", snapshot, "--delete-settings"],
            cwd=_bootstrap_vr.OPT_VR_DIR,
            env=viewer_env,
        )
    except Exception as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    finally:
        # The viewer normally consumes this file; also clean it up if either
        # subprocess fails before that point.
        Path(snapshot).unlink(missing_ok=True)
        if args.delete_settings:
            Path(args.layout_settings).unlink(missing_ok=True)


if __name__ == "__main__":
    _bootstrap_vr.require_windows("The EMAP-SSN VR layout launcher")
    raise SystemExit(main())
