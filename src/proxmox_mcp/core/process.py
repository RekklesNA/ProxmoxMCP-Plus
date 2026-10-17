"""Run headless subprocesses with bounded in-memory output capture."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from threading import Thread
from typing import Any


@dataclass
class ProcessResult:
    returncode: int
    stdout: str
    stderr: str
    output_truncated: bool


def run_bounded(args: list[str], *, timeout: float, stdin: Any = subprocess.DEVNULL, max_output_bytes: int = 1048576) -> ProcessResult:
    if max_output_bytes < 1 or timeout <= 0:
        raise ValueError("Output limit and timeout must be positive")
    process = subprocess.Popen(args, stdin=stdin, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    buffers = [bytearray(), bytearray()]
    truncated = [False, False]

    def drain(stream: Any, index: int) -> None:
        try:
            while True:
                chunk = stream.read(65536)
                if not chunk:
                    return
                capacity = max_output_bytes - len(buffers[index])
                buffers[index].extend(chunk[:capacity])
                truncated[index] |= len(chunk) > capacity
        finally:
            stream.close()

    threads = [Thread(target=drain, args=(stream, index), daemon=True) for index, stream in enumerate((process.stdout, process.stderr))]
    for thread in threads:
        thread.start()
    try:
        code = process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()
        code = 124
    finally:
        for thread in threads:
            thread.join(timeout=1)
    return ProcessResult(code, buffers[0].decode("utf-8", errors="replace"), buffers[1].decode("utf-8", errors="replace"), any(truncated))
