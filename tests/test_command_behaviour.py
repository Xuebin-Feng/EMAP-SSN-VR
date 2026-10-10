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

"""What shared commands actually do in the headless viewer.

The compatibility probe reads source: a guarded ``getattr`` counts as
optional and a method that does nothing counts as present, so it passed while
`hide` never reached the headset, `label` and `logo` stopped at a missing
scheduler and `undo` left a deleted metadata column deleted. These run the
commands through the terminal's own dispatcher and check the effect: the
packets queued for the client, the files written and the state restored.
"""

import io
import json
import os
import shutil
import socket
import sys
import tempfile
import threading
import time
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

OPT_VR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VR_SRC = os.path.join(OPT_VR, "src")
if VR_SRC not in sys.path:
    sys.path.insert(0, VR_SRC)

_NEUTRAL = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
json.dump({}, _NEUTRAL)
_NEUTRAL.close()
os.environ.setdefault("SSN_VIEWER_SETTINGS_PATH", _NEUTRAL.name)

import numpy as np  # noqa: E402

import _bootstrap_vr  # noqa: E402
import Settings_VR as cfg  # noqa: E402

with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
    import Background_Job_Scheduler_VR  # noqa: E402
    import Command_Engine  # noqa: E402
    import EMAPSSN_Viewer_VR as vr_viewer  # noqa: E402
    import Viewer_Command_Portal  # noqa: E402

_bootstrap_vr.install_settings_alias(cfg)

from tests.cache_fixtures import publish_cache, use_inputs  # noqa: E402
from tests.test_opt_vr import build_viewer, run_command  # noqa: E402

#: A small alignment; its first row is the reference.
ALIGNED_ROWS = ("MKT-AYIAKQ", "MKTLAYIAKQ", "MRT-AYLAKQ", "MKT-GYIAKE", "MKS-AYIARQ", "MKT-AYIVKQ")
#: The network's canonical headers for ALIGNED_ROWS.
ALIGNED_HEADERS = tuple(f"sp|P{index:05d}|PROT{index}_TEST" for index in range(len(ALIGNED_ROWS)))


def write_msa(folder):
    """An MSA of ALIGNED_ROWS under ALIGNED_HEADERS."""
    path = os.path.join(folder, "msa.fasta")
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        for header, row in zip(ALIGNED_HEADERS, ALIGNED_ROWS):
            handle.write(f">{header}\n{row}\n")
    return path


def aligned_viewer():
    """A viewer whose network is ALIGNED_HEADERS, loading the configured MSA."""
    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
        viewer = vr_viewer.HeadlessViewer(
            len(ALIGNED_HEADERS), list(ALIGNED_HEADERS), list(ALIGNED_HEADERS), {}
        )
    viewer.pos = np.zeros((len(ALIGNED_HEADERS), 3), dtype=np.float32)
    viewer.original_pos = viewer.pos.copy()
    return viewer


def patch_settings(test, **values):
    for name, value in values.items():
        patcher = mock.patch.object(cfg, name, value, create=True)
        patcher.start()
        test.addCleanup(patcher.stop)


def drain(viewer):
    """Return every packet queued for the client, emptying the queue."""
    packets = []
    while not viewer.update_queue.empty():
        packets.append(viewer.update_queue.get_nowait())
    return packets


def wait_for(predicate, timeout=60.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return predicate()


class RecordingContext:
    """A bound command context, as the portal binds one, that keeps the reports."""

    portal = None

    def __init__(self):
        self.reports = []

    def report(self, status, message, artifact):
        self.reports.append((status, None if message is None else str(message)))


class HidePacketTests(unittest.TestCase):
    """`hide` changes the visibility the client draws, so it must send it."""

    def setUp(self):
        self.viewer = build_viewer()
        # As while a client is connected, every packet stays queued to be sent.
        self.viewer.is_connected = True

    def test_hide_queues_the_new_visibility(self):
        run_command(self.viewer, 'hide "P00001"')
        packets = drain(self.viewer)
        self.assertEqual(len(packets), 1, "one packet, not none and not two")
        self.assertIs(packets[0]["visible"][1], False)
        self.assertEqual(packets[0]["visible"].count(False), 1)

    def test_hiding_the_selection_queues_it_too(self):
        run_command(self.viewer, 'select "P00002"')
        self.assertEqual(drain(self.viewer), [], "selecting changes nothing the client draws")
        run_command(self.viewer, "hide")
        packets = drain(self.viewer)
        self.assertEqual(len(packets), 1)
        self.assertIs(packets[0]["visible"][2], False)

    def test_a_hide_that_matches_nothing_sends_nothing(self):
        run_command(self.viewer, 'hide "P00001"')
        drain(self.viewer)
        run_command(self.viewer, 'hide "P00001"')
        self.assertEqual(drain(self.viewer), [])

    def test_commands_that_send_the_nodes_themselves_send_once(self):
        run_command(self.viewer, 'hide "P00001"')
        drain(self.viewer)
        for command in ("reset hide", "undo", "redo"):
            with self.subTest(command=command):
                run_command(self.viewer, command)
                self.assertEqual(len(drain(self.viewer)), 1)


class HideSingleTests(unittest.TestCase):
    """`hide single` on a cache without a similarity threshold."""

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)

    def test_a_umap_cache_counts_every_edge(self):
        cache = publish_cache(self.root, umap_neighbors=2)
        use_inputs(self, cache)
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            viewer = vr_viewer.open_layout_session()
        self.assertIsNone(cfg.SIMILARITY_THRESHOLD)
        self.assertEqual(viewer.current_slider_threshold, float("-inf"))

        output = run_command(viewer, "hide single")
        self.assertNotIn("Traceback", output)
        self.assertIn("No single/free nodes found", output)

        # Hide node 0's neighbours; with no threshold node 0 is then free.
        neighbours = {int(b) for a, b in viewer.edges if a == 0} | {
            int(a) for a, b in viewer.edges if b == 0
        }
        viewer.visible_mask[sorted(neighbours)] = False
        output = run_command(viewer, "hide single")
        self.assertNotIn("Traceback", output)
        self.assertFalse(viewer.visible_mask[0])

    def test_a_threshold_cache_keeps_its_threshold(self):
        cache = publish_cache(self.root, similarity_threshold=0.45)
        use_inputs(self, cache)
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            viewer = vr_viewer.open_layout_session()
        self.assertEqual(viewer.current_slider_threshold, 0.45)


class ResetTests(unittest.TestCase):
    """`reset` is the main program's, render order and colour names included."""

    def test_reset_order_restores_the_render_order(self):
        viewer = build_viewer()
        viewer.promote_nodes([3, 4])
        self.assertNotEqual(viewer.node_render_order.tolist(), list(range(viewer.n_nodes)))
        output = run_command(viewer, "reset order")
        self.assertIn("Reset successful: node order.", output)
        self.assertEqual(viewer.node_render_order.tolist(), list(range(viewer.n_nodes)))

        run_command(viewer, "undo")
        self.assertEqual(viewer.node_render_order[-2:].tolist(), [3, 4])

    def test_reset_colours_takes_any_colour_the_settings_name(self):
        for value in ("red", "#f00", "#ff0000"):
            with self.subTest(value=value):
                patch_settings(self, INITIAL_NODE_COLOR=value)
                viewer = build_viewer()
                viewer.current_colors[:] = [0.0, 1.0, 0.0, 1.0]
                run_command(viewer, "reset colors")
                np.testing.assert_allclose(viewer.current_colors[0], [1.0, 0.0, 0.0, 1.0])

    def test_reset_returns_its_message(self):
        viewer = build_viewer()
        with redirect_stdout(io.StringIO()):
            message = Command_Engine.execute_reset(viewer, ["hidden"])
        self.assertEqual(message, "Reset successful: hidden.")

    def test_an_unknown_target_resets_nothing(self):
        viewer = build_viewer()
        viewer.visible_mask[0] = False
        output = run_command(viewer, "reset hide bogus")
        self.assertIn("Unknown reset target(s): bogus", output)
        self.assertFalse(viewer.visible_mask[0])
        self.assertEqual(viewer.undo_stack, [])


class UndoTests(unittest.TestCase):
    """Undo restores everything a command changed, and says whether it did."""

    def setUp(self):
        self.viewer = build_viewer()
        self.viewer.metadata["Organism"] = {
            "type": "text",
            "values": np.array([f"org{index}" for index in range(self.viewer.n_nodes)], dtype=object),
        }

    def test_undo_brings_a_deleted_metadata_column_back(self):
        output = run_command(self.viewer, "meta delete Organism")
        self.assertIn("Deleted metadata columns: Organism.", output)
        self.assertNotIn("Organism", self.viewer.metadata)

        self.assertIn("Undo successful.", run_command(self.viewer, "undo"))
        self.assertEqual(list(self.viewer.metadata), ["Length", "Organism"])
        self.assertEqual(self.viewer.metadata["Organism"]["values"][3], "org3")

        run_command(self.viewer, "redo")
        self.assertNotIn("Organism", self.viewer.metadata)

    def test_undo_restores_the_clustering_parameters(self):
        viewer = self.viewer
        viewer.cluster_labels = np.zeros(viewer.n_nodes, dtype=int)
        viewer.last_cluster_params = ("LEIDEN_1.0", 2)
        viewer._save_state()
        viewer.cluster_labels = np.ones(viewer.n_nodes, dtype=int)
        viewer.last_cluster_params = ("LEIDEN_2.0", 5)

        run_command(viewer, "undo")
        self.assertEqual(viewer.last_cluster_params, ("LEIDEN_1.0", 2))
        self.assertEqual(viewer.cluster_labels.tolist(), [0] * viewer.n_nodes)
        run_command(viewer, "redo")
        self.assertEqual(viewer.last_cluster_params, ("LEIDEN_2.0", 5))

    def test_undo_restores_the_positions_and_custom_datasets(self):
        viewer = self.viewer
        viewer.custom_scores = np.arange(viewer.n_nodes, dtype=float)
        viewer._cacheable_attrs.add("custom_scores")
        original = viewer.pos.copy()
        viewer._save_state()
        viewer.pos = viewer.pos + 1.0
        viewer.custom_scores = viewer.custom_scores * 0

        run_command(viewer, "undo")
        np.testing.assert_array_equal(viewer.pos, original)
        self.assertEqual(viewer.custom_scores.tolist(), list(range(viewer.n_nodes)))

    def test_undo_and_redo_say_whether_anything_changed(self):
        viewer = self.viewer
        with redirect_stdout(io.StringIO()):
            self.assertFalse(viewer._do_undo())
            self.assertFalse(viewer._do_redo())
            viewer._save_state()
            self.assertTrue(viewer._do_undo())
            self.assertTrue(viewer._do_redo())

    def test_the_command_report_matches_what_happened(self):
        viewer = self.viewer
        run_command(viewer, 'hide "P00001"')
        for command, expected in (
            ("undo", "Undo successful."),
            ("undo", "Nothing to undo."),
            ("redo", "Redo successful."),
            ("redo", "Nothing to redo."),
        ):
            context = RecordingContext()
            with Viewer_Command_Portal.bind(context):
                output = run_command(viewer, command)
            with self.subTest(command=command, expected=expected):
                self.assertIn(expected, output)
                self.assertIn(("succeeded", expected), context.reports)


class ArtifactTests(unittest.TestCase):
    """`logo` and `label` queue their work and write their files."""

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        msa = write_msa(self.root)
        self.results = os.path.join(self.root, "results")
        patch_settings(
            self,
            MSA_FILE=msa,
            ALIGNMENT_REFERENCE=ALIGNED_HEADERS[0],
            ALIGNMENT_OFFSET=0,
            ANALYSIS_RESULT_DIR=self.results,
        )
        self.viewer = aligned_viewer()
        self.assertTrue(self.viewer.alignment.has_reference)
        self.viewer.cluster_labels = np.array([0, 0, 0, 1, 1, 1])
        self.viewer.last_cluster_params = ("LEIDEN_1.0", 2)

        self.addCleanup(self.viewer.background_job_scheduler.shutdown)

        console = mock.patch.object(vr_viewer.CONSOLE, "message")
        self.reports = console.start()
        self.addCleanup(console.stop)

    def finish(self):
        scheduler = self.viewer.background_job_scheduler
        # The workers print their progress; keep it out of the test output.
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            finished = wait_for(lambda: scheduler.queue_depth == 0)
        self.assertTrue(finished, "the job did not finish")
        return "\n".join(str(call.args[0]) for call in self.reports.call_args_list)

    def written(self, folder):
        directory = os.path.join(self.results, folder)
        return sorted(os.listdir(directory)) if os.path.isdir(directory) else []

    def test_logo_writes_its_image(self):
        output = run_command(self.viewer, "logo [2-5] vr_logo.svg")
        self.assertIn("Queued background job", output)
        self.assertNotIn("unavailable", output)
        reports = self.finish()
        self.assertEqual(self.written("Sequence_Logos"), ["vr_logo.svg"])
        self.assertIn("completed", reports)
        self.assertIn(os.path.join(self.results, "Sequence_Logos", "vr_logo.svg"), reports)

    def test_label_writes_its_workbook(self):
        output = run_command(self.viewer, "label")
        self.assertIn("Queued background job", output)
        self.assertNotIn("unavailable", output)
        reports = self.finish()
        workbooks = self.written("Cluster_Label")
        self.assertEqual(len(workbooks), 1, workbooks)
        self.assertTrue(workbooks[0].endswith(".xlsx"))
        self.assertIn("completed", reports)
        self.assertIn(os.path.join(self.results, "Cluster_Label", workbooks[0]), reports)

    def test_a_reserved_output_is_refused(self):
        release = threading.Event()
        scheduler = self.viewer.background_job_scheduler
        blocker = os.path.join(self.results, "blocker.txt")
        with redirect_stdout(io.StringIO()):
            scheduler.enqueue("test", "blocker", None, lambda _: release.wait(30) and {}, blocker)
        run_command(self.viewer, "logo [2-5] vr_logo.svg")
        output = run_command(self.viewer, "logo [2-5] vr_logo.svg")
        release.set()
        self.assertIn("already reserved by a background job", output)
        self.finish()
        self.assertEqual(self.written("Sequence_Logos"), ["vr_logo.svg"])


class SchedulerTests(unittest.TestCase):
    """The scheduler's own contract, which `label` and `logo` rely on."""

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.reports = []
        self.scheduler = Background_Job_Scheduler_VR.BackgroundJobScheduler(say=self.reports.append)
        self.addCleanup(self.scheduler.shutdown)

    def enqueue(self, worker, name="out.txt", **kwargs):
        with redirect_stdout(io.StringIO()):
            return self.scheduler.enqueue(
                "test", f"test -> {name}", None, worker, os.path.join(self.root, name), **kwargs
            )

    def test_jobs_run_in_order_and_release_their_outputs(self):
        order = []
        self.enqueue(lambda _: order.append(1) or {}, "a.txt")
        self.enqueue(lambda _: order.append(2) or {}, "b.txt")
        self.assertTrue(wait_for(lambda: self.scheduler.queue_depth == 0))
        self.assertEqual(order, [1, 2])
        self.assertFalse(self.scheduler.is_output_path_reserved(os.path.join(self.root, "a.txt")))

    def test_an_existing_file_needs_overwrite(self):
        path = os.path.join(self.root, "out.txt")
        open(path, "w").close()
        with self.assertRaises(FileExistsError):
            self.enqueue(lambda _: {})
        self.enqueue(lambda _: {}, allow_overwrite=True)

    def test_a_failure_is_reported_and_the_queue_continues(self):
        def fail(_):
            raise ValueError("no luck")

        self.enqueue(fail, "a.txt")
        self.enqueue(lambda _: {"message": "fine"}, "b.txt")
        self.assertTrue(wait_for(lambda: self.scheduler.queue_depth == 0))
        text = "\n".join(self.reports)
        self.assertIn("Background job #1 failed", text)
        self.assertIn("no luck", text)
        self.assertIn("Background job #2 completed", text)

    def test_shutdown_refuses_new_jobs(self):
        self.scheduler.shutdown()
        with self.assertRaises(RuntimeError):
            self.enqueue(lambda _: {})

    def test_a_viewer_that_queues_nothing_starts_no_thread(self):
        self.assertIsNone(build_viewer().background_job_scheduler._thread)


class PacketQueueTests(unittest.TestCase):
    """With no client connected, only the newest state packet is kept."""

    def test_only_the_newest_packet_waits_for_a_client(self):
        viewer = build_viewer()
        for index in range(5):
            viewer.current_sizes[0] = 20.0 + index
            viewer.update_nodes()
        packets = drain(viewer)
        self.assertEqual(len(packets), 1)
        self.assertEqual(packets[0]["sizes"][0], 24.0)

    def test_a_connected_client_still_gets_every_packet(self):
        viewer = build_viewer()
        viewer.is_connected = True
        for _ in range(3):
            viewer.update_nodes()
        self.assertEqual(len(drain(viewer)), 3)

    def test_a_new_client_starts_from_the_current_state(self):
        """A packet queued before the connection is older than the initial one."""
        viewer = build_viewer(n_nodes=3)
        viewer.update_nodes()  # all visible
        viewer.visible_mask[1] = False  # e.g. a change no packet carried yet

        client, peer = socket.socketpair()
        self.addCleanup(client.close)
        self.addCleanup(peer.close)
        peer.shutdown(socket.SHUT_WR)  # the client hangs up after the handshake
        listener = mock.Mock()
        listener.accept.side_effect = [(client, ("local", 1)), OSError("listener stopped")]
        patch_settings(self, EXIT_WITH_UNITY=False)
        with mock.patch.object(vr_viewer._thread, "interrupt_main"), \
                mock.patch.object(vr_viewer.CONSOLE, "message"):
            empty = np.empty((0, 2), dtype=np.int32)
            vr_viewer.unity_server_loop(
                listener, viewer, np.zeros((3, 3), dtype=np.float32), empty, 3, 0, empty
            )

        received = b""
        while True:
            chunk = peer.recv(1 << 16)
            if not chunk:
                break
            received += chunk
        handshake = 4 + 3 * 12 + 4 + 4
        lines = [json.loads(line) for line in received[handshake:].splitlines() if line]
        self.assertEqual(len(lines), 1, "only the initial packet")
        self.assertIs(lines[0]["visible"][1], False)
        self.assertTrue(viewer.update_queue.empty())


class CacheChoiceTests(unittest.TestCase):
    """The relaunch opens the cache written last, whatever its name."""

    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.folder, ignore_errors=True)

    def write(self, name, age):
        path = os.path.join(self.folder, name)
        open(path, "w").close()
        stamp = time.time() - age
        os.utime(path, (stamp, stamp))
        return path

    def test_save_save_named_save_opens_the_last_save(self):
        self.write("version_00.h5", 30)
        self.write("zzz.h5", 20)
        newest = self.write("version_01.h5", 10)
        self.assertEqual(vr_viewer._newest_cache_in(self.folder), newest)

    def test_version_100_is_newer_than_version_99(self):
        self.write("version_99.h5", 20)
        newest = self.write("version_100.h5", 10)
        self.assertEqual(vr_viewer._newest_cache_in(self.folder), newest)

    def test_an_empty_folder_has_no_cache(self):
        self.assertIsNone(vr_viewer._newest_cache_in(self.folder))


class CommandNameTests(unittest.TestCase):
    def test_names_that_are_not_commands_are_unknown(self):
        viewer = build_viewer()
        for name in ("a.b", ".", "..", "__init__", "_private", "vr___init__"):
            with self.subTest(name=name):
                output = run_command(viewer, name)
                self.assertIn("Unknown command:", output)
                self.assertNotIn("Traceback", output)
                self.assertNotIn("missing dependency", output)

    def test_real_commands_still_run(self):
        viewer = build_viewer()
        self.assertIn("Reset successful", run_command(viewer, "vr_reset hide"))


class AlignmentLoadMessageTests(unittest.TestCase):
    def test_success_is_claimed_only_with_an_alignment(self):
        patch_settings(self, MSA_FILE=None)
        buffer = io.StringIO()
        with redirect_stdout(buffer), redirect_stderr(buffer):
            viewer = build_viewer()
            viewer.load_global_alignment()
        self.assertIsNone(viewer.alignment.aln)
        self.assertNotIn("successfully loaded", buffer.getvalue())

    def test_a_loaded_alignment_is_announced(self):
        root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        patch_settings(self, MSA_FILE=write_msa(root))
        viewer = aligned_viewer()
        buffer = io.StringIO()
        with redirect_stdout(buffer), redirect_stderr(buffer):
            viewer.load_global_alignment()
        self.assertIn("Alignment Manager successfully loaded.", buffer.getvalue())


if __name__ == "__main__":
    unittest.main()
