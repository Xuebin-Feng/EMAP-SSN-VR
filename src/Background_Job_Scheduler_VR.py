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

"""Qt-free stand-in for the main program's background job scheduler.

The shared `label` and `logo` commands validate and snapshot their inputs on
the command thread, then hand the expensive work to
``viewer.background_job_scheduler``. The main program's scheduler is a QObject
that reports through Qt signals, so it cannot load in this headless process;
without a scheduler both commands stopped after validation with "the
background job scheduler is unavailable".

This keeps the contract those commands rely on: jobs run in strict FIFO order
on one daemon thread, an output path is reserved from enqueue until its job
ends, an existing file is refused unless overwriting was asked for, and
completion or failure is reported. Reports go to the terminal, with the saved
path in place of the desktop's file-manager reveal.

It also gives a job what the main scheduler gives one (Background_Job_Scheduler),
by the main program's own Qt-free pieces (utilities.Job_Cancellation), so the
shared commands stop and clean up here as they do on the desktop:

* **A handle per job.** The worker runs with a JobHandle bound to its thread, so
  the check points of the shared commands (raise_if_cancelled), their partial-file
  notes (note_partial_path) and CancellableFile do something, and a worker with a
  second parameter called ``job`` is handed the handle.
* **The line.** One lane, "files", as the main scheduler names the lane of file
  jobs, so the shared ``jobs`` command reads it as it does there: snapshot() and
  listing() give the unfinished jobs, and cancel_many() takes the waiting ones out
  of the line and tells the running one to stop; it ends at its next check point,
  which deletes what it had written, and is reported as stopped.
* **Closing.** shutdown() drops the waiting jobs, tells the running one to stop,
  waits up to SHUTDOWN_WAIT_SECONDS for it, and deletes the partial files a job
  that did not stop had named, so leaving the viewer in the middle of a write
  leaves no half-written file.

The main scheduler's lanes beyond that one, its ordering (move), its failure list
and its follow-up callbacks serve the desktop's Session card, which this process
has no use for.
"""

from __future__ import annotations

import inspect
import os
import threading
import time
import traceback
from dataclasses import dataclass
from typing import Any, Callable

from utilities.Job_Cancellation import JobCancelled, JobHandle, bound_to
from utilities.Localization import Message

#: The lane the main scheduler puts file jobs in, and the title it gives it
#: (Background_Job_Scheduler.DEFAULT_LANE); the shared ``jobs`` command lists a
#: job under its lane's name. A test reads the main scheduler's source to see that
#: these still agree with it.
DEFAULT_LANE = "files"
LANE_TITLE = Message("Files")
#: How long closing the viewer waits for the running job to reach a check point and
#: stop (Background_Job_Scheduler.SHUTDOWN_WAIT_SECONDS).
SHUTDOWN_WAIT_SECONDS = 2.5


def _takes_handle(worker):
    """Whether the worker has a second parameter named ``job``, which is the job's JobHandle.

    The main scheduler's rule (Background_Job_Scheduler._takes_handle), which lives in
    a module that loads Qt and so cannot be imported here.
    """
    try:
        parameters = list(inspect.signature(worker).parameters.values())
    except (TypeError, ValueError):
        return False
    positional = [parameter for parameter in parameters
                  if parameter.kind in (parameter.POSITIONAL_ONLY, parameter.POSITIONAL_OR_KEYWORD)]
    return len(positional) >= 2 and positional[1].name == "job"


@dataclass(frozen=True)
class BackgroundJob:
    job_id: int
    command_name: str
    description: str
    payload: Any
    worker: Callable[..., Any]
    output_path: str
    lane: str = DEFAULT_LANE


@dataclass(frozen=True)
class JobStatus:
    """One unfinished job as snapshot() reports it, with the fields the main scheduler's has.

    ``position`` is its place in the line, the running job being 1; ``started_at`` is the
    running job's time.monotonic() start, None for a waiting one; ``stopping`` is true for the
    running job once it was told to stop; ``progress`` is what the running job says it is doing.
    """
    job: BackgroundJob
    running: bool
    position: int
    started_at: float | None = None
    stopping: bool = False
    lane: str = DEFAULT_LANE
    progress: Any = None


class BackgroundJobScheduler:
    """Run command jobs in strict FIFO order on one daemon thread.

    The line, the running job and the reservations are read and changed under one lock, so
    a job is either still waiting, where it can be removed, or running, where it can only be
    told to stop.
    """

    def __init__(self, say=print):
        #: Prints one report line; the viewer passes its prompt-safe console.
        self._say = say
        self._lock = threading.Lock()
        self._wake = threading.Condition(self._lock)
        self._accepting = True
        self._next_job_id = 1
        # The waiting jobs, in the order they will run; the running one is not in it.
        self._queued = []
        self._active = None
        self._handle = None
        self._started = None
        self._stopping = False
        self._reserved_output_paths = set()
        # Started by the first job, so a viewer that never queues one never
        # holds a thread.
        self._thread = None

    @staticmethod
    def _output_key(path):
        return os.path.normcase(os.path.abspath(os.fspath(path)))

    @staticmethod
    def lanes():
        """(name, title) of every lane, as the main scheduler lists them: here the one."""
        return [(DEFAULT_LANE, LANE_TITLE)]

    @property
    def queue_depth(self):
        """Return the number of running and queued jobs."""
        with self._lock:
            return len(self._queued) + (self._active is not None)

    def is_output_path_reserved(self, path):
        key = self._output_key(path)
        with self._lock:
            return key in self._reserved_output_paths

    # --- the line ---

    def listing(self):
        """The jobs not yet finished, in the order of the line, as (job, running) pairs."""
        with self._lock:
            return [(job, job is self._active) for job in self._line()]

    def snapshot(self):
        """The unfinished jobs in the order of the line, as JobStatus entries, read at one moment."""
        with self._lock:
            entries = []
            position = 1
            if self._active is not None:
                handle = self._handle
                entries.append(JobStatus(
                    self._active, True, position, self._started, self._stopping, self._active.lane,
                    handle.progress_text if handle is not None else None,
                ))
                position += 1
            for job in self._queued:
                entries.append(JobStatus(job, False, position, None, False, job.lane))
                position += 1
            return entries

    def _line(self):
        """The unfinished jobs in the order of the line, the running one first; call with the lock held."""
        return ([self._active] if self._active is not None else []) + self._queued

    def cancel(self, job_id):
        """Take a job out of the line, or tell the running one to stop; return whether there was one to."""
        return bool(self.cancel_many([job_id]))

    def cancel_many(self, job_ids):
        """Cancel several jobs as one step; return the numbers of those there was something to cancel.

        A waiting job is gone at once: its output is released and it is reported cancelled. The
        running job is told to stop and ends at the next check point of its worker, which deletes
        its unfinished files; it is reported stopped then. A worker with no check point left
        finishes its file as it would have, and is reported as completed. A job already told to
        stop is not told again.

        The waiting ones are taken out of the line before the running one is told to stop, in a
        single step: the next job could otherwise start in between, when the running job ended
        at once, and run although it was among those to cancel.
        """
        removed = []
        handles = []
        cancelled = []
        with self._lock:
            for job_id in job_ids:
                index = next((place for place, job in enumerate(self._queued) if job.job_id == job_id), None)
                if index is not None:
                    job = self._queued.pop(index)
                    self._release(job)
                    removed.append(job)
                elif self._active is not None and self._active.job_id == job_id and not self._stopping:
                    self._stopping = True
                    if self._handle is not None:
                        handles.append(self._handle)
                else:
                    continue
                cancelled.append(job_id)
        for job in removed:
            self._report(Message(
                "Background job #{job} was cancelled before it started: {description}",
                job=job.job_id, description=job.description,
            ))
        for handle in handles:
            handle.request()
        return cancelled

    def _release(self, job):
        """Free the output the job reserved; call with the lock held."""
        self._reserved_output_paths.discard(self._output_key(job.output_path))

    def enqueue(
        self,
        command_name,
        description,
        payload,
        worker,
        output_path,
        allow_overwrite=False,
    ):
        """Reserve an output and append one immutable job to the FIFO queue."""
        output_path = os.path.abspath(os.fspath(output_path))
        output_key = self._output_key(output_path)
        with self._lock:
            if not self._accepting:
                raise RuntimeError("The background job scheduler is shutting down.")
            if not allow_overwrite and os.path.exists(output_path):
                raise FileExistsError(f"Output file already exists: {output_path}")
            if output_key in self._reserved_output_paths:
                raise FileExistsError(
                    f"Output file is already reserved by a background job: {output_path}"
                )

            job_id = self._next_job_id
            self._next_job_id += 1
            queue_position = len(self._queued) + (self._active is not None) + 1
            job = BackgroundJob(
                job_id=job_id,
                command_name=str(command_name),
                description=str(description),
                payload=payload,
                worker=worker,
                output_path=output_path,
            )
            self._reserved_output_paths.add(output_key)
            self._queued.append(job)
            if self._thread is None:
                self._thread = threading.Thread(
                    target=self._worker_loop,
                    name="SSN-VR-Background-Jobs",
                    daemon=True,
                )
                self._thread.start()
            self._wake.notify()

        print(Message(
            "Queued background job #{job}: {command} (position {position}) -> {file}",
            job=job_id, command=job.command_name, position=queue_position,
            file=os.path.basename(output_path),
        ))
        return job_id

    def shutdown(self, wait=SHUTDOWN_WAIT_SECONDS):
        """Close the line: discard the waiting jobs and stop the running one, within ``wait`` seconds.

        The running job is told to stop and given up to ``wait`` seconds to reach a check point,
        where its worker deletes its partial files and the job ends. A job that has not stopped
        by then is left to its daemon thread, which ends with the process; the partial files it
        named (JobHandle.note_partial) are deleted here instead, so that leaving the viewer in
        the middle of a write leaves no half-written file whatever the job's thread is doing. A
        file it renames into place afterwards cannot appear: the partial file it would rename
        is gone.
        """
        with self._lock:
            if not self._accepting:
                return
            self._accepting = False
            for job in self._queued:
                self._release(job)
            self._queued.clear()
            handle = self._handle
            thread = self._thread
            self._wake.notify_all()
        if handle is not None:
            handle.request()
        if thread is not None:
            thread.join(max(0.0, wait))
        with self._lock:
            stuck = self._handle if self._active is not None else None
        for path in stuck.partial_paths() if stuck is not None else ():
            try:
                os.remove(path)
            except OSError:
                pass

    def _worker_loop(self):
        while True:
            with self._lock:
                while self._accepting and not self._queued:
                    self._wake.wait()
                if not self._accepting:
                    return
                job = self._queued.pop(0)
                handle = JobHandle()
                self._active = job
                self._handle = handle
                self._started = time.monotonic()
                self._stopping = False

            try:
                self._run(job, handle)
            finally:
                with self._lock:
                    self._active = None
                    self._handle = None
                    self._started = None
                    self._stopping = False
                    self._release(job)

    def _run(self, job, handle):
        self._report(Message(
            "Running background job #{job}: {description}", job=job.job_id, description=job.description
        ))
        started_at = time.perf_counter()
        try:
            with bound_to(handle):
                if _takes_handle(job.worker):
                    result = dict(job.worker(job.payload, job=handle))
                else:
                    result = dict(job.worker(job.payload))
        except JobCancelled:
            # A closing viewer has nobody left to tell.
            if self._is_accepting():
                self._report(Message(
                    "Background job #{job} was stopped before it finished: {description}",
                    job=job.job_id, description=job.description,
                ))
            return
        except Exception as error:
            elapsed = time.perf_counter() - started_at
            self._report(
                str(Message(
                    "Background job #{job} failed after {seconds}s ({command}): {error}",
                    job=job.job_id, seconds=f"{elapsed:.1f}", command=job.command_name, error=error,
                ))
                + f"\n{traceback.format_exc()}"
            )
            return

        elapsed = time.perf_counter() - started_at
        detail = result.get("message") or Message("Saved {path}", path=job.output_path)
        # A stop request is honoured at the worker's check points: past its last one, the job completes.
        if handle.requested:
            message = str(Message(
                "Background job #{job} was told to stop but had no step left to stop at, and completed in {seconds}s: {detail}",
                job=job.job_id, seconds=f"{elapsed:.1f}", detail=detail,
            ))
        else:
            message = str(Message(
                "Background job #{job} completed in {seconds}s: {detail}",
                job=job.job_id, seconds=f"{elapsed:.1f}", detail=detail,
            ))
        if job.output_path not in str(detail):
            # The desktop reveals the folder; the terminal names the file.
            message += f"\nSaved to: {job.output_path}"
        self._report(message)

    def _is_accepting(self):
        with self._lock:
            return self._accepting

    def _report(self, text):
        try:
            self._say(str(text))
        except Exception:
            # A failed report must not stop the queue.
            pass
