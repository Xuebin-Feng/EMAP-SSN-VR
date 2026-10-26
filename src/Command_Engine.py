# Copyright 2026 Xuebin Feng
# Author affiliation: University of Toronto
# SPDX-License-Identifier: Apache-2.0

import importlib.util
import numpy as np
import os
import sys
from contextlib import contextmanager
from contextvars import ContextVar

import _bootstrap_vr
import Settings_VR as cfg


def _upstream_engine():
    """Load the main program's Command_Engine under a private alias.

    ``import Command_Engine`` resolves to *this* module - opt_vr precedes src on
    sys.path, which is what makes the override work at all - so the upstream
    copy has to be loaded by path to be reachable from here.
    """
    alias = "_upstream_Command_Engine"
    module = sys.modules.get(alias)
    if module is None:
        path = os.path.join(_bootstrap_vr.SRC_DIR, "Command_Engine.py")
        spec = importlib.util.spec_from_file_location(alias, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[alias] = module
        spec.loader.exec_module(module)
    return module


# The Boolean selection grammar belongs to the main program: the tokenizer, the
# recursive-descent parser, every predicate it can evaluate, and the errors it
# raises when an expression names a cluster, group, file, alignment position or
# metadata property that the current SSN does not have.
#
# All of it is adopted rather than forked. This module used to adopt only the
# *classifier* and keep a local regex-rewrite-and-eval evaluator, which meant VR
# accepted an expression upstream rejected and rejected one upstream accepted:
# `(RHK)71` and `K(-1)` classified as valid and then failed to evaluate, group
# labels matched case-sensitively instead of case-insensitively, and a
# misspelled `#label#` silently selected nothing instead of reporting which
# labels exist. Nothing about that divergence was VR-specific - it was drift.
#
# The upstream module loads cleanly in this headless process: its only imports
# are numpy, fnmatch, re, os, dataclasses, enum, EMAPSSN_Config and the Qt-free
# utilities.Localization, and _bootstrap_vr has already registered Settings_VR
# under EMAPSSN_Config. The two
# settings the grammar reads - GAP_CHARS and HEADER_LIST_DIR - resolve through
# that alias to the same values the forked copy used.
_upstream = _upstream_engine()

SelectionExpressionError = _upstream.SelectionExpressionError
SelectionContextError = _upstream.SelectionContextError
SelectionClassification = _upstream.SelectionClassification
SelectionClassificationKind = _upstream.SelectionClassificationKind
ResolvedLabelTarget = _upstream.ResolvedLabelTarget

classify_selection_expression = _upstream.classify_selection_expression
parse_selection_expression = _upstream.parse_selection_expression
evaluate_selection_expression = _upstream.evaluate_selection_expression
parse_advanced_expression = _upstream.parse_advanced_expression

resolve_label_target = _upstream.resolve_label_target
evaluate_string_mask = _upstream.evaluate_string_mask
evaluate_file_mask = _upstream.evaluate_file_mask
evaluate_label_mask = _upstream.evaluate_label_mask
evaluate_aa_mask = _upstream.evaluate_aa_mask
evaluate_aa_group_mask = _upstream.evaluate_aa_group_mask
evaluate_metadata_mask = _upstream.evaluate_metadata_mask
FASTA_EXTENSIONS = _upstream.FASTA_EXTENSIONS


def print_help(viewer, msg, *, terminal_msg=None, report_message=True):
    """Print a message to the terminal.

    The VR viewer has no on-canvas HUD: ``viewer.console_text`` is a DummyText
    stand-in kept only so command code shared with the desktop viewer can
    assign to it. The terminal is the only output surface here.

    The previous implementation forwarded multi-line messages to that stand-in
    and printed "Please see the viewer console for details." instead, which
    made every help text, table and report invisible in the VR terminal.
    """
    text = msg if terminal_msg is None else terminal_msg
    if report_message:
        report(message=text, viewer=viewer)
    viewer.console_text.text = text
    print(f"\n{text}")


# Shared commands write the console line through Command_Engine.show_status.
# Here the line is the DummyText stand-in, so the upstream helper serves as is.
show_status = _upstream.show_status


# `reset`, `hide reset`, `color reset`, `group reset` and `label reset` all
# reset through this, and the main program's version runs here as it is: it
# reads only the state arrays, cfg (Settings_VR) and update_nodes /
# update_edges, which the VR viewer has, and guards the desktop's label
# visuals and console background. The fork it replaces had drifted: it
# accepted `reset order` without restoring the render order, parsed only
# #rrggbb[aa] colours (a named colour reset to grey) and returned no message.
execute_reset = _upstream.execute_reset


# =====================================================================
# Shared helpers mirrored from the main program's Command_Engine
# =====================================================================

def _coerce_node_mask(mask, n_nodes):
    """Normalize any selection input to a node-length Boolean mask."""
    result = np.zeros(n_nodes, dtype=bool)
    if mask is None:
        return result
    candidate = np.asarray(mask)
    if candidate.dtype == bool and candidate.shape == (n_nodes,):
        return candidate.copy()
    if candidate.dtype == bool:
        limit = min(candidate.shape[0] if candidate.ndim else 0, n_nodes)
        result[:limit] = candidate[:limit]
        return result
    # Otherwise treat it as a sequence of indices.
    for index in candidate.reshape(-1).tolist():
        try:
            index = int(index)
        except (TypeError, ValueError):
            continue
        if 0 <= index < n_nodes:
            result[index] = True
    return result


# The selection a shared command reads and leaves. Upstream they follow the
# job of the desktop Viewer's command queue, which runs a waiting command with
# the selection it was given; VR runs every command at once, so they read and
# write viewer.selected_indices, as the commands did before.
command_selection = _upstream.command_selection
set_command_selection = _upstream.set_command_selection


def get_selected_mask(viewer):
    """Return the current selection as a stable node-length Boolean mask."""
    n_nodes = int(
        getattr(viewer, "n_nodes", len(getattr(viewer, "full_headers", [])))
    )
    return _coerce_node_mask(getattr(viewer, "selected_indices", None), n_nodes)


def get_alignment_mapping(viewer):
    """Return the network-to-alignment map and the mapped node indices.

    Mirrors the main program's helper. Seven command modules had each
    open-coded this block.
    """
    full_headers = getattr(viewer, 'full_headers', [])
    n_nodes = len(full_headers)
    alignment = getattr(viewer, 'alignment', None)

    if alignment is not None:
        stored_mapping = getattr(alignment, 'viewer_to_aln', None)
        if stored_mapping is not None:
            stored_mapping = np.asarray(stored_mapping, dtype=int)
            if stored_mapping.shape == (n_nodes,):
                return stored_mapping, np.flatnonzero(stored_mapping >= 0)

    viewer_to_aln = np.full(n_nodes, -1, dtype=int)
    if alignment is not None and getattr(alignment, 'aln', None) is not None:
        seq_map = getattr(alignment, 'seq_map', {}) or {}
        for index, header in enumerate(full_headers):
            if header in seq_map:
                viewer_to_aln[index] = seq_map[header]
    return viewer_to_aln, np.flatnonzero(viewer_to_aln >= 0)


def get_embedding_mapping(viewer):
    """Return the network-to-embedding map and the embedded node indices.

    Mirrors the main program's helper, as get_alignment_mapping does: entry i
    is node i's row in the embedding file, or -1 when the embedding does not
    cover it.
    """
    n_nodes = len(getattr(viewer, 'full_headers', []))
    embedding = getattr(viewer, 'embedding', None)
    if getattr(embedding, 'source', None) is not None:
        mapping = np.asarray(getattr(embedding, 'viewer_to_emb', ()), dtype=int)
        if mapping.shape == (n_nodes,):
            return mapping, np.flatnonzero(mapping >= 0)
    viewer_to_emb = np.full(n_nodes, -1, dtype=int)
    return viewer_to_emb, np.flatnonzero(viewer_to_emb >= 0)


# Why a command cannot use the embedding is the main program's to decide, so
# both viewers refuse with the same messages.
embedding_unavailable_message = _upstream.embedding_unavailable_message


def require_embedding(viewer):
    """The viewer's Embedding_Manager when a command can use it, else None.

    The main program's helper, reporting here: the outcome goes through this
    module's command_failed, which this dispatcher records, and the reason to
    the terminal, the only place the VR viewer shows it.
    """
    message = embedding_unavailable_message(viewer)
    if message is not None:
        command_failed(viewer, message)
        print_help(viewer, message, report_message=False)
        return None
    return viewer.embedding


# --- Explicit outcome reporting -------------------------------------
# Upstream commands call these unconditionally. Here they forward to the
# Qt-free Viewer_Command_Portal shim, whose report() is a no-op unless an
# execution context is bound - which interactive typing never does. That is
# what lets an upstream command run unmodified in the VR terminal.

def report(status=None, message=None, artifact=None, viewer=None):
    from Viewer_Command_Portal import report as _report
    _report(status, message, artifact, viewer)


# A run script counts the lines that failed through upstream's outcome
# recorder, so every outcome reported here is recorded there too.
recorded_outcome = _upstream.recorded_outcome
script_command = _upstream.script_command


def command_succeeded(viewer, message=None, artifact=None):
    _upstream._record_outcome('succeeded')
    _record_dispatch('succeeded')
    report('succeeded', message, artifact, viewer)


def command_failed(viewer, message):
    _upstream._record_outcome('failed')
    _record_dispatch('failed')
    report('failed', str(message), viewer=viewer)


def command_cancelled(viewer, message):
    _upstream._record_outcome('cancelled')
    _record_dispatch('cancelled')
    report('cancelled', str(message), viewer=viewer)


def command_artifact(viewer, path):
    report(artifact=path, viewer=viewer)


# --- Changes the headset cannot show --------------------------------
# The VR protocol sends the headset colours, sizes, visibility and the
# transform, and nothing else (docs/PROTOCOL.md, "Known limitations"), and the
# reference client draws every node opaque, so the alpha of a colour is not
# shown either. A command that changes anything else still succeeds, so the
# terminal says what the headset will not show. It is said here, around the
# viewer's dispatch of each command, so no upstream command needs VR-specific
# code.


def _alpha_channel(colors):
    """The alpha of every node's colour, the part of current_colors the headset does not show."""
    return colors[:, 3]


#: command -> ((viewer attribute it can change, what the headset does not show of it
#: [, a function that picks the part of the attribute the headset does not show]), ...)
HEADSET_LIMITS = {
    "select": (("selected_indices", "the selection"),),
    "color": (
        ("current_shapes", "node shapes"),
        ("current_colors", "transparency", _alpha_channel),
    ),
    "reset": (
        ("current_shapes", "node shapes"),
        ("pos", "node position changes after the headset connects"),
        ("current_colors", "transparency", _alpha_channel),
    ),
    "undo": (
        ("current_shapes", "node shapes"),
        ("pos", "node position changes after the headset connects"),
        ("current_colors", "transparency", _alpha_channel),
    ),
    "redo": (
        ("current_shapes", "node shapes"),
        ("pos", "node position changes after the headset connects"),
        ("current_colors", "transparency", _alpha_channel),
    ),
    # These recolor nodes too, and give the nodes of noise a 40 % alpha.
    "cluster": (("current_colors", "transparency", _alpha_channel),),
    "subcluster": (("current_colors", "transparency", _alpha_channel),),
    "spectrum": (("current_colors", "transparency", _alpha_channel),),
}

HEADSET_NOTE = "(Not shown in the headset: {what}.)"

# The outcome the command being dispatched has reported: the latest status,
# except that a failure or cancellation stays, as the portal's records keep it.
_DISPATCH = ContextVar("vr_command_dispatch", default=None)


def _record_dispatch(status):
    record = _DISPATCH.get()
    if record is not None and record["status"] not in ("failed", "cancelled"):
        record["status"] = status


def _copy_of(value):
    return value.copy() if hasattr(value, "copy") else value


def _watched_part(viewer, row):
    """What a HEADSET_LIMITS row watches in the viewer now, as a copy.

    That is the row's attribute, or when the row has a function, the part of the
    attribute that function picks. An attribute the viewer lacks is None.
    """
    value = getattr(viewer, row[0], None)
    if len(row) > 2 and value is not None:
        value = row[2](value)
    return _copy_of(value)


@contextmanager
def headset_notes(viewer, command_name):
    """Around one command's run: if it succeeded having changed what the
    headset cannot show, end its output with a note saying so.

    A command that raised, failed or was cancelled gets no note, and neither
    does one whose change the headset does show.
    """
    watched = HEADSET_LIMITS.get(command_name, ())
    before = [_watched_part(viewer, row) for row in watched]
    record = {"status": None}
    token = _DISPATCH.set(record)
    try:
        yield
    finally:
        _DISPATCH.reset(token)
    if record["status"] != "succeeded":
        return
    unshown = [
        row[1] for row, was in zip(watched, before)
        if not np.array_equal(was, _watched_part(viewer, row))
    ]
    if unshown:
        print(HEADSET_NOTE.format(what=" and ".join(unshown)))


def report_selection_error(viewer, expression, error, operation="Selection"):
    """Canonical abort path for a bad Boolean expression."""
    command_failed(viewer, error)
    print_help(
        viewer,
        f"{operation} failed for expression: {expression}\n"
        f"  {error}\n"
        "Operation aborted; no changes were applied.",
        report_message=False,
    )
