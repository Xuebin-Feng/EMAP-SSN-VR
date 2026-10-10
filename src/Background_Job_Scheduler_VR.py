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
"""

from __future__ import annotations

import os
import queue
import threading
import time
import traceback
from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class BackgroundJob:
    job_id: int
    command_name: str
    description: str
    payload: Any
    worker: Callable[[Any], Any]
    output_path: str


class BackgroundJobScheduler:
    """Run command jobs in strict FIFO order on one daemon thread."""

    _STOP = object()

    def __init__(self, say=print):
        #: Prints one report line; the viewer passes its prompt-safe console.
        self._say = say
        self._jobs = queue.Queue()
        self._lock = threading.Lock()
        self._accepting = True
        self._outstanding_count = 0
        self._next_job_id = 1
        self._reserved_output_paths = set()
        # Started by the first job, so a viewer that never queues one never
        # holds a thread.
        self._thread = None

    @staticmethod
    def _output_key(path):
        return os.path.normcase(os.path.abspath(os.fspath(path)))

    @property
    def queue_depth(self):
        """Return the number of running and queued jobs."""
        with self._lock:
            return self._outstanding_count

    def is_output_path_reserved(self, path):
        key = self._output_key(path)
        with self._lock:
            return key in self._reserved_output_paths

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
            queue_position = self._outstanding_count + 1
            job = BackgroundJob(
                job_id=job_id,
                command_name=str(command_name),
                description=str(description),
                payload=payload,
                worker=worker,
                output_path=output_path,
            )
            self._reserved_output_paths.add(output_key)
            self._outstanding_count += 1
            if self._thread is None:
                self._thread = threading.Thread(
                    target=self._worker_loop,
                    name="SSN-VR-Background-Jobs",
                    daemon=True,
                )
                self._thread.start()
            self._jobs.put(job)

        print(
            f"Queued background job #{job_id}: {job.command_name} "
            f"(position {queue_position}) -> {os.path.basename(output_path)}"
        )
        return job_id

    def shutdown(self):
        """Discard queued jobs without waiting for the daemon worker."""
        with self._lock:
            if not self._accepting:
                return
            self._accepting = False

        while True:
            try:
                item = self._jobs.get_nowait()
            except queue.Empty:
                break
            if isinstance(item, BackgroundJob):
                with self._lock:
                    self._reserved_output_paths.discard(
                        self._output_key(item.output_path)
                    )
                    self._outstanding_count -= 1
            self._jobs.task_done()
        self._jobs.put(self._STOP)

    def _worker_loop(self):
        while True:
            job = self._jobs.get()
            if job is self._STOP:
                self._jobs.task_done()
                return

            try:
                with self._lock:
                    accepting = self._accepting
                if accepting:
                    self._run(job)
            finally:
                with self._lock:
                    self._reserved_output_paths.discard(
                        self._output_key(job.output_path)
                    )
                    self._outstanding_count -= 1
                self._jobs.task_done()

    def _run(self, job):
        self._report(f"Running background job #{job.job_id}: {job.description}")
        started_at = time.perf_counter()
        try:
            result = dict(job.worker(job.payload))
        except Exception as error:
            elapsed = time.perf_counter() - started_at
            self._report(
                f"Background job #{job.job_id} failed after {elapsed:.1f}s "
                f"({job.command_name}): {error}\n{traceback.format_exc()}"
            )
            return

        elapsed = time.perf_counter() - started_at
        detail = result.get("message") or f"Saved {job.output_path}"
        message = f"Background job #{job.job_id} completed in {elapsed:.1f}s: {detail}"
        if job.output_path not in str(detail):
            # The desktop reveals the folder; the terminal names the file.
            message += f"\nSaved to: {job.output_path}"
        self._report(message)

    def _report(self, text):
        try:
            self._say(text)
        except Exception:
            # A failed report must not stop the queue.
            pass
