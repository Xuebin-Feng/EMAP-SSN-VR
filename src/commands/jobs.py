# Copyright 2026 Xuebin Feng
# Author affiliation: University of Toronto
# SPDX-License-Identifier: Apache-2.0

"""jobs: list the background file jobs (logo, label) that wait or run, and cancel them.

The listing and the cancelling are the main program's ``jobs`` command, run as it is on
this viewer's background job scheduler (Background_Job_Scheduler_VR), which gives it what
it reads: snapshot() and cancel_many(). This module shadows the main command for what
differs here, and for nothing else:

* **Its help.** The main command describes the desktop Viewer: a queue of commands that
  run one after another, the Session card that lists the jobs and moves a waiting one, the
  Console window, and the folding workers. None of that exists in this process, so
  ``jobs help`` and ``help jobs`` say what does: every command runs at once, and the
  jobs are the file jobs.
* **A bare ``jobs cancel``.** On the desktop it cancels the newest command in the queue,
  and a file job is cancelled by its number or with ``all``. This viewer has no queue, so
  the same words would cancel nothing while a job runs; here they cancel the newest job.

It runs at once, as the main command does.

OVERRIDE_REASON is read by Command_Compatibility_VR, which would otherwise take this
override for a redundant one: the main program's module loads in this process, and is
run by this one.
"""
import importlib.util
import os
import sys

import _bootstrap_vr
import Command_Engine

OVERRIDE_REASON = "its help describes a command queue and windows this viewer has not; runs the main command"

_UPSTREAM = "_upstream_commands_jobs"


def _upstream():
    """The main program's ``jobs`` module, loaded by path under a private name.

    ``commands.jobs`` is this module, so the main one cannot be imported by its own name.
    It is loaded once: the dispatcher reloads this module at each call, and the main
    one's functions are what ``run`` hands the work to.
    """
    module = sys.modules.get(_UPSTREAM)
    if module is None:
        path = os.path.join(_bootstrap_vr.SRC_DIR, "commands", "jobs.py")
        spec = importlib.util.spec_from_file_location(_UPSTREAM, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[_UPSTREAM] = module
        try:
            spec.loader.exec_module(module)
        except BaseException:
            sys.modules.pop(_UPSTREAM, None)
            raise
    return module


def print_help():
    print("""
    Jobs: Waiting and Running File Jobs
    ===================================
    Usage: jobs
           jobs cancel [N ...]
           jobs cancel all
           jobs help

    Description:
      This viewer runs every command at once, as it is typed. The slow ones that
      write a file (logo, label) run in the background instead, one at a time in
      the order they were given, while the prompt stays free: those are the jobs.
      jobs lists them, numbered, and cancels them.

    Arguments:
      (none)            - Lists the jobs that wait or run.
      cancel            - Cancels the newest job.
      cancel N [N ...]  - Cancels those jobs, by number (3 or #3). A job that is
                          running is told to stop, and a job not started is
                          dropped. A number that names no job cancels nothing.
      cancel all        - Cancels every job, running or not.

    Notes:
      A running job stops at its next step, which takes a moment, longer where
      one step is a large picture or report. Until it has, it is not cancelled:
      jobs lists it as stopping, and it is reported cancelled when it ends, with
      what it had written deleted (a file of that name from before stays as it
      was). A job with no step left to stop at completes instead, and is
      reported as completed.
      Leaving the viewer stops a running job the same way, waits up to 2.5
      seconds for it, and deletes the file it had begun; the jobs not started
      are dropped.
      The jobs are listed here, in this terminal.

    Examples:
      jobs
      jobs cancel
      jobs cancel 3 4
      jobs cancel all
    """)


def run(viewer, args):
    if args and args[0].lower() in ['help', '-h', '--help']:
        print_help()
        if hasattr(viewer, 'console_text'):
            viewer.console_text.text = "Help information printed to the terminal"
        Command_Engine.command_succeeded(viewer, 'Help information printed to the terminal.')
        return
    upstream = _upstream()
    if len(args) == 1 and args[0].lower() == 'cancel':
        # No queue here: the newest job, which is the last of the line, is what "newest" means.
        jobs = upstream._file_jobs(viewer)
        if jobs:
            args = ['cancel', str(jobs[-1][0].job_id)]
    upstream.run(viewer, args)
