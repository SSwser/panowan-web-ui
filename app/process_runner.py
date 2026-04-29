from __future__ import annotations

import os
import signal
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass

_CANCEL_POLL_INTERVAL_SECONDS = 0.25
ProcessOutput = str | bytes


class ProcessCancelledError(RuntimeError):
    def __init__(self, stdout: ProcessOutput, stderr: ProcessOutput) -> None:
        super().__init__("Process cancelled")
        self.stdout = stdout
        self.stderr = stderr


@dataclass(frozen=True)
class ProcessRunResult:
    process: subprocess.Popen
    stdout: ProcessOutput
    stderr: ProcessOutput


def run_cancellable_process(
    command: list[str],
    *,
    timeout_seconds: int,
    should_cancel: Callable[[], bool] | None = None,
    cwd: str | None = None,
    text: bool = False,
) -> ProcessRunResult:
    process = subprocess.Popen(
        command,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=text,
        start_new_session=(os.name != "nt"),
    )
    try:
        stdout, stderr = _communicate_with_cancellation(
            process,
            timeout_seconds=timeout_seconds,
            should_cancel=should_cancel,
        )
    except subprocess.TimeoutExpired:
        terminate_process_tree(process)
        process.communicate()
        raise
    return ProcessRunResult(process=process, stdout=stdout, stderr=stderr)


def terminate_process_tree(process: subprocess.Popen) -> None:
    if os.name == "nt":
        process.kill()
        return

    kill_signal = getattr(signal, "SIGKILL", signal.SIGTERM)

    try:
        os.killpg(os.getpgid(process.pid), kill_signal)
    except (ProcessLookupError, PermissionError):
        process.kill()


def output_tail(output: ProcessOutput, limit: int = 500) -> str:
    if not output:
        return ""
    if isinstance(output, str):
        return output[-limit:]
    return bytes(output[-limit:]).decode(errors="replace")


def _communicate_with_cancellation(
    process: subprocess.Popen,
    timeout_seconds: int,
    should_cancel: Callable[[], bool] | None,
) -> tuple[ProcessOutput, ProcessOutput]:
    deadline = time.monotonic() + timeout_seconds

    while True:
        if should_cancel and should_cancel():
            terminate_process_tree(process)
            stdout, stderr = process.communicate()
            raise ProcessCancelledError(stdout=stdout, stderr=stderr)

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise subprocess.TimeoutExpired(process.args, timeout_seconds)

        try:
            return process.communicate(
                timeout=min(_CANCEL_POLL_INTERVAL_SECONDS, remaining)
            )
        except subprocess.TimeoutExpired:
            continue
