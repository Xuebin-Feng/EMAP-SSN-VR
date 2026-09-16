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
# are numpy, fnmatch, re, os, dataclasses, enum and EMAPSSN_Config, and
# _bootstrap_vr has already registered Settings_VR under that last name. The two
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


def execute_reset(viewer, targets):
    """Executes reset on the specified targets."""
    lower_parts = [p.lower() for p in targets]
    
    if "help" in lower_parts or "-h" in lower_parts or "--help" in lower_parts:
        msg = "Usage: reset <target_1> [target_2] ...\nDescription: Resets specific properties of the network to their default or backup states.\nValid Targets:\n  colors   - Resets all node colors to default\n  sizes    - Resets all node sizes to default\n  shapes   - Resets all node shapes to default\n  clusters - Clears all cluster labels\n  groups   - Clears all group labels\n  hide     - Unhides all hidden nodes\n  network  - Restores node layout positions to the original or last saved state\nExamples:\n  reset network hide\n  reset colors sizes"
        print_help(viewer, msg)
        return

    targets_found = []
    needs_update = False
    
    viewer._save_state()
    
    for p in lower_parts:
        base_p = p[:-1] if p.endswith('s') else p
        
        if base_p == "color":
            if hasattr(viewer, 'current_colors'):
                neighbor_hex = getattr(cfg, 'NEIGHBOR_COLOR', '#4488ff')
                def parse_hex_color(hex_str):
                    h = hex_str.lstrip('#')
                    if len(h) == 6:
                        return [int(h[0:2], 16)/255.0, int(h[2:4], 16)/255.0, int(h[4:6], 16)/255.0, 1.0]
                    elif len(h) == 8:
                        return [int(h[0:2], 16)/255.0, int(h[2:4], 16)/255.0, int(h[4:6], 16)/255.0, int(h[6:8], 16)/255.0]
                    return [0.8, 0.8, 0.8, 1.0]
                n_rgba = parse_hex_color(neighbor_hex)
                viewer.current_colors[:] = n_rgba
            needs_update = True
            targets_found.append("colors")
            
        elif base_p == "size":
            if hasattr(viewer, 'current_sizes'):
                viewer.current_sizes.fill(cfg.NODE_SIZE)
            needs_update = True
            targets_found.append("sizes")
        
        elif base_p == "shape":
            if hasattr(viewer, 'current_shapes'):
                viewer.current_shapes.fill('disc')
            needs_update = True
            targets_found.append("shapes")

        elif base_p == "cluster":
            viewer.cluster_labels = None
            viewer.tooltip.text = "" 
            targets_found.append("clusters")

        elif base_p == "group":
            viewer.group_labels = [set() for _ in range(viewer.n_nodes)]
            viewer.tooltip.text = "" 
            targets_found.append("groups")
                
        elif base_p in ["hide", "hidden"]:
            viewer.visible_mask.fill(True)
            needs_update = True
            targets_found.append("hidden")
            
        elif base_p == "network":
            if hasattr(viewer, 'original_pos'):
                viewer.pos = viewer.original_pos.copy()
            needs_update = True
            targets_found.append("network")

    if needs_update:
        viewer.update_nodes()
        if "hidden" in targets_found or "network" in targets_found:
            viewer.update_edges()

    if targets_found:
        msg = f"Reset successful: {', '.join(targets_found)}."
    else:
        msg = "Usage: reset [colors | sizes | clusters | hide | network]"
    
    viewer.console_text.text = msg
    print(f"{msg}")


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


def command_succeeded(viewer, message=None, artifact=None):
    report('succeeded', message, artifact, viewer)


def command_failed(viewer, message):
    report('failed', str(message), viewer=viewer)


def command_cancelled(viewer, message):
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
