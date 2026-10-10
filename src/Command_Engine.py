import importlib.util
import numpy as np
import os
import sys

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
    report('succeeded', message, artifact, viewer)


def command_failed(viewer, message):
    _upstream._record_outcome('failed')
    report('failed', str(message), viewer=viewer)


def command_cancelled(viewer, message):
    _upstream._record_outcome('cancelled')
    report('cancelled', str(message), viewer=viewer)


def command_artifact(viewer, path):
    report(artifact=path, viewer=viewer)


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
