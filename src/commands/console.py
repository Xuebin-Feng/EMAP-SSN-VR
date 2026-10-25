# Copyright 2026 Xuebin Feng
# Author affiliation: University of Toronto
# SPDX-License-Identifier: Apache-2.0

"""console: say where this viewer's output is. The VR viewer has no Console window; this terminal is its console.

The main program's ``console`` opens the desktop Viewer's Console window and,
where the viewer has none, refuses with "this Viewer has no window of that
kind". That reads as an error here, where the terminal this viewer was started
from already is its console: everything it prints appears in it, as it
happens. This module shadows it so that `console` answers that, and names the
log file when this process keeps one (utilities.Console_Capture, the main
program's capture of a process's output), instead of refusing.

It is not a refusal, so it succeeds: asking where the output is has an answer.
It runs at once, as the main command does.

OVERRIDE_REASON is read by Command_Compatibility_VR, which would otherwise take this
override for a redundant one: the main program's module loads in this process, and
does not do this.
"""
import Command_Engine
from utilities.Localization import JoinedMessage, Message

OVERRIDE_REASON = "the VR viewer has no Console window; its terminal is the console"


def print_help():
    print("""
    Console: Where This Viewer's Output Is
    ======================================
    Usage: console
           console help

    Description:
      The VR viewer has no Console window. It is a terminal program, and the
      terminal it was started from is its console: everything it prints, the
      commands' output and every warning and error, appears there as it
      happens, and the terminal's own scrollback keeps it. console says so,
      and names the log file that keeps every line of the session when this
      process writes one.

    Notes:
      The Console window, which searches and filters what a program printed,
      is the desktop viewer's. Here, scroll back in the terminal.

    Examples:
      console
    """)


def _log_path():
    """The log file this process writes its output to, or None when it keeps none."""
    try:
        from utilities import Console_Capture
        capture = Console_Capture.current()
    except Exception:  # Nothing here may keep the command from answering.
        return None
    path = getattr(capture, "log_path", None)
    return str(path) if path else None


def run(viewer, args):
    if args and args[0].lower() in ['help', '-h', '--help']:
        print_help()
        if hasattr(viewer, 'console_text'):
            viewer.console_text.text = "Help information printed to the terminal"
        Command_Engine.command_succeeded(viewer, 'Help information printed to the terminal.')
        return
    if args:
        message = JoinedMessage([
            Message("Error: console takes no arguments, not '{argument}'.", argument=args[0]),
            Message("Usage: {syntax}", syntax="console"),
        ], separator="\n")
        Command_Engine.print_help(viewer, message, report_message=False)
        Command_Engine.command_failed(viewer, message)
        return
    log_path = _log_path()
    if log_path:
        message = Message(
            "The VR viewer has no Console window: everything it prints is in this terminal, "
            "and the log file {path} keeps every line of the session.",
            path=log_path,
        )
    else:
        message = Message("The VR viewer has no Console window: everything it prints is in this terminal.")
    Command_Engine.print_help(viewer, message)
    Command_Engine.command_succeeded(viewer, message)
