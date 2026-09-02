"""Run a process with bounded diagnostic output and a hard output limit."""

from __future__ import annotations

import os
import queue
import signal
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from cogito_common import CogitoError


TERMINATION_DRAIN_SECONDS = 2


@dataclass(frozen=True)
class ProcessCapture:
    exit_code: int | None
    timed_out: bool
    output_limit_exceeded: bool
    termination_degraded: bool
    stdout: bytes
    stderr: bytes
    stdout_bytes: int
    stderr_bytes: int
    stdout_truncated: bool
    stderr_truncated: bool


class _HeadTailBuffer:
    """Keep bounded head and tail bytes while counting the full stream."""

    def __init__(self, capacity: int):
        self.capacity = capacity
        self.head_capacity = capacity // 2
        self.tail_capacity = capacity - self.head_capacity
        self.head = bytearray()
        self.tail = bytearray()
        self.total = 0

    def append(self, chunk: bytes) -> None:
        self.total += len(chunk)
        head_room = self.head_capacity - len(self.head)
        if head_room > 0:
            self.head.extend(chunk[:head_room])
            chunk = chunk[head_room:]
        if chunk and self.tail_capacity:
            self.tail.extend(chunk)
            overflow = len(self.tail) - self.tail_capacity
            if overflow > 0:
                del self.tail[:overflow]

    def value(self) -> bytes:
        return bytes(self.head + self.tail)

    @property
    def truncated(self) -> bool:
        return self.total > self.capacity


def _reader(name: str, pipe, output: queue.Queue[tuple[str, bytes | None]]) -> None:
    try:
        for chunk in iter(lambda: pipe.read(8192), b""):
            output.put((name, chunk))
    except (OSError, ValueError):
        pass
    finally:
        try:
            pipe.close()
        except OSError:
            pass
        try:
            output.put((name, None), timeout=0.1)
        except queue.Full:
            pass


def _stop_process_group(process: subprocess.Popen[bytes]) -> tuple[bool, str | None]:
    if os.name == "posix":
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            return False, None
        except OSError as exc:
            if process.poll() is not None:
                return True, None
            try:
                process.kill()
            except OSError as kill_exc:
                return True, (
                    "cannot terminate controlled check process: "
                    f"group error={exc}; direct error={kill_exc}"
                )
            return True, None
        deadline = time.monotonic() + 1
        while process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.01)
        try:
            # The direct child may already have exited while descendants still
            # hold the pipes, so always finish the dedicated process group.
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        except OSError as exc:
            if process.poll() is None:
                try:
                    process.kill()
                except OSError as kill_exc:
                    return True, (
                        "cannot kill controlled check process: "
                        f"group error={exc}; direct error={kill_exc}"
                    )
            return True, None
        return False, None
    try:  # pragma: no cover - exercised on Windows hosts
        result = subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            shell=False,
            check=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        result = None
        failure = str(exc)
    else:
        failure = f"taskkill exited with status {result.returncode}"
    if result is not None and result.returncode == 0:
        return False, None
    if process.poll() is None:
        try:
            process.kill()
            process.wait(timeout=1)
        except (OSError, subprocess.TimeoutExpired) as exc:
            failure = f"{failure}; direct process kill failed: {exc}"
        if process.poll() is None:
            return True, f"cannot terminate controlled check process tree: {failure}"
        return True, None
    return True, None


def _close_capture_pipes(process: subprocess.Popen[bytes]) -> None:
    def close(pipe) -> None:
        try:
            pipe.close()
        except OSError:
            pass

    for pipe in (process.stdout, process.stderr):
        if pipe is None:
            continue
        # BufferedReader owns its fd. Close through that owner in a daemon
        # thread so a blocked read cannot stall the runner or double-close a
        # raw fd that the OS may already have reused.
        threading.Thread(target=close, args=(pipe,), daemon=True).start()


def run_bounded_process(
    argv: Sequence[str],
    *,
    cwd: Path,
    env: Mapping[str, str],
    timeout_seconds: int,
    evidence_cap: int,
    output_limit: int,
) -> ProcessCapture:
    """Capture bounded head/tail output and stop the process at its hard limit."""
    stdout_buffer = _HeadTailBuffer(evidence_cap)
    stderr_buffer = _HeadTailBuffer(evidence_cap)
    process_kwargs = {"start_new_session": True} if os.name == "posix" else {
        "creationflags": subprocess.CREATE_NEW_PROCESS_GROUP
    }
    try:
        process = subprocess.Popen(
            list(argv),
            cwd=cwd,
            env=dict(env),
            shell=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            **process_kwargs,
        )
    except OSError as exc:
        message = str(exc).encode("utf-8", errors="replace")
        stderr_buffer.append(message)
        return ProcessCapture(
            127, False, False, False, b"", stderr_buffer.value(), 0, len(message),
            False, stderr_buffer.truncated,
        )

    assert process.stdout is not None and process.stderr is not None
    chunks: queue.Queue[tuple[str, bytes | None]] = queue.Queue(maxsize=64)
    readers = [
        threading.Thread(target=_reader, args=("stdout", process.stdout, chunks), daemon=True),
        threading.Thread(target=_reader, args=("stderr", process.stderr, chunks), daemon=True),
    ]
    for reader in readers:
        reader.start()

    deadline = time.monotonic() + timeout_seconds
    closed: set[str] = set()
    timed_out = False
    output_limit_exceeded = False
    termination_degraded = False
    termination_deadline: float | None = None
    termination_error: str | None = None
    # EOF only finishes capture. A process may close its streams and continue
    # working, so keep the original deadline active until it also exits.
    while process.poll() is None or len(closed) < 2:
        if termination_deadline is not None and time.monotonic() >= termination_deadline:
            _close_capture_pipes(process)
            break
        if not timed_out and not output_limit_exceeded and time.monotonic() >= deadline:
            timed_out = True
            degraded, error = _stop_process_group(process)
            termination_degraded |= degraded
            termination_error = error or termination_error
            termination_deadline = time.monotonic() + TERMINATION_DRAIN_SECONDS
        try:
            name, chunk = chunks.get(timeout=0.05)
        except queue.Empty:
            # A reader's EOF sentinel can be dropped when the queue is full.
            # Once all producers stopped, an empty queue means capture is done;
            # it says nothing about whether the process itself has finished.
            if all(not reader.is_alive() for reader in readers) and chunks.empty():
                closed.update(("stdout", "stderr"))
            continue
        if chunk is None:
            closed.add(name)
            continue
        target = stdout_buffer if name == "stdout" else stderr_buffer
        target.append(chunk)
        if (
            not timed_out
            and not output_limit_exceeded
            and stdout_buffer.total + stderr_buffer.total > output_limit
        ):
            output_limit_exceeded = True
            degraded, error = _stop_process_group(process)
            termination_degraded |= degraded
            termination_error = error or termination_error
            termination_deadline = time.monotonic() + TERMINATION_DRAIN_SECONDS

    for reader in readers:
        reader.join(timeout=1)
    if process.poll() is None:
        degraded, error = _stop_process_group(process)
        termination_degraded |= degraded
        termination_error = error or termination_error
    try:
        process.wait(timeout=1)
    except subprocess.TimeoutExpired:
        _close_capture_pipes(process)
        raise CogitoError("controlled check process did not terminate")
    if termination_error:
        raise CogitoError(termination_error)
    exit_code = None if timed_out or output_limit_exceeded else process.returncode
    return ProcessCapture(
        exit_code=exit_code,
        timed_out=timed_out,
        output_limit_exceeded=output_limit_exceeded,
        termination_degraded=termination_degraded,
        stdout=stdout_buffer.value(),
        stderr=stderr_buffer.value(),
        stdout_bytes=stdout_buffer.total,
        stderr_bytes=stderr_buffer.total,
        stdout_truncated=stdout_buffer.truncated,
        stderr_truncated=stderr_buffer.truncated,
    )
