"""The shared generator must hand back to VR without losing its settings."""

import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

#: Guarded, like every other test module here. An unconditional insert put a
#: second copy of opt_vr/src on sys.path, and because unittest discovery runs
#: every module in one interpreter, that duplicate was still there when
#: BootstrapTests later asserted the path holds exactly one.
VR_SRC = str(Path(__file__).resolve().parents[1] / "src")
if VR_SRC not in sys.path:
    sys.path.insert(0, VR_SRC)
import Layout_Launcher_VR as launcher


class LayoutLauncherTests(unittest.TestCase):
    def test_success_preserves_snapshot_and_launches_vr(self):
        with tempfile.TemporaryDirectory() as folder:
            snapshot = Path(folder) / "viewer.json"
            layout = Path(folder) / "layout.json"
            payload = {"EXIT_WITH_UNITY": False, "VR_PORT": 6123,
                       "TARGET_CACHE_PATH": str(Path(folder) / "new.h5")}
            snapshot.write_text(json.dumps(payload), encoding="utf-8")
            layout.write_text("{}", encoding="utf-8")
            published = str(Path(folder) / "new_version_2.h5")
            calls = []

            def run(command, **kwargs):
                calls.append((command, kwargs))
                self.assertEqual(json.loads(snapshot.read_text(encoding="utf-8")),
                                 {**payload, "TARGET_CACHE_PATH": published, "TARGET_CACHE_MODE": "existing"})
                self.assertEqual(Path(command[2]), Path(launcher._bootstrap_vr.VR_SRC_DIR) / "EMAPSSN_Viewer_VR.py")
                self.assertEqual(command[3:], ["--settings", str(snapshot), "--delete-settings"])
                self.assertEqual(kwargs["env"]["SSN_VIEWER_SETTINGS_PATH"], str(snapshot))
                self.assertNotIn("SSN_TARGET_CACHE", kwargs["env"])
                return 7

            with mock.patch.dict(os.environ, {"SSN_VIEWER_SETTINGS_PATH": str(snapshot), "SSN_TARGET_CACHE": "stale"}), mock.patch.object(launcher, "generate", return_value=published) as generate, mock.patch.object(launcher.subprocess, "call", side_effect=run):
                self.assertEqual(launcher.main([str(layout), "--delete-settings"]), 7)
                generate.assert_called_once_with(str(layout))
            self.assertEqual(len(calls), 1)
            self.assertFalse(snapshot.exists())
            self.assertFalse(layout.exists())

    def test_generation_failure_does_not_launch_viewer_and_cleans_snapshots(self):
        for outcome in (ValueError("invalid layout settings"), OSError("could not generate cache")):
            with self.subTest(outcome=outcome), tempfile.TemporaryDirectory() as folder:
                snapshot = Path(folder) / "viewer.json"
                layout = Path(folder) / "layout.json"
                snapshot.write_text("{}", encoding="utf-8")
                layout.write_text("{}", encoding="utf-8")
                with mock.patch.dict(os.environ, {"SSN_VIEWER_SETTINGS_PATH": str(snapshot)}), mock.patch.object(launcher, "generate", side_effect=outcome), mock.patch.object(launcher.subprocess, "call") as run:
                    self.assertEqual(launcher.main([str(layout), "--delete-settings"]), 1)
                    run.assert_not_called()
                self.assertFalse(snapshot.exists())
                self.assertFalse(layout.exists())

    def test_generation_delegates_to_the_shared_pipeline(self):
        pipeline = SimpleNamespace(
            LayoutGenerationSettings=mock.Mock(),
            generate_layout_cache=mock.Mock(return_value=SimpleNamespace(cache_path=Path("published.h5"))),
        )
        with mock.patch.dict(sys.modules, {"Layout_Cache_Generator": pipeline}):
            self.assertEqual(launcher.generate("layout.json"), "published.h5")
        pipeline.LayoutGenerationSettings.from_json_file.assert_called_once_with("layout.json")
        pipeline.generate_layout_cache.assert_called_once_with(
            pipeline.LayoutGenerationSettings.from_json_file.return_value
        )


if __name__ == "__main__":
    unittest.main()
