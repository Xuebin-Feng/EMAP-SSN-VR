import Command_Engine

# Maps the base form Command_Engine.execute_reset derives (one trailing 's'
# stripped) onto the canonical target name it reports.
VALID_TARGETS = {
    'color': 'colors',
    'size': 'sizes',
    'shape': 'shapes',
    'cluster': 'clusters',
    'group': 'groups',
    'hide': 'hidden',
    'hidden': 'hidden',
    'network': 'network',
}

HELP_TEXT = (
    "Network Reset Tool\n"
    "==================\n"
    "Usage:\n"
    "  reset <TARGET_1> [TARGET_2] ...\n"
    "  reset help\n"
    "\n"
    "Targets:\n"
    "  colors    Restores all node colors to the configured default color.\n"
    "  sizes     Restores all node sizes to the configured default size.\n"
    "  shapes    Restores all node shapes to discs.\n"
    "  clusters  Clears all cluster labels.\n"
    "  groups    Clears all group labels.\n"
    "  hide      Makes all hidden nodes visible.\n"
    "  network   Restores node positions to the original layout.\n"
    "\n"
    "Notes:\n"
    "  Multiple targets may be reset in one command. Singular and plural target\n"
    "  names are accepted. The reset is stored as one undoable action.\n"
    "  In VR, 'colors', 'sizes' and 'hide' are pushed to the headset immediately;\n"
    "  'shapes' and 'network' change viewer state only (see the warnings printed\n"
    "  when you use them).\n"
    "\n"
    "Examples:\n"
    "  reset network hide\n"
    "  reset colors sizes shapes"
)

# viewer.update_nodes() ships colors, sizes and visibility only. Positions are
# sent once in the binary handshake and node shape has no Unity channel at
# all, so silently reporting 'Reset successful: network' would tell the user
# the headset had changed when it had not.
VR_CAVEATS = {
    'network': ("Note: node positions reach Unity only in the connection handshake. "
               "The layout in the headset is unchanged until the VR client reconnects."),
    'shapes': ("Note: node shape is not part of the Unity update packet. The shapes "
              "were reset in the viewer state, but the headset rendering is unchanged."),
}


def _base_form(target):
    lowered = target.lower()
    return lowered[:-1] if lowered.endswith('s') else lowered


def run(viewer, args):
    if not args or args[0].lower() in ['help', '-h', '--help']:
        Command_Engine.print_help(viewer, HELP_TEXT)
        return

    # execute_reset() calls viewer._save_state() before it parses anything, so
    # handing it an unusable target pushed a no-op snapshot onto the undo stack
    # and wiped the redo stack. Validate first and refuse the whole command.
    unknown = [a for a in args if _base_form(a) not in VALID_TARGETS]
    if unknown:
        msg = (
            f"Error: unknown reset target(s): {', '.join(unknown)}.\n"
            "Valid targets: colors, sizes, shapes, clusters, groups, hide, network.\n"
            "Nothing was reset. Type 'reset help' for details."
        )
        Command_Engine.print_help(viewer, msg)
        return

    Command_Engine.execute_reset(viewer, args)

    resolved = {VALID_TARGETS[_base_form(a)] for a in args}
    caveats = [VR_CAVEATS[name] for name in ('network', 'shapes') if name in resolved]
    if caveats:
        Command_Engine.print_help(viewer, '\n'.join(caveats))
