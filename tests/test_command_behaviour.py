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

import ast
import atexit
import inspect
import io
import json
import os
import re
import shutil
import socket
import sys
import tempfile
import threading
import time
import unittest
from contextlib import redirect_stderr, redirect_stdout
from types import SimpleNamespace
from unittest import mock

OPT_VR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VR_SRC = os.path.join(OPT_VR, "src")
if VR_SRC not in sys.path:
    sys.path.insert(0, VR_SRC)

_NEUTRAL = tempfile.TemporaryDirectory(prefix="ssn_vr_neutral_")  # removed when this process exits
atexit.register(_NEUTRAL.cleanup)
_NEUTRAL_SETTINGS = os.path.join(_NEUTRAL.name, "viewer_settings.json")
with open(_NEUTRAL_SETTINGS, "w", encoding="utf-8") as _neutral_file:
    json.dump({}, _neutral_file)
os.environ.setdefault("SSN_VIEWER_SETTINGS_PATH", _NEUTRAL_SETTINGS)

import numpy as np  # noqa: E402

import _bootstrap_vr  # noqa: E402
import Settings_VR as cfg  # noqa: E402

with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
    import Background_Job_Scheduler_VR  # noqa: E402
    import Command_Engine  # noqa: E402
    import EMAPSSN_Viewer_VR as vr_viewer  # noqa: E402
    import Viewer_Command_Portal  # noqa: E402

_bootstrap_vr.install_settings_alias(cfg)

from utilities.Job_Cancellation import (  # noqa: E402
    CancellableFile,
    JobHandle,
    cancel_requested,
    current_job,
    forget_partial_path,
    note_partial_path,
    raise_if_cancelled,
)

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
        # `meta` reads the metadata folder setting; the default is a folder in
        # the project root, which no test may touch.
        metadata_folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, metadata_folder, True)
        patch_settings(self, METADATA_DIR=metadata_folder)
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


class UndoStepTests(unittest.TestCase):
    """`undo N` and `redo N` report once, and send the headset the result once."""

    def setUp(self):
        self.viewer = build_viewer()
        for step in range(3):
            self.viewer._save_state()
            self.viewer.pos = self.viewer.pos + 1.0

    def test_a_count_reports_once_and_updates_the_headset_once(self):
        viewer = self.viewer
        for command, text in (("undo 3", "Undid 3 steps."), ("redo 2", "Redid 2 steps.")):
            with self.subTest(command=command), \
                    mock.patch.object(viewer, "update_nodes") as nodes, \
                    mock.patch.object(viewer, "update_edges") as edges:
                output = run_command(viewer, command)

                self.assertIn(text, output)
                self.assertNotIn("successful", output)
                self.assertEqual(viewer.console_text.text, text)
                self.assertEqual((nodes.call_count, edges.call_count), (1, 1))

    def test_a_single_undo_still_reports_itself(self):
        self.assertIn("Undo successful.", run_command(self.viewer, "undo"))


class HeadsetNoteTests(unittest.TestCase):
    """A command that succeeds but changes what the protocol cannot carry says so.

    The note is added where the viewer dispatches a command, from the
    HEADSET_LIMITS table, so none of the upstream commands knows about it.
    """

    SELECTION = "(Not shown in the headset: the VR protocol does not carry the selection.)"
    SHAPES = "(Not shown in the headset: the VR protocol does not carry node shapes.)"
    POSITIONS = (
        "(Not shown in the headset: the VR protocol does not carry node position "
        "changes after the headset connects.)"
    )

    def setUp(self):
        self.viewer = build_viewer()
        self.viewer.cluster_labels = np.array([0] * 5 + [1] * 5 + [-1] * 2)
        self.viewer.group_labels = [set() for _ in range(self.viewer.n_nodes)]

    def test_select_says_the_headset_does_not_show_the_selection(self):
        output = run_command(self.viewer, "select #cluster_0#")
        self.assertIn("Selected 5 nodes", output)
        # The note ends the output, after the command's own report.
        self.assertTrue(output.rstrip().endswith(self.SELECTION), output)

    def test_a_select_that_changes_nothing_says_nothing(self):
        run_command(self.viewer, "select #cluster_0#")
        self.assertNotIn("Not shown in the headset", run_command(self.viewer, "select #cluster_0#"))

    def test_a_failed_command_gets_no_note(self):
        output = run_command(self.viewer, "select #nope#")
        self.assertIn("Selection failed", output)
        self.assertNotIn("Not shown in the headset", output)

    def test_a_shape_the_headset_cannot_draw_is_noted_and_a_colour_is_not(self):
        output = run_command(self.viewer, "color red #cluster_0#")
        self.assertIn("Applied: 5 nodes (red)", output)
        self.assertNotIn("Not shown in the headset", output)

        output = run_command(self.viewer, "color #cluster_0# triangle")
        self.assertIn("Applied: 5 nodes (triangle_up)", output)
        self.assertTrue(output.rstrip().endswith(self.SHAPES), output)

        # The same shape again changes nothing.
        self.assertNotIn(
            "Not shown in the headset", run_command(self.viewer, "color #cluster_0# triangle")
        )

    def test_reset_notes_only_the_targets_the_headset_cannot_show(self):
        viewer = self.viewer
        viewer.current_shapes[:] = "star"
        viewer.current_colors[:] = [0.0, 1.0, 0.0, 1.0]
        viewer.pos = viewer.pos + 1.0

        self.assertNotIn("Not shown in the headset", run_command(viewer, "reset colors"))
        self.assertTrue(run_command(viewer, "reset shapes").rstrip().endswith(self.SHAPES))
        self.assertTrue(run_command(viewer, "reset network").rstrip().endswith(self.POSITIONS))
        # Nothing left to reset: the command succeeds, and there is nothing to note.
        self.assertNotIn("Not shown in the headset", run_command(viewer, "reset shapes network"))

    def test_reset_naming_both_says_both_in_one_note(self):
        viewer = self.viewer
        viewer.current_shapes[:] = "star"
        viewer.pos = viewer.pos + 1.0
        output = run_command(viewer, "reset shapes network")
        self.assertEqual(output.count("Not shown in the headset"), 1)
        self.assertTrue(
            output.rstrip().endswith(
                "(Not shown in the headset: the VR protocol does not carry node shapes "
                "and node position changes after the headset connects.)"
            ),
            output,
        )

    def test_undo_and_redo_note_a_restored_layout(self):
        viewer = self.viewer
        original = viewer.pos.copy()
        viewer._save_state()
        viewer.pos = viewer.pos + 1.0

        output = run_command(viewer, "undo")
        np.testing.assert_array_equal(viewer.pos, original)
        self.assertTrue(output.rstrip().endswith(self.POSITIONS), output)
        self.assertTrue(run_command(viewer, "redo").rstrip().endswith(self.POSITIONS))

    def test_undo_and_redo_note_a_restored_shape(self):
        viewer = self.viewer
        run_command(viewer, "color #cluster_0# star")
        self.assertTrue(run_command(viewer, "undo").rstrip().endswith(self.SHAPES))
        self.assertTrue(run_command(viewer, "redo").rstrip().endswith(self.SHAPES))

    def test_undoing_a_colour_change_restores_nothing_the_headset_lacks(self):
        run_command(self.viewer, "color red #cluster_0#")
        self.assertNotIn("Not shown in the headset", run_command(self.viewer, "undo"))
        self.assertNotIn("Not shown in the headset", run_command(self.viewer, "redo"))

    def test_the_table_decides_which_commands_are_noted(self):
        patched = {**Command_Engine.HEADSET_LIMITS, "color": (("current_colors", "node colours"),)}
        with mock.patch.object(Command_Engine, "HEADSET_LIMITS", patched):
            output = run_command(self.viewer, "color red #cluster_0#")
        self.assertTrue(
            output.rstrip().endswith(
                "(Not shown in the headset: the VR protocol does not carry node colours.)"
            ),
            output,
        )

    def test_each_line_of_a_script_is_noted_as_typed(self):
        with tempfile.TemporaryDirectory() as folder:
            script = os.path.join(folder, "steps.txt")
            with open(script, "w", encoding="utf-8") as handle:
                handle.write("select #cluster_0#\ncolor red #cluster_0#\nselect #cluster_1#\n")
            output = run_command(self.viewer, f"run {script}")
        self.assertIn("Batch execution completed: 3 commands run.", output)
        self.assertEqual(output.count(self.SELECTION), 2)

    def test_a_command_run_outside_the_dispatcher_prints_no_note(self):
        from commands import select

        output = io.StringIO()
        with redirect_stdout(output):
            select.run(self.viewer, ["#cluster_0#"])
        self.assertNotIn("Not shown in the headset", output.getvalue())

    def test_a_command_that_raises_gets_no_note(self):
        viewer = self.viewer
        with redirect_stdout(io.StringIO()) as output:
            with self.assertRaises(RuntimeError):
                with Command_Engine.headset_notes(viewer, "select"):
                    Command_Engine.command_succeeded(viewer, "done")
                    viewer.selected_indices = [1]
                    raise RuntimeError("boom")
        self.assertEqual(output.getvalue(), "")

    def test_a_failure_after_a_success_keeps_the_command_failed(self):
        viewer = self.viewer
        with redirect_stdout(io.StringIO()) as output:
            with Command_Engine.headset_notes(viewer, "select"):
                Command_Engine.command_succeeded(viewer, "part")
                Command_Engine.command_failed(viewer, "rest")
                Command_Engine.command_succeeded(viewer, "again")
                viewer.selected_indices = [1]
        self.assertEqual(output.getvalue(), "")


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

    def test_a_waiting_logo_job_is_listed_and_cancelled_and_frees_its_file(self):
        release = threading.Event()
        self.addCleanup(release.set)
        scheduler = self.viewer.background_job_scheduler
        with redirect_stdout(io.StringIO()):
            scheduler.enqueue("test", "blocker", None, lambda _: release.wait(30) and {}, os.path.join(self.results, "blocker.txt"))
        run_command(self.viewer, "logo [2-5] vr_logo.svg")
        listing = run_command(self.viewer, "jobs")
        self.assertRegex(listing, r"#2\s+waiting\s+logo -> vr_logo\.svg\s+\(files\)")
        self.assertIn("2 jobs waiting or running", listing)
        self.assertIn("Cancelled 1 job: #2 logo -> vr_logo.svg.", run_command(self.viewer, "jobs cancel 2"))
        release.set()
        self.finish()
        self.assertEqual(self.written("Sequence_Logos"), [], "a cancelled job writes nothing")
        self.assertIn("No commands wait or run", run_command(self.viewer, "jobs"))
        run_command(self.viewer, "logo [2-5] vr_logo.svg")
        self.finish()
        self.assertEqual(self.written("Sequence_Logos"), ["vr_logo.svg"], "its file was free to use again")

    def test_a_running_logo_job_stops_at_its_next_check_point_and_leaves_nothing(self):
        """The shared worker's own check points reach the handle the scheduler bound to its thread."""
        from utilities import Alignment_Profiles

        real = Alignment_Profiles.calculate_logo_matrix
        reached = threading.Event()

        def waits_for_the_stop(*args, **kwargs):
            reached.set()
            wait_for(cancel_requested, 30)
            return real(*args, **kwargs)

        patcher = mock.patch.object(Alignment_Profiles, "calculate_logo_matrix", waits_for_the_stop)
        patcher.start()
        self.addCleanup(patcher.stop)
        run_command(self.viewer, "logo [2-5] vr_logo.svg")
        self.assertTrue(reached.wait(30), "the job did not start")
        self.assertRegex(run_command(self.viewer, "jobs"), r"#1\s+running\s+logo -> vr_logo\.svg\s+\(files\)")
        self.assertIn("Told 1 running job to stop: #1 logo -> vr_logo.svg.", run_command(self.viewer, "jobs cancel all"))
        reports = self.finish()
        self.assertIn("Background job #1 was stopped before it finished: logo -> vr_logo.svg", reports)
        self.assertNotIn("completed", reports)
        self.assertEqual(self.written("Sequence_Logos"), [], "no image and no partial file")
        self.assertFalse(self.viewer.background_job_scheduler.is_output_path_reserved(
            os.path.join(self.results, "Sequence_Logos", "vr_logo.svg")))


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


class JobControlFixture(unittest.TestCase):
    """A scheduler, a folder for its outputs, and workers that run until the test lets them go."""

    #: How long a test waits for a job to start.
    STARTUP_SECONDS = 30.0

    def make_scheduler(self):
        """The scheduler under test; ``self.reports`` is what it said."""
        self.reports = []
        return Background_Job_Scheduler_VR.BackgroundJobScheduler(say=self.reports.append)

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.release = threading.Event()
        self.ran = []
        self.scheduler = self.make_scheduler()
        # Cleanups run last in first out: the jobs are let go before the scheduler closes.
        self.addCleanup(self.scheduler.shutdown, 0.2)
        self.addCleanup(self.release.set)

    def path(self, name):
        return os.path.join(self.root, name)

    def text(self):
        return "\n".join(self.reports)

    def enqueue(self, worker, name="out.txt", scheduler=None):
        with redirect_stdout(io.StringIO()):
            return (scheduler or self.scheduler).enqueue("test", f"test -> {name}", name, worker, self.path(name))

    def recording(self, name):
        return lambda payload: self.ran.append(name) or {}

    def running_job(self, name, *, checks):
        """Queue a job that runs until the test releases it, and wait for it to start; return its number.

        With ``checks`` it reaches a check point between its steps and ends there when told to stop;
        without, it goes on until released, as a job stuck in one long call does.
        """
        started = threading.Event()

        def worker(payload):
            started.set()
            while not self.release.wait(0.005):
                if checks:
                    raise_if_cancelled()
            return {"message": "done"}

        job = self.enqueue(worker, name)
        self.assertTrue(started.wait(self.STARTUP_SECONDS), "the job did not start")
        return job

    def wait_idle(self):
        self.assertTrue(wait_for(lambda: self.scheduler.queue_depth == 0), "the jobs did not finish")


class SchedulerJobControlTests(JobControlFixture):
    """The scheduler gives a job what the main scheduler gives one: a handle, a line to cancel from, a clean close."""

    def test_the_worker_runs_with_its_handle_bound_to_its_thread(self):
        seen = []

        def plain(payload):
            seen.append(("plain", type(current_job()).__name__))
            return {}

        def with_handle(payload, job):
            seen.append(("handle", job is current_job(), isinstance(job, JobHandle)))
            return {}

        self.enqueue(plain, "a.txt")
        self.enqueue(with_handle, "b.txt")
        self.wait_idle()
        self.assertEqual(seen, [("plain", "JobHandle"), ("handle", True, True)])
        self.assertIsNone(current_job(), "nothing stays bound to the thread that asked")

    def test_snapshot_and_listing_tell_a_running_job_from_a_waiting_one(self):
        running = self.running_job("run.txt", checks=False)
        waiting = self.enqueue(self.recording("wait"), "wait.txt")
        first, second = self.scheduler.snapshot()
        self.assertEqual((first.job.job_id, first.running, first.position, first.stopping, first.lane),
                         (running, True, 1, False, "files"))
        self.assertIsNotNone(first.started_at)
        self.assertEqual((second.job.job_id, second.running, second.position, second.started_at, second.lane),
                         (waiting, False, 2, None, "files"))
        self.assertEqual([(job.job_id, state) for job, state in self.scheduler.listing()],
                         [(running, True), (waiting, False)])
        self.assertEqual(self.scheduler.queue_depth, 2)
        self.assertEqual([name for name, _title in self.scheduler.lanes()], ["files"])

    def test_the_lane_and_the_wait_are_the_main_schedulers(self):
        """The shared jobs command lists a job under its lane's name, and closing waits as long as the desktop's."""
        with open(os.path.join(_bootstrap_vr.SRC_DIR, "Background_Job_Scheduler.py"), encoding="utf-8") as handle:
            source = handle.read()
        main = {}
        for node in ast.parse(source).body:
            if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
                if node.targets[0].id in ("DEFAULT_LANE", "SHUTDOWN_WAIT_SECONDS"):
                    main[node.targets[0].id] = ast.literal_eval(node.value)
        self.assertEqual(main, {
            "DEFAULT_LANE": Background_Job_Scheduler_VR.DEFAULT_LANE,
            "SHUTDOWN_WAIT_SECONDS": Background_Job_Scheduler_VR.SHUTDOWN_WAIT_SECONDS,
        })
        self.assertEqual(inspect.signature(self.scheduler.shutdown).parameters["wait"].default,
                         Background_Job_Scheduler_VR.SHUTDOWN_WAIT_SECONDS)
        self.assertIn('self._lane(DEFAULT_LANE, Message("Files"))', source)
        self.assertEqual(str(Background_Job_Scheduler_VR.LANE_TITLE), "Files")

    def test_a_waiting_job_is_removed_at_once_and_never_runs(self):
        running = self.running_job("run.txt", checks=False)
        waiting = self.enqueue(self.recording("wait"), "wait.txt")
        self.assertTrue(self.scheduler.is_output_path_reserved(self.path("wait.txt")))
        self.assertEqual(self.scheduler.cancel_many([waiting]), [waiting])
        self.assertEqual([job.job_id for job, _ in self.scheduler.listing()], [running])
        self.assertFalse(self.scheduler.is_output_path_reserved(self.path("wait.txt")))
        self.assertIn("Background job #2 was cancelled before it started: test -> wait.txt", self.text())
        self.release.set()
        self.wait_idle()
        self.assertEqual(self.ran, [])

    def test_a_running_job_is_told_to_stop_and_ends_at_its_next_check_point(self):
        job = self.running_job("run.txt", checks=True)
        self.assertEqual(self.scheduler.cancel_many([job]), [job])
        self.wait_idle()
        self.assertIn(f"Background job #{job} was stopped before it finished: test -> run.txt", self.text())
        self.assertNotIn("completed", self.text())
        self.assertFalse(self.scheduler.is_output_path_reserved(self.path("run.txt")))

    def test_a_running_job_is_listed_as_stopping_until_it_ends_and_is_told_only_once(self):
        job = self.running_job("run.txt", checks=False)
        self.assertTrue(self.scheduler.cancel(job))
        self.assertTrue(self.scheduler.snapshot()[0].stopping)
        self.assertEqual(self.scheduler.cancel_many([job]), [], "a job already told to stop is not told again")
        self.assertFalse(self.scheduler.cancel(job))

    def test_a_job_with_no_check_point_left_completes_and_says_so(self):
        job = self.running_job("run.txt", checks=False)
        self.scheduler.cancel_many([job])
        self.release.set()
        self.wait_idle()
        self.assertIn(f"Background job #{job} was told to stop but had no step left to stop at, and completed in", self.text())
        self.assertNotIn("stopped before it finished", self.text())

    def test_a_number_that_names_no_job_cancels_nothing(self):
        job = self.running_job("run.txt", checks=True)
        self.assertEqual(self.scheduler.cancel_many([job + 7]), [])
        self.assertFalse(self.scheduler.cancel(job + 7))
        self.assertFalse(self.scheduler.snapshot()[0].stopping)

    def test_the_waiting_jobs_leave_before_the_running_one_is_told_to_stop(self):
        """The running job may end at once; the job behind it must not start in between."""
        running = self.running_job("run.txt", checks=True)
        first = self.enqueue(self.recording("first"), "first.txt")
        second = self.enqueue(self.recording("second"), "second.txt")
        self.assertEqual(self.scheduler.cancel_many([running, first, second]), [running, first, second])
        self.wait_idle()
        self.assertEqual(self.ran, [])
        self.assertEqual(self.scheduler.listing(), [])

    def test_a_job_that_ends_stops_being_listed_and_frees_its_file(self):
        self.enqueue(self.recording("a"), "a.txt")
        self.wait_idle()
        self.assertEqual(self.scheduler.snapshot(), [])
        self.assertFalse(self.scheduler.is_output_path_reserved(self.path("a.txt")))


class SchedulerCloseTests(JobControlFixture):
    """Closing the viewer while a job writes: the job stops and no half-written file is left, within a bound."""

    def writing_job(self, name, *, checks):
        """A job that writes a partial file, names it to the scheduler, and renames it into place if it ever finishes.

        With ``checks`` it writes through CancellableFile, as `logo` and `label` do, so every write is a
        check point and its ``finally`` deletes the file; without, it ignores the stop and holds nothing open.
        """
        partial, target = self.path(f".{name}.partial"), self.path(name)
        reached = threading.Event()

        def worker(payload):
            note_partial_path(partial)
            try:
                if checks:
                    with CancellableFile.at(partial, "wb") as handle:
                        handle.write(b"half")
                        reached.set()
                        while not self.release.wait(0.005):
                            handle.write(b".")
                else:
                    with open(partial, "wb") as handle:
                        handle.write(b"half")
                    reached.set()
                    self.release.wait(30)
                os.replace(partial, target)
                forget_partial_path(partial)
            finally:
                if checks and os.path.exists(partial):
                    os.remove(partial)
            return {"message": "done"}

        self.enqueue(worker, name)
        self.assertTrue(reached.wait(self.STARTUP_SECONDS), "the job did not start")
        return partial, target

    def test_a_job_that_checks_stops_at_once_and_its_partial_file_is_gone(self):
        partial, target = self.writing_job("report.xlsx", checks=True)
        self.assertTrue(os.path.exists(partial))
        started = time.monotonic()
        self.scheduler.shutdown()
        self.assertLess(time.monotonic() - started, 1.5, "a job that checks stops long before the bound")
        self.assertEqual(os.listdir(self.root), [])
        self.assertEqual(self.scheduler.queue_depth, 0)

    def test_a_job_that_ignores_the_stop_costs_the_wait_and_its_partial_file_is_deleted(self):
        partial, target = self.writing_job("stuck.png", checks=False)
        queued = self.enqueue(self.recording("queued"), "queued.png")
        self.assertTrue(os.path.exists(partial))
        started = time.monotonic()
        self.scheduler.shutdown(wait=0.3)
        elapsed = time.monotonic() - started
        self.assertGreaterEqual(elapsed, 0.25, "it waited for the job to stop")
        self.assertLess(elapsed, 2.0, "and no longer than the bound")
        self.assertFalse(os.path.exists(partial), "the scheduler deleted the partial file the job named")
        self.assertFalse(self.scheduler.is_output_path_reserved(self.path("queued.png")), "the queued job's file is free")
        # What the job does when it finally gets on cannot put a file in place: its partial file is gone.
        self.release.set()
        self.assertTrue(wait_for(lambda: self.scheduler.queue_depth == 0))
        self.assertFalse(os.path.exists(target))
        self.assertEqual(self.ran, [], "the queued job never ran")
        self.assertEqual(queued, 2)

    def test_a_file_renamed_into_place_before_the_close_is_left_alone(self):
        finished = self.path("finished.png")
        renamed = threading.Event()

        def worker(payload):
            partial = self.path(".finished.partial")
            note_partial_path(partial)
            with open(partial, "wb") as handle:
                handle.write(b"whole")
            os.replace(partial, finished)
            forget_partial_path(partial)
            renamed.set()
            self.release.wait(30)   # a later step that ignores the stop
            return {}

        self.enqueue(worker, "finished.png")
        self.assertTrue(renamed.wait(self.STARTUP_SECONDS))
        self.scheduler.shutdown(wait=0.2)
        self.release.set()
        with open(finished, "rb") as handle:
            self.assertEqual(handle.read(), b"whole")
        self.assertEqual(os.listdir(self.root), ["finished.png"])

    def test_closing_drops_the_waiting_jobs_refuses_new_ones_and_twice_is_harmless(self):
        self.running_job("run.txt", checks=True)
        self.enqueue(self.recording("a"), "a.txt")
        self.enqueue(self.recording("b"), "b.txt")
        self.scheduler.shutdown()
        self.assertEqual(self.ran, [])
        self.assertEqual(self.scheduler.listing(), [])
        for name in ("a.txt", "b.txt", "run.txt"):
            self.assertFalse(self.scheduler.is_output_path_reserved(self.path(name)))
        with self.assertRaises(RuntimeError):
            self.enqueue(self.recording("late"), "late.txt")
        self.scheduler.shutdown()

    def test_closing_with_no_job_returns_at_once(self):
        started = time.monotonic()
        self.scheduler.shutdown()
        self.assertLess(time.monotonic() - started, 0.5)

    def test_a_job_stopped_by_the_close_reports_nothing_more(self):
        self.running_job("run.txt", checks=True)
        self.reports.clear()
        self.scheduler.shutdown()
        self.assertEqual(self.reports, [], "the viewer is closing: nobody is left to tell")


class JobsCommandTests(JobControlFixture):
    """`jobs` in the headless viewer lists and cancels the background file jobs, as it does on the desktop."""

    def make_scheduler(self):
        console = mock.patch.object(vr_viewer.CONSOLE, "message")
        self.console = console.start()
        self.addCleanup(console.stop)
        self.viewer = build_viewer()
        self.reports = []
        return self.viewer.background_job_scheduler

    def jobs(self, command="jobs"):
        return run_command(self.viewer, command)

    def reports_text(self):
        return "\n".join(str(call.args[0]) for call in self.console.call_args_list)

    def test_jobs_lists_a_running_and_a_waiting_job(self):
        self.assertIn("No commands wait or run, and no file is being written.", self.jobs())
        self.running_job("run.txt", checks=True)
        self.enqueue(self.recording("wait"), "wait.txt")
        output = self.jobs()
        self.assertRegex(output, r"#1\s+running\s+test -> run\.txt\s+\(files\)")
        self.assertRegex(output, r"#2\s+waiting\s+test -> wait\.txt\s+\(files\)")
        self.assertIn("2 jobs waiting or running", output)
        self.assertNotIn("No commands wait or run", output)

    def test_jobs_cancel_removes_a_waiting_job(self):
        self.running_job("run.txt", checks=False)
        self.enqueue(self.recording("wait"), "wait.txt")
        output = self.jobs("jobs cancel 2")
        self.assertIn("Cancelled 1 job: #2 test -> wait.txt.", output)
        self.assertNotIn("Told", output)
        self.assertEqual([job.job_id for job, _ in self.scheduler.listing()], [1])
        self.assertFalse(self.scheduler.is_output_path_reserved(self.path("wait.txt")))
        self.release.set()
        self.wait_idle()
        self.assertEqual(self.ran, [])

    def test_jobs_cancel_stops_a_running_job(self):
        self.running_job("run.txt", checks=True)
        output = self.jobs("jobs cancel #1")
        self.assertIn("Told 1 running job to stop: #1 test -> run.txt.", output)
        self.assertNotIn("Cancelled 1 job", output, "a running job is told to stop, not yet cancelled")
        self.wait_idle()
        self.assertIn("Background job #1 was stopped before it finished: test -> run.txt", self.reports_text())
        self.assertIn("No commands wait or run", self.jobs())

    def test_a_job_told_to_stop_is_listed_as_stopping_and_is_not_told_again(self):
        self.running_job("run.txt", checks=False)
        self.jobs("jobs cancel 1")
        self.assertRegex(self.jobs(), r"#1\s+stopping\s+test -> run\.txt")
        self.assertIn("Already stopping: #1 test -> run.txt.", self.jobs("jobs cancel 1"))

    def test_jobs_cancel_all_cancels_the_waiting_jobs_and_stops_the_running_one(self):
        self.running_job("run.txt", checks=True)
        self.enqueue(self.recording("a"), "a.txt")
        self.enqueue(self.recording("b"), "b.txt")
        output = self.jobs("jobs cancel all")
        self.assertIn("Cancelled 2 jobs: #2 test -> a.txt, #3 test -> b.txt.", output)
        self.assertIn("Told 1 running job to stop: #1 test -> run.txt.", output)
        self.wait_idle()
        self.assertEqual(self.ran, [])
        self.assertIn("No commands wait or run", self.jobs())

    def test_a_bare_cancel_cancels_the_newest_job_since_there_is_no_queue(self):
        self.running_job("run.txt", checks=False)
        self.enqueue(self.recording("a"), "a.txt")
        self.assertIn("Cancelled 1 job: #2 test -> a.txt.", self.jobs("jobs cancel"))
        self.assertIn("Told 1 running job to stop: #1 test -> run.txt.", self.jobs("jobs cancel"))
        self.assertIn("Already stopping: #1", self.jobs("jobs cancel"))

    def test_a_bare_cancel_with_no_job_cancels_nothing(self):
        self.assertIn("Nothing to cancel", self.jobs("jobs cancel"))
        self.assertIn("Nothing to cancel", self.jobs("jobs cancel all"))

    def test_a_number_that_names_no_job_cancels_nothing(self):
        self.running_job("run.txt", checks=True)
        output = self.jobs("jobs cancel 9")
        self.assertIn("No job #9 waits or runs; nothing was cancelled.", output)
        self.assertFalse(self.scheduler.snapshot()[0].stopping)

    def test_a_cancelled_command_reports_the_outcome_as_a_command_does(self):
        self.running_job("run.txt", checks=True)
        context = RecordingContext()
        with Viewer_Command_Portal.bind(context):
            self.jobs("jobs cancel 1")
        self.assertEqual([status for status, _ in context.reports if status], ["succeeded"])

    def test_its_help_describes_this_viewer_not_the_desktop(self):
        for command in ("jobs help", "jobs --help"):
            with self.subTest(command=command):
                output = self.jobs(command)
                self.assertIn("This viewer runs every command at once", output)
                self.assertIn("in this terminal", output)
                for desktop in ("Session card", "Console window", "esmfold stop", "run stop", "subcluster", "Ctrl+Z"):
                    self.assertNotIn(desktop, output)
        context = RecordingContext()
        with Viewer_Command_Portal.bind(context):
            self.jobs("jobs help")
        self.assertEqual([status for status, _ in context.reports if status], ["succeeded"])

    def test_help_jobs_gives_the_vr_text(self):
        output = self.jobs("help jobs")
        self.assertIn("List the background file jobs (logo, label)", output)
        self.assertIn("(VR-specific implementation)", output)
        self.assertIn("Run 'jobs help' for its usage in this viewer.", output)
        self.assertNotIn("Commands run one at a time in the order given", output)


class ConsoleCommandTests(unittest.TestCase):
    """`console` in the headless viewer says its terminal is the console, in place of a refusal."""

    def setUp(self):
        self.viewer = build_viewer()

    def run_bound(self, command):
        context = RecordingContext()
        with Viewer_Command_Portal.bind(context):
            output = run_command(self.viewer, command)
        return output, [status for status, _ in context.reports if status]

    def test_console_says_the_output_is_in_this_terminal(self):
        output, statuses = self.run_bound("console")
        self.assertIn("The VR viewer has no Console window: everything it prints is in this terminal.", output)
        self.assertNotIn("no window of that kind", output)
        self.assertNotIn("is not available", output)
        self.assertEqual(statuses, ["succeeded"], "asking where the output is has an answer: it is no failure")

    def test_it_names_the_log_file_when_the_process_keeps_one(self):
        from utilities import Console_Capture

        log = os.path.join("logs", "vr-viewer-20261024-120000-1.log")
        with mock.patch.object(Console_Capture, "current", return_value=SimpleNamespace(log_path=log)):
            output, statuses = self.run_bound("console")
        self.assertIn(f"in this terminal, and the log file {log} keeps every line of the session.", output)
        self.assertEqual(statuses, ["succeeded"])

    def test_a_capture_with_no_log_names_none(self):
        from utilities import Console_Capture

        with mock.patch.object(Console_Capture, "current", return_value=SimpleNamespace(log_path=None)):
            output, _ = self.run_bound("console")
        self.assertNotIn("log file", output)
        self.assertIn("everything it prints is in this terminal.", output)

    def test_an_argument_is_refused_with_the_usage(self):
        output, statuses = self.run_bound("console now")
        self.assertIn("Error: console takes no arguments, not 'now'.", output)
        self.assertIn("Usage: console", output)
        self.assertEqual(statuses, ["failed"])

    def test_its_help_describes_this_viewer_not_the_desktop(self):
        for command in ("console help", "console -h"):
            with self.subTest(command=command):
                output, statuses = self.run_bound(command)
                self.assertIn("The VR viewer has no Console window.", output)
                self.assertIn("the terminal it was started from is its console", " ".join(output.split()))
                for desktop in ("Opens the Console window", "sidebar", "20,000", "Errors are red"):
                    self.assertNotIn(desktop, output)
                self.assertEqual(statuses, ["succeeded"])

    def test_help_console_gives_the_vr_text(self):
        output = run_command(self.viewer, "help console")
        self.assertIn("the VR viewer has no Console window, and this terminal is its console.", output)
        self.assertIn("(VR-specific implementation)", output)
        self.assertIn("Run 'console help' for its usage in this viewer.", output)
        self.assertNotIn("Needs a Viewer that shows windows", output)
        self.assertNotIn("Open the Console window", output)

    def test_the_command_list_shows_it_as_vr_text(self):
        listing = run_command(self.viewer, "help")
        self.assertRegex(listing, r"(?m)^    console +Say where this viewer's output is")
        self.assertRegex(listing, r"(?m)^    jobs +List the background file jobs")
        self.assertNotRegex(listing, r"(?m)^  \* (console|jobs) ", "neither is listed as the main program's")


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

    def test_a_failed_load_reports_the_loaders_reason(self):
        root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        good = write_msa(root)
        cases = (
            ("unequal.fasta", ">{0}\nMKT-A\n>{1}\nMKT\n".format(*ALIGNED_HEADERS[:2]),
             "MSA rejected: MSA sequences must have equal aligned lengths; expected 5, found "
             f"'{ALIGNED_HEADERS[1]}' (3)."),
            ("empty.fasta", "", "MSA rejected: MSA FASTA contains no records."),
        )
        for name, content, reason in cases:
            with self.subTest(file=name):
                path = os.path.join(root, name)
                with open(path, "w", encoding="utf-8", newline="\n") as handle:
                    handle.write(content)
                patch_settings(self, MSA_FILE=good)
                viewer = aligned_viewer()
                with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                    viewer.load_global_alignment()
                previous = viewer.alignment
                self.assertIsNotNone(previous.aln)

                context = RecordingContext()
                with Viewer_Command_Portal.bind(context), redirect_stdout(io.StringIO()) as output, \
                        redirect_stderr(io.StringIO()):
                    viewer.process_command(f"alignment {path}", record_history=False)

                failures = [text for status, text in context.reports if status == "failed"]
                self.assertTrue(
                    failures[0].startswith(f"\nFailed to load alignment '{name}': {reason}"), failures
                )
                self.assertFalse(any("failed to return an alignment" in text for _, text in context.reports))
                self.assertFalse(any(status == "succeeded" for status, _ in context.reports))
                # The terminal shows it too, and the previous alignment is back.
                self.assertIn(f"Failed to load alignment '{name}': {reason}", output.getvalue())
                self.assertIs(viewer.alignment, previous)
                self.assertEqual(cfg.MSA_FILE, good)

    def test_a_loaded_alignment_is_announced(self):
        root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        patch_settings(self, MSA_FILE=write_msa(root))
        viewer = aligned_viewer()
        buffer = io.StringIO()
        with redirect_stdout(buffer), redirect_stderr(buffer):
            viewer.load_global_alignment()
        self.assertIn("Alignment Manager successfully loaded.", buffer.getvalue())


def write_embeddings(folder, headers, sequence="MKTA", *, name="set_[test_model]_embeddings.h5",
                     model_name="test_model", complete=True):
    """An embedding file in the Tools' format holding HEADERS, all of SEQUENCE."""
    import h5py
    from utilities import HDF5_Storage

    path = os.path.join(folder, name)
    with h5py.File(path, "w") as handle:
        group = HDF5_Storage.create_metadata_first_file(
            handle, list(headers), [sequence] * len(headers), model_name, "float16"
        )
        for index, header in enumerate(headers):
            group.create_dataset(
                header, data=np.full((len(sequence), 2), index + 1, dtype=np.float16)
            )
        if complete:
            HDF5_Storage.mark_generation_complete(handle)
    return path


class EmbeddingLoadTests(unittest.TestCase):
    """The VR viewer loads the optional embedding through the main program's manager."""

    def test_no_embedding_leaves_a_manager_without_a_source(self):
        patch_settings(self, EMBED_FILE="")
        buffer = io.StringIO()
        with redirect_stdout(buffer), redirect_stderr(buffer):
            viewer = vr_viewer.HeadlessViewer(
                len(ALIGNED_HEADERS), list(ALIGNED_HEADERS), list(ALIGNED_HEADERS), {}
            )
        self.assertIsNone(viewer.embedding.source)
        self.assertIsNone(viewer.embedding.load_failure)
        self.assertIn("An embedding file is not selected", buffer.getvalue())

    def test_the_configured_embedding_is_matched_to_the_nodes(self):
        root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        patch_settings(self, EMBED_FILE=write_embeddings(root, ALIGNED_HEADERS[:2]))
        viewer = aligned_viewer()
        expected = [0, 1] + [-1] * (len(ALIGNED_HEADERS) - 2)
        self.assertEqual(viewer.embedding.viewer_to_emb.tolist(), expected)
        self.assertEqual(viewer.embedding.model_name, "test_model")
        np.testing.assert_array_equal(viewer.embedding.residues(1), np.full((4, 2), 2.0))
        # The manifest read at launch is kept when the file is unchanged.
        first = viewer.embedding
        with redirect_stdout(io.StringIO()) as output:
            viewer.load_embedding(reuse_loaded=True)
        self.assertIn("Reusing the loaded embedding manifest", output.getvalue())
        self.assertIs(viewer.embedding._manifest, first._manifest)


class EmbeddingCommandTests(unittest.TestCase):
    """`embedding` switches the active embedding as the desktop viewer's command does."""

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        patch_settings(self, EMBED_FILE="", EMBED_DIR=self.root, INPUT_HDF5="")
        self.viewer = aligned_viewer()
        self.previous = self.viewer.embedding

    def embedding_command(self, line):
        """Run LINE through the terminal's dispatcher: (printed text, the reports as (status, text))."""
        context = RecordingContext()
        buffer = io.StringIO()
        with Viewer_Command_Portal.bind(context), redirect_stdout(buffer), redirect_stderr(buffer):
            self.viewer.process_command(line, record_history=False)
        return buffer.getvalue(), context.reports

    def statuses(self, reports):
        return [status for status, _ in reports if status is not None]

    def test_a_file_is_required_and_a_missing_one_changes_nothing(self):
        output, reports = self.embedding_command("embedding")
        self.assertIn("Please name the embedding file", output)
        self.assertEqual(self.statuses(reports), ["failed"])
        output, reports = self.embedding_command("embedding no_such_file.h5")
        self.assertIn("Error: Embedding file 'no_such_file.h5' not found (checked absolute, relative, and", output)
        self.assertEqual(self.statuses(reports), ["failed"])
        self.assertIs(self.viewer.embedding, self.previous)
        self.assertEqual(cfg.EMBED_FILE, "")

    def test_help_is_printed_and_listed(self):
        for word in ("help", "-h", "--help", "HELP"):
            with self.subTest(word=word):
                output, reports = self.embedding_command(f"embedding {word}")
                self.assertIn("Embedding Switcher Tool", output)
                self.assertIn(self.root, output)
                self.assertEqual(self.statuses(reports), ["succeeded"])
                self.assertEqual(reports[-1][1], "Help information printed to the terminal.")
        self.assertRegex(self.embedding_command("help")[0], r"(?m)^\s*embedding\s")
        self.assertIn("Switch the active embedding", self.embedding_command("help embedding")[0])

    def test_the_file_is_found_as_given_in_the_folder_and_without_its_extension(self):
        absolute = write_embeddings(self.root, ALIGNED_HEADERS[:2])
        write_embeddings(self.root, ALIGNED_HEADERS[:3], name="other.h5")
        folder = os.path.join(self.root, "My Files")
        os.mkdir(folder)
        spaced = write_embeddings(folder, ALIGNED_HEADERS[:4], name="x.h5")
        cases = (
            (f"embedding {absolute}", absolute, 2),
            ("embedding other.h5", os.path.join(self.root, "other.h5"), 3),
            ("embedding other", os.path.join(self.root, "other.h5"), 3),
            (f"embedding {absolute[:-3]}", absolute, 2),
            (f'embedding "{spaced}"', spaced, 4),
            (f"embedding '{spaced}'", spaced, 4),
        )
        for line, expected, covered in cases:
            with self.subTest(line=line):
                output, reports = self.embedding_command(line)
                self.assertEqual(self.statuses(reports), ["succeeded"], reports)
                self.assertEqual(cfg.EMBED_FILE, os.path.abspath(expected).replace("\\", "/"))
                self.assertEqual(self.viewer.embedding.embed_file, cfg.EMBED_FILE)
                self.assertIn(f"({covered}/{len(ALIGNED_HEADERS)} network nodes embedded)", output)
        # As given wins over the folder, then the relative path of the working directory.
        previous_directory = os.getcwd()
        os.chdir(folder)
        self.addCleanup(os.chdir, previous_directory)
        output, reports = self.embedding_command("embedding x")
        self.assertEqual(cfg.EMBED_FILE, os.path.abspath(spaced).replace("\\", "/"))

    def test_the_new_embedding_is_reported_and_replaces_the_old_one(self):
        first = write_embeddings(self.root, ALIGNED_HEADERS[:2], name="first.h5")
        second = write_embeddings(self.root, ALIGNED_HEADERS[:5], name="second.h5", model_name="other_model")
        output, reports = self.embedding_command("embedding first")
        self.assertIn(
            f"Success: Loaded embedding 'first.h5' (2/{len(ALIGNED_HEADERS)} network nodes embedded).", output
        )
        self.assertIn("Embedding model: test_model (width 2, float16).", output)
        self.assertEqual(self.statuses(reports), ["succeeded"])
        self.assertEqual(
            reports[-1][1],
            f"Success: Loaded embedding 'first.h5' (2/{len(ALIGNED_HEADERS)} network nodes embedded). "
            "Embedding model: test_model (width 2, float16).",
        )
        self.assertEqual(
            self.viewer.console_text.text,
            f"Loaded first.h5: 2/{len(ALIGNED_HEADERS)} embedded. Embedding model: test_model (width 2, float16).",
        )
        before = self.viewer.embedding
        self.embedding_command("embedding second")
        self.assertIsNot(self.viewer.embedding, before)
        self.assertEqual(self.viewer.embedding.model_name, "other_model")
        mapping, valid = Command_Engine.get_embedding_mapping(self.viewer)
        self.assertEqual(mapping.tolist(), [0, 1, 2, 3, 4, -1])
        self.assertEqual(valid.tolist(), [0, 1, 2, 3, 4])
        self.assertIs(Command_Engine.require_embedding(self.viewer), self.viewer.embedding)
        self.assertEqual(cfg.EMBED_FILE, os.path.abspath(second).replace("\\", "/"))
        self.assertNotEqual(cfg.EMBED_FILE, first.replace("\\", "/"))

    def test_nodes_whose_sequence_differs_are_counted(self):
        path = write_embeddings(self.root, ALIGNED_HEADERS[:3], name="mixed.h5")
        self.viewer.sequences_map = {header: "MKTA" for header in ALIGNED_HEADERS}
        self.viewer.sequences_map[ALIGNED_HEADERS[1]] = "MKTW"
        output, reports = self.embedding_command(f"embedding {path}")
        self.assertIn(f"(2/{len(ALIGNED_HEADERS)} network nodes embedded)", output)
        self.assertIn("1 node not embedded: the file holds a different sequence.", output)
        self.assertEqual(self.viewer.embedding.mismatched_headers, [ALIGNED_HEADERS[1]])
        self.assertIn("1 node not embedded", reports[-1][1])

    def test_a_network_built_with_another_model_is_noted_and_accepted(self):
        import h5py

        network = os.path.join(self.root, "network.h5")
        with h5py.File(network, "w") as handle:
            handle.attrs["model_name"] = "esm2_t12_35M_UR50D"
        patch_settings(self, INPUT_HDF5=network)
        path = write_embeddings(self.root, ALIGNED_HEADERS[:2], name="same.h5", model_name="test_model")
        note = ("NOTE: The network was built with esm2_t12_35M_UR50D, not test_model. The Viewer "
                "accepts this; embedding commands use the embedding's model.")
        output, reports = self.embedding_command(f"embedding {path}")
        self.assertIn(note, output)
        self.assertTrue(reports[-1][1].endswith(note), reports)
        self.assertEqual(self.statuses(reports), ["succeeded"])
        # The same model, and a BLAST network, which has no model, get no note.
        matching = write_embeddings(self.root, ALIGNED_HEADERS[:2], name="match.h5", model_name="esm2_t12_35M_UR50D")
        self.assertNotIn("NOTE:", self.embedding_command(f"embedding {matching}")[0])
        with h5py.File(network, "w") as handle:
            handle.attrs["model_name"] = "BLAST"
        self.assertNotIn("NOTE:", self.embedding_command(f"embedding {path}")[0])

    def test_a_file_the_loader_refuses_restores_the_previous_embedding(self):
        good = write_embeddings(self.root, ALIGNED_HEADERS[:2], name="good.h5")
        self.embedding_command("embedding good")
        previous = self.viewer.embedding
        incomplete = write_embeddings(self.root, ALIGNED_HEADERS[:2], name="incomplete.h5", complete=False)
        broken = os.path.join(self.root, "broken.h5")
        with open(broken, "wb") as handle:
            handle.write(b"not an HDF5 file")
        notes = os.path.join(self.root, "notes.txt")
        with open(notes, "w", encoding="utf-8") as handle:
            handle.write("not an embedding")
        for name in ("incomplete.h5", "broken.h5", "notes.txt"):
            with self.subTest(file=name):
                output, reports = self.embedding_command(f"embedding {os.path.join(self.root, name)}")
                self.assertEqual(self.statuses(reports), ["failed"], reports)
                self.assertTrue(reports[-1][1].startswith(f"Failed to load embedding '{name}': Embedding file rejected:"))
                self.assertTrue(reports[-1][1].endswith("Reverted to previous embedding."))
                self.assertIn("Reverting to previous embedding state...", output)
                self.assertIs(self.viewer.embedding, previous)
                self.assertEqual(cfg.EMBED_FILE, os.path.abspath(good).replace("\\", "/"))
                self.assertEqual(self.viewer.console_text.text, "Load failed. Reverted to previous embedding.")

    def test_a_refused_file_leaves_no_embedding_when_there_was_none(self):
        broken = os.path.join(self.root, "broken.h5")
        with open(broken, "wb") as handle:
            handle.write(b"not an HDF5 file")
        output, reports = self.embedding_command(f"embedding {broken}")
        self.assertEqual(self.statuses(reports), ["failed"])
        self.assertIs(self.viewer.embedding, self.previous)
        self.assertIsNone(self.viewer.embedding.source)
        self.assertEqual(cfg.EMBED_FILE, "")

    def test_a_viewer_that_could_not_build_a_manager_is_rolled_back_too(self):
        path = write_embeddings(self.root, ALIGNED_HEADERS[:2], name="ok.h5")

        def fails():
            self.viewer.embedding = None  # What load_embedding leaves when the manager raised.

        self.viewer.load_embedding = fails
        output, reports = self.embedding_command(f"embedding {path}")
        self.assertEqual(self.statuses(reports), ["failed"])
        self.assertIn("Embedding loader failed to return an embedding.", reports[-1][1])
        self.assertIs(self.viewer.embedding, self.previous)
        self.assertEqual(cfg.EMBED_FILE, "")


if __name__ == "__main__":
    unittest.main()
