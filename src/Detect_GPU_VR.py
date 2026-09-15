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

"""Can this machine drive a headset at all?

The main program's ``Detect_GPU`` answers a different question: which PyTorch
backend to install. That is about compute, and its verdict does not carry over
here - an Intel Arc card is a perfectly good XPU compute target and still
cannot run SteamVR. The Unity client, not Python, is what renders to the
headset, so what matters is the display and runtime stack.

The vendor situation as of September 2026:

* **NVIDIA** - supported.
* **AMD** - supported. SteamVR's own stated floor is roughly an RX 480.
* **Intel Arc** - *not* supported, for either Alchemist (A-series) or
  Battlemage (B-series). SteamVR refuses to start when it detects an Arc GPU,
  and Intel has published no timeline for changing that. Streaming apps such
  as Virtual Desktop are the only route, and they bypass this viewer's client.
* **Intel integrated** (UHD, Iris, HD) - not a VR part.

Scope, deliberately narrow: this says whether the runtime will work with the
hardware *at all*, not whether the hardware is fast enough. Frame-rate
headroom depends on the headset, the scene and the network size, and a checker
that guessed at it would be wrong more often than useful. Model tiers are not
parsed for the same reason.

Inventory comes from the main program's ``Detect_GPU`` rather than a second
enumeration, so both agree about what is installed even when they disagree
about what it is good for.
"""

from __future__ import annotations

import argparse
import re
import sys

import _bootstrap_vr  # noqa: F401  (puts the parent src tree on sys.path)

import Detect_GPU

#: Verdicts, worst last: the report takes the worst one that applies.
READY = "ready"
NO_RUNTIME = "no_runtime"
UNSUPPORTED_GPU = "unsupported_gpu"
UNKNOWN = "unknown"

#: Exit codes for the command line form, so a launcher can branch on them.
EXIT_CODES = {READY: 0, NO_RUNTIME: 11, UNSUPPORTED_GPU: 10, UNKNOWN: 12}

#: Reused from the main program so both modules recognise Arc the same way.
_ARC = re.compile(Detect_GPU.INTEL_ARC_PREFIX, re.IGNORECASE)

_ARC_REASON = (
    "Intel Arc has no SteamVR support - SteamVR refuses to start when it "
    "detects one, for both A-series and B-series, and Intel has announced no "
    "timeline. Only streaming apps such as Virtual Desktop work, and they "
    "bypass this viewer's Unity client."
)
_INTEL_INTEGRATED_REASON = "Intel integrated graphics cannot drive a headset."
_UNKNOWN_REASON = "Unrecognised graphics adapter; treating VR support as unknown."


def classify(device):
    """Return ``(capable, reason)`` for one device from ``Detect_GPU``.

    ``capable`` is True, False, or None where the adapter is not recognised -
    None is not False, and the caller must not turn "I do not know" into "this
    will not work".
    """
    name = str(device.get("name") or "")
    vendor = str(device.get("vendor") or "").upper()

    if vendor == "NVIDIA":
        return True, "NVIDIA GPUs are supported by SteamVR and OpenXR."
    if vendor == "AMD":
        return True, "AMD GPUs are supported by SteamVR (RX 480 or newer)."
    if vendor == "INTEL":
        if _ARC.search(name):
            return False, _ARC_REASON
        return False, _INTEL_INTEGRATED_REASON
    return None, _UNKNOWN_REASON


def active_openxr_runtime():
    """The OpenXR runtime registered on this machine, or None.

    A headset is reached through whatever runtime holds this registry key -
    SteamVR, or the Oculus/Meta one. Its absence means nothing is installed to
    talk to a headset with, however good the GPU is.
    """
    if sys.platform != "win32":
        return None
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Khronos\OpenXR\1"
        ) as key:
            value, _kind = winreg.QueryValueEx(key, "ActiveRuntime")
    except OSError:
        return None
    return str(value) or None


def runtime_name(path):
    """A readable name for a runtime manifest path."""
    if not path:
        return None
    lowered = path.lower()
    if "steamxr" in lowered or "steamvr" in lowered:
        return "SteamVR"
    if "oculus" in lowered:
        return "Oculus/Meta"
    if "windowsmr" in lowered or "mixedreality" in lowered:
        return "Windows Mixed Reality"
    if "varjo" in lowered:
        return "Varjo"
    return "an OpenXR runtime"


def installed_adapters():
    """Every display adapter, by name and vendor.

    Deliberately not ``Detect_GPU.detect_hardware()``: that runs several
    PowerShell queries and takes about four seconds here, because it is also
    working out driver versions, ROCm agents and a PyTorch backend. None of
    that bears on whether a headset will work. Asking only for the adapter
    names costs about a tenth of it, which is what makes this cheap enough to
    run on every launch.
    """
    system = "windows" if sys.platform == "win32" else sys.platform
    return [
        {"name": name, "vendor": Detect_GPU._vendor(name), "kind": None}
        for name in Detect_GPU._controller_names(system)
    ]


def check(hardware=None):
    """Assess this machine's ability to run the VR client.

    Pass ``hardware`` - a report from the main program's ``detect_hardware`` -
    to reuse an inventory a caller already paid for; otherwise the cheap
    adapter listing above is used.
    """
    devices = (
        (hardware.get("devices") or ()) if hardware is not None else installed_adapters()
    )

    assessed = []
    for device in devices:
        capable, reason = classify(device)
        assessed.append(
            {
                "name": device.get("name"),
                "vendor": device.get("vendor"),
                "kind": device.get("kind"),
                "vr_capable": capable,
                "reason": reason,
            }
        )

    capable = [entry for entry in assessed if entry["vr_capable"] is True]
    unknown = [entry for entry in assessed if entry["vr_capable"] is None]
    runtime = active_openxr_runtime()

    if capable:
        verdict = READY if runtime else NO_RUNTIME
    elif unknown:
        verdict = UNKNOWN
    elif assessed:
        verdict = UNSUPPORTED_GPU
    else:
        verdict = UNKNOWN

    return {
        "verdict": verdict,
        "devices": assessed,
        "vr_capable_devices": capable,
        "openxr_runtime": runtime,
        "runtime_name": runtime_name(runtime),
    }


def summary(report):
    """One or two lines describing `report`, suitable for a console or a label."""
    verdict = report["verdict"]
    capable = report["vr_capable_devices"]
    if verdict == READY:
        return (
            f"VR hardware: {capable[0]['name']} with "
            f"{report['runtime_name']}."
        )
    if verdict == NO_RUNTIME:
        return (
            f"VR hardware: {capable[0]['name']} is supported, but no OpenXR "
            "runtime is registered. Install SteamVR (or your headset's own "
            "runtime) before launching the viewer."
        )
    if verdict == UNSUPPORTED_GPU:
        listed = ", ".join(entry["name"] or "unknown" for entry in report["devices"])
        reason = report["devices"][0]["reason"] if report["devices"] else ""
        return f"No VR-capable GPU found ({listed}). {reason}"
    return (
        "Could not tell whether this machine can drive a headset. "
        "The viewer will still start; the Unity client is what needs the GPU."
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="print nothing; report the verdict through the exit code alone",
    )
    parser.add_argument(
        "--json", action="store_true", help="print the full report as JSON"
    )
    args = parser.parse_args(argv)

    report = check()
    if args.json:
        import json

        print(json.dumps(report, indent=2))
    elif not args.quiet:
        print(summary(report))
        for entry in report["devices"]:
            mark = {True: "ok", False: "no", None: "??"}[entry["vr_capable"]]
            print(f"  [{mark}] {entry['name']}")
            if entry["vr_capable"] is not True:
                print(f"       {entry['reason']}")
    return EXIT_CODES[report["verdict"]]


if __name__ == "__main__":
    raise SystemExit(main())
