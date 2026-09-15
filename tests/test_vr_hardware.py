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

"""Tests for the VR hardware check.

The verdict that actually costs a user an afternoon is Intel Arc: it is a
capable compute device, the main program will happily pick it as an XPU
backend, and SteamVR still refuses to start when it sees one. So the Arc cases
are pinned by model name across both generations, and the check is kept
independent of the compute-backend question it is easily confused with.

Everything is driven from synthetic inventories. Reading the real machine would
make these describe whichever GPU the suite happens to run on.
"""

import io
import os
import sys
import unittest
from contextlib import redirect_stdout
from unittest import mock

OPT_VR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VR_SRC = os.path.join(OPT_VR, "src")
if VR_SRC not in sys.path:
    sys.path.insert(0, VR_SRC)

import _bootstrap_vr  # noqa: E402,F401

import Detect_GPU_VR as vr_gpu  # noqa: E402

STEAMVR = r"C:\Program Files (x86)\Steam\steamapps\common\SteamVR\steamxr_win64.json"


def device(name, vendor):
    return {"name": name, "vendor": vendor, "kind": None}


def report_for(devices, runtime=STEAMVR):
    with mock.patch.object(vr_gpu, "active_openxr_runtime", return_value=runtime):
        return vr_gpu.check({"devices": devices})


class ClassifyTests(unittest.TestCase):
    def test_nvidia_and_amd_are_supported(self):
        for name, vendor in (
            ("NVIDIA GeForce RTX 4070", "NVIDIA"),
            ("NVIDIA GeForce GTX 1660 SUPER", "NVIDIA"),
            ("AMD Radeon RX 7900 XTX", "AMD"),
            ("AMD Radeon RX 6700 XT", "AMD"),
        ):
            with self.subTest(name=name):
                capable, _reason = vr_gpu.classify(device(name, vendor))
                self.assertIs(capable, True)

    def test_every_intel_arc_generation_is_refused(self):
        """The expensive mistake: Arc is a fine compute device and no use here."""
        for name in (
            "Intel(R) Arc(TM) A770 Graphics",
            "Intel(R) Arc(TM) A750 Graphics",
            "Intel(R) Arc(TM) A380 Graphics",
            "Intel(R) Arc(TM) B580 Graphics",
            "Intel(R) Arc(TM) B570 Graphics",
            "Intel(R) Arc(TM) Graphics",
        ):
            with self.subTest(name=name):
                capable, reason = vr_gpu.classify(device(name, "INTEL"))
                self.assertIs(capable, False)
                self.assertIn("SteamVR", reason)
                self.assertIn("Virtual Desktop", reason)

    def test_intel_integrated_is_refused_for_its_own_reason(self):
        capable, reason = vr_gpu.classify(
            device("Intel(R) UHD Graphics 770", "INTEL")
        )
        self.assertIs(capable, False)
        self.assertIn("integrated", reason)
        # Not the Arc explanation: it would be a misleading thing to read.
        self.assertNotIn("Virtual Desktop", reason)

    def test_an_unrecognised_adapter_is_unknown_not_refused(self):
        capable, _reason = vr_gpu.classify(device("Basic Display Adapter", "CPU"))
        self.assertIsNone(capable, "not knowing must not be reported as knowing")


class VerdictTests(unittest.TestCase):
    def test_a_supported_gpu_with_a_runtime_is_ready(self):
        report = report_for([device("NVIDIA GeForce RTX 4070", "NVIDIA")])
        self.assertEqual(report["verdict"], vr_gpu.READY)
        self.assertEqual(report["runtime_name"], "SteamVR")

    def test_a_supported_gpu_without_a_runtime_says_so(self):
        report = report_for([device("AMD Radeon RX 7900 XTX", "AMD")], runtime=None)
        self.assertEqual(report["verdict"], vr_gpu.NO_RUNTIME)
        self.assertIn("no OpenXR runtime", vr_gpu.summary(report))

    def test_arc_alone_is_an_unsupported_machine(self):
        report = report_for([device("Intel(R) Arc(TM) B580 Graphics", "INTEL")])
        self.assertEqual(report["verdict"], vr_gpu.UNSUPPORTED_GPU)
        self.assertIn("No VR-capable GPU", vr_gpu.summary(report))

    def test_a_supported_card_beside_an_unsupported_one_is_ready(self):
        """The common desktop: a discrete card plus the chipset's integrated one."""
        report = report_for(
            [
                device("Intel(R) UHD Graphics 770", "INTEL"),
                device("NVIDIA GeForce RTX 4070", "NVIDIA"),
            ]
        )
        self.assertEqual(report["verdict"], vr_gpu.READY)
        self.assertEqual(len(report["vr_capable_devices"]), 1)

    def test_an_unknown_adapter_does_not_read_as_unsupported(self):
        report = report_for([device("Basic Display Adapter", "CPU")])
        self.assertEqual(report["verdict"], vr_gpu.UNKNOWN)

    def test_an_empty_inventory_is_unknown(self):
        self.assertEqual(report_for([])["verdict"], vr_gpu.UNKNOWN)

    def test_every_verdict_has_an_exit_code_and_a_summary(self):
        for verdict in (
            vr_gpu.READY,
            vr_gpu.NO_RUNTIME,
            vr_gpu.UNSUPPORTED_GPU,
            vr_gpu.UNKNOWN,
        ):
            with self.subTest(verdict=verdict):
                self.assertIn(verdict, vr_gpu.EXIT_CODES)
        self.assertEqual(vr_gpu.EXIT_CODES[vr_gpu.READY], 0, "ready must exit clean")
        self.assertNotIn(
            0, [code for name, code in vr_gpu.EXIT_CODES.items() if name != vr_gpu.READY]
        )


class RuntimeNameTests(unittest.TestCase):
    def test_known_runtimes_are_named(self):
        for path, expected in (
            (STEAMVR, "SteamVR"),
            (r"C:\Program Files\Oculus\Support\oculus-runtime\oculus_openxr_64.json",
             "Oculus/Meta"),
            (r"C:\Windows\System32\WindowsMRRuntime.json", "Windows Mixed Reality"),
        ):
            with self.subTest(path=path):
                self.assertEqual(vr_gpu.runtime_name(path), expected)

    def test_an_unfamiliar_runtime_is_still_a_runtime(self):
        self.assertEqual(vr_gpu.runtime_name(r"C:\vendor\thing.json"), "an OpenXR runtime")

    def test_no_runtime_has_no_name(self):
        self.assertIsNone(vr_gpu.runtime_name(None))


class CommandLineTests(unittest.TestCase):
    def test_the_exit_code_reports_the_verdict(self):
        arc = [device("Intel(R) Arc(TM) A770 Graphics", "INTEL")]
        with mock.patch.object(
            vr_gpu, "installed_adapters", return_value=arc
        ), mock.patch.object(vr_gpu, "active_openxr_runtime", return_value=STEAMVR):
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                code = vr_gpu.main([])
        self.assertEqual(code, vr_gpu.EXIT_CODES[vr_gpu.UNSUPPORTED_GPU])
        self.assertIn("Arc", buffer.getvalue())

    def test_quiet_prints_nothing(self):
        with mock.patch.object(
            vr_gpu, "installed_adapters", return_value=[device("RTX 4070", "NVIDIA")]
        ), mock.patch.object(vr_gpu, "active_openxr_runtime", return_value=STEAMVR):
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                code = vr_gpu.main(["--quiet"])
        self.assertEqual(code, 0)
        self.assertEqual(buffer.getvalue(), "")


class SeparationFromComputeTests(unittest.TestCase):
    """VR capability is not the PyTorch backend question, and must not drift into it."""

    def test_arc_is_a_compute_target_and_still_not_vr_capable(self):
        import Detect_GPU

        name = "Intel(R) Arc(TM) A770 Graphics"
        # The main program recognises this as an XPU candidate...
        self.assertTrue(
            any(
                __import__("re").search(pattern, name.lower())
                for pattern in Detect_GPU.INTEL_XPU_PATTERNS
            )
        )
        # ...and it is still no use for a headset.
        self.assertIs(vr_gpu.classify(device(name, "INTEL"))[0], False)

    def test_the_arc_pattern_is_the_main_program_s_own(self):
        import Detect_GPU

        self.assertEqual(vr_gpu._ARC.pattern, Detect_GPU.INTEL_ARC_PREFIX)


if __name__ == "__main__":
    unittest.main()
