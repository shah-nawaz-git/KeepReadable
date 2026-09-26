import logging
import os
import subprocess
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from keepreadable.utilities.cancellation import CancellationToken, OperationCancelled

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class CommandResult:
    args: tuple[str, ...]
    returncode: int
    stdout: bytes
    stderr: bytes
    duration_seconds: float
    timed_out: bool


class SubprocessError(Exception):
    pass


class ToolNotFoundError(SubprocessError):
    pass


Runner = Callable[..., CommandResult]


class _BoundedBuffer:
    marker = b"\n[output truncated]\n"

    def __init__(self, maximum: int) -> None:
        self.maximum = maximum
        self.data = bytearray()
        self.truncated = False

    def append(self, chunk: bytes) -> None:
        remaining = self.maximum - len(self.data)
        if remaining > 0:
            self.data.extend(chunk[:remaining])
        if len(chunk) > remaining:
            self.truncated = True

    def value(self) -> bytes:
        if not self.truncated:
            return bytes(self.data)
        marker = self.marker[: self.maximum]
        prefix_length = max(0, self.maximum - len(marker))
        return bytes(self.data[:prefix_length]) + marker


def _read_pipe(pipe: BinaryIO, target: _BoundedBuffer) -> None:
    try:
        while chunk := pipe.read(64 * 1024):
            target.append(chunk)
    finally:
        pipe.close()


def _kill_and_wait(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is None:
        process.kill()
    process.wait()


def run_command(
    args: Sequence[str | os.PathLike[str]],
    *,
    timeout: float,
    cancel: CancellationToken | None = None,
    cwd: Path | None = None,
    max_output_bytes: int = 64 * 1024 * 1024,
) -> CommandResult:
    normalized = tuple(os.fspath(argument) for argument in args)
    if not normalized:
        raise ValueError("args must not be empty")
    if any(not isinstance(argument, str) for argument in normalized):
        raise TypeError("all command arguments must resolve to strings")
    if any("\0" in argument for argument in normalized):
        raise ValueError("command arguments must not contain NUL characters")
    if max_output_bytes < 0:
        raise ValueError("max_output_bytes must not be negative")

    started = time.monotonic()
    try:
        process = subprocess.Popen(
            normalized,
            shell=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=os.fspath(cwd) if cwd is not None else None,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0,
        )
    except FileNotFoundError as exc:
        raise ToolNotFoundError(f"Tool not found: {normalized[0]}") from exc

    assert process.stdout is not None
    assert process.stderr is not None
    stdout_buffer = _BoundedBuffer(max_output_bytes)
    stderr_buffer = _BoundedBuffer(max_output_bytes)
    threads = [
        threading.Thread(target=_read_pipe, args=(process.stdout, stdout_buffer), daemon=True),
        threading.Thread(target=_read_pipe, args=(process.stderr, stderr_buffer), daemon=True),
    ]
    for thread in threads:
        thread.start()

    timed_out = False
    deadline = started + timeout
    try:
        while process.poll() is None:
            if cancel is not None and cancel.is_cancelled:
                _kill_and_wait(process)
                raise OperationCancelled
            if time.monotonic() >= deadline:
                timed_out = True
                _kill_and_wait(process)
                break
            time.sleep(0.05)
    finally:
        if process.poll() is None:
            _kill_and_wait(process)
        for thread in threads:
            thread.join()

    duration = time.monotonic() - started
    result = CommandResult(
        args=normalized,
        returncode=process.returncode,
        stdout=stdout_buffer.value(),
        stderr=stderr_buffer.value(),
        duration_seconds=duration,
        timed_out=timed_out,
    )
    logger.debug(
        "Command %s completed in %.3fs with return code %s",
        Path(normalized[0]).name,
        duration,
        process.returncode,
    )
    return result
