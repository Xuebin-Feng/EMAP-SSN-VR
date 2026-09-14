import Command_Engine

# The VR Alignment_Manager builds col_to_label / label_to_col once and has no
# set_offset() of its own, so the pristine (unshifted) mapping is cached on the
# alignment object the first time an offset is applied. Re-applying always
# starts from that cache, so offsets replace each other instead of stacking.
BASE_MAPPING_ATTR = '_vr_base_col_to_label'

HELP_MSG = ("Usage: offset [INTEGER]\n"
            "Description: Shifts reference-anchored alignment numbering by an integer.\n"
            "  Displayed position = reference position + offset, so an offset of 10 turns\n"
            "  position 1 into 11 and insertion position 1.1 into 11.1. The alignment\n"
            "  itself and the underlying columns are never modified.\n"
            "  Call without arguments to report the current offset.\n"
            "Requirements:\n"
            "  An alignment must be loaded with a resolved reference. Use 'reference <ID>'\n"
            "  first. Reloading the reference rebuilds the alignment and clears the offset,\n"
            "  so re-apply it afterwards.\n"
            "Affected commands:\n"
            "  The new numbering is used immediately by the position-aware commands:\n"
            "  query, label, logo, color, select, group, hide and spectrum.\n"
            "Note:\n"
            "  An offset that pushes positions to zero or below still renumbers every\n"
            "  report (query, label, logo), but the VR selection parser cannot address a\n"
            "  non-positive position: K0 and K-1 are not valid selection tokens.\n"
            "Examples:\n"
            "  offset        (Reports the current offset)\n"
            "  offset 10     (Starts reference numbering at 11 instead of 1)\n"
            "  offset -5     (Subtracts 5 from every reference-anchored position)\n"
            "  offset 0      (Restores the unshifted reference numbering)")


def _alignment(viewer):
    """The loaded alignment, or None if there is nothing to renumber."""
    alignment = getattr(viewer, 'alignment', None)
    if alignment is None or getattr(alignment, 'aln', None) is None:
        return None
    if not getattr(alignment, 'col_to_label', None):
        return None
    return alignment


def _has_reference(alignment):
    """True when numbering is reference-anchored rather than pure occupancy."""
    resolved = getattr(alignment, 'resolved_ref_full', None)
    return bool(resolved) and str(resolved).strip().lower() != 'none'


def _base_mapping(alignment):
    base = getattr(alignment, BASE_MAPPING_ATTR, None)
    if base is None:
        base = dict(alignment.col_to_label)
        setattr(alignment, BASE_MAPPING_ATTR, base)
    return base


def _shift_label(label, offset):
    """'12' -> '22', '12.3' -> '22.3' for an offset of 10."""
    parts = str(label).split('.', 1)
    try:
        shifted = str(int(parts[0]) + offset)
    except (TypeError, ValueError):
        return str(label)
    return shifted if len(parts) == 1 else f"{shifted}.{parts[1]}"


def _sort_key(label):
    parts = str(label).split('.', 1)
    try:
        major = int(parts[0])
    except (TypeError, ValueError):
        return (1, 0, 0)
    minor = 0
    if len(parts) == 2:
        try:
            minor = int(parts[1])
        except (TypeError, ValueError):
            minor = 0
    return (0, major, minor)


def _range_text(alignment):
    """'1 .. 245 (312 positions)' for the numbering currently in force."""
    labels = sorted(alignment.col_to_label.values(), key=_sort_key)
    if not labels:
        return "no positions"
    return f"{labels[0]} .. {labels[-1]} ({len(labels)} positions)"


def _apply(alignment, offset):
    base = _base_mapping(alignment)
    alignment.col_to_label = {col: _shift_label(label, offset)
                              for col, label in base.items()}
    alignment.label_to_col = {label: col
                              for col, label in alignment.col_to_label.items()}
    alignment.offset = offset


def run(viewer, args):
    if args and args[0].lower() in ['help', '-h', '--help']:
        Command_Engine.print_help(viewer, HELP_MSG)
        return

    alignment = _alignment(viewer)

    if not args:
        if alignment is None:
            Command_Engine.print_help(
                viewer,
                "Current Alignment Offset: 0 (inactive: no alignment is loaded)")
            return
        current = int(getattr(alignment, 'offset', 0) or 0)
        if not _has_reference(alignment):
            Command_Engine.print_help(
                viewer,
                f"Current Alignment Offset: {current} (inactive: the alignment is in "
                f"pure occupancy mode, with no resolved reference)\n"
                f"Displayed positions: {_range_text(alignment)}\n"
                f"Use 'reference <ID>' to anchor numbering before setting an offset.")
            return
        Command_Engine.print_help(
            viewer,
            f"Current Alignment Offset: {current}\n"
            f"Reference: {alignment.resolved_ref_full}\n"
            f"Displayed positions: {_range_text(alignment)}")
        return

    if len(args) != 1:
        Command_Engine.print_help(
            viewer,
            "Error: Offset accepts exactly one integer.\nUsage: offset [INTEGER]")
        return

    try:
        new_offset = int(args[0])
    except (TypeError, ValueError):
        Command_Engine.print_help(
            viewer,
            f"Error: Alignment offset must be an integer, not '{args[0]}'.\n"
            f"Usage: offset [INTEGER]")
        return

    if alignment is None:
        Command_Engine.print_help(
            viewer,
            "Error: Alignment offset requires a loaded alignment.\n"
            "Set an MSA file in your settings, then use 'reference <ID>'.")
        return

    if not _has_reference(alignment):
        Command_Engine.print_help(
            viewer,
            "Error: Alignment offset requires a resolved alignment reference.\n"
            "The alignment is in pure occupancy mode, where positions are simply "
            "column numbers.\nUse 'reference <ID>' first.")
        return

    before = _range_text(alignment)
    _apply(alignment, new_offset)
    viewer.alignment_offset = new_offset

    warning = ""
    if any(_sort_key(label)[1] < 1 for label in alignment.col_to_label.values()):
        warning = ("\nWarning: this offset produces positions at or below zero. They are "
                   "still\n  reported by query, label and logo, but the selection parser "
                   "cannot address\n  them: K0 and K-1 are not valid selection tokens.")

    Command_Engine.print_help(
        viewer,
        f"Alignment Offset set to {new_offset}. Position numbering updated.\n"
        f"  Reference:  {alignment.resolved_ref_full}\n"
        f"  Positions:  {before}  ->  {_range_text(alignment)}\n"
        f"query, label, logo, color, select, group, hide and spectrum now use the "
        f"new numbering.\nNode colours, sizes and visibility are unchanged, so no "
        f"update is sent to the headset.{warning}")
