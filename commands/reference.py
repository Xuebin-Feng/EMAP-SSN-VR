import Command_Engine
import fnmatch

_MISSING = object()


def _describe_active_reference(viewer):
    """Describe what the alignment is anchored to right now.

    The bare 'reference' report used to echo viewer.resolved_ref_full or the
    configured reference even when the MSA had failed to load, which - with the
    terminal as the only surface here - read as a working anchor when there was
    none.
    """
    alignment = getattr(viewer, 'alignment', None)
    configured = getattr(viewer, 'active_reference', None) or 'None'

    if alignment is None or getattr(alignment, 'aln', None) is None:
        return (f"Current Reference: {configured} (inactive: no alignment is loaded)\n"
                f"Set an MSA file in your settings, then use 'reference <ID>'.")

    resolved = getattr(alignment, 'resolved_ref_full', None)
    if not resolved or str(resolved).strip().lower() == 'none':
        return ("Current Reference: None (the alignment is in pure occupancy mode, so "
                "positions are plain column numbers)\n"
                "Use 'reference <ID>' to anchor the numbering to a sequence.")

    return f"Current Reference: {resolved}"


def run(viewer, args):
    if not args:
        Command_Engine.print_help(viewer, _describe_active_reference(viewer))
        return
        
    if args[0].lower() in ['help', '-h', '--help']:
        msg = "Usage: reference [TARGET]\nDescription: Changes the reference sequence for alignment mapping.\n  - Call without arguments to see the current active reference.\n  - Pass a partial sequence header name to set a new reference.\nExamples:\n  reference\n  reference SeqA"
        Command_Engine.print_help(viewer, msg)
        return

    target = args[0]
    target_lower = target.lower()
    found_ref = None
    found_ref_full = None

    matches = [h for h in viewer.full_headers if fnmatch.fnmatch(h.lower(), target_lower) or target_lower in h.lower()]
    if matches:
        found_ref = matches[0]
        found_ref_full = found_ref
        if len(matches) > 1:
            print(f"Warning: Multiple matches found for '{target}'. Using '{found_ref}'.")
    else:
        aln = getattr(getattr(viewer, 'alignment', None), 'aln', None)
        # Iterating a sparse alignment builds one SeqRecord per row, which this
        # fork's loader cannot do (it raises NameError), so any unknown reference
        # used to end in a traceback instead of "not found". Its header list
        # carries the same information without materializing records.
        aln_headers = getattr(aln, 'headers', None) if aln is not None else None
        if aln_headers is not None:
            for header in aln_headers:
                if fnmatch.fnmatch(header.lower(), target_lower) or target_lower in header.lower():
                    found_ref = header.split()[0] if header.split() else header
                    found_ref_full = header
                    break
        elif aln:
            for record in aln:
                k = record.id
                if fnmatch.fnmatch(k.lower(), target_lower) or target_lower in k.lower():
                    found_ref = k
                    found_ref_full = record.description if record.description else k
                    break
    
    if found_ref:
        previous_alignment = getattr(viewer, 'alignment', None)
        previous_reference = getattr(viewer, 'active_reference', None)
        previous_resolved = getattr(viewer, 'resolved_ref_full', _MISSING)

        viewer.active_reference = target
        viewer.resolved_ref_full = found_ref_full or found_ref

        print(f"\nReloading alignment...")
        viewer.console_text.text = f"Reloading alignment with new reference: {target}..."
        
        viewer.load_global_alignment()
        
        # console_text is a DummyText stand-in with no on-screen surface here, so
        # the outcome has to be printed. The failure branch used to report nothing
        # at all, leaving a silently disabled alignment behind.
        if viewer.alignment and viewer.alignment.aln is not None:
            resolved = getattr(viewer.alignment, 'resolved_ref_full', None)
            if not resolved or str(resolved).strip().lower() == 'none':
                resolved = found_ref_full or found_ref
            viewer.resolved_ref_full = resolved
            msg = f"Reference successfully set: {resolved}"
        else:
            # This fork's Alignment_Manager discards the whole MSA when the requested
            # reference is not in it, so a failed reload used to cost the session the
            # alignment it already had. Put the previous one back instead.
            viewer.alignment = previous_alignment
            viewer.active_reference = previous_reference
            if previous_resolved is _MISSING:
                try:
                    del viewer.resolved_ref_full
                except AttributeError:
                    pass
            else:
                viewer.resolved_ref_full = previous_resolved

            msg = (f"Error: '{target}' matched '{found_ref_full or found_ref}' but the MSA "
                   f"could not be reloaded against it. Either the alignment file is "
                   f"unreadable, or that sequence is in the network but not in the MSA.\n"
                   f"{_describe_active_reference(viewer)}")
            if getattr(viewer, 'alignment', None) is None or viewer.alignment.aln is None:
                msg += ("\nAlignment-dependent commands (query, label, logo, offset and "
                        "position-based selections) are unavailable until a working "
                        "reference or alignment is loaded.")
        Command_Engine.print_help(viewer, msg)
    else:
        err = f"Error: Reference '{target}' not found."
        viewer.console_text.text = err
        print(f"\n{err}")
