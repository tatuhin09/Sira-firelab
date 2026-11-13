"""Bounded subprocess runner for SIRA's existing scholarly research orchestrator."""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
from typing import Any

from .paths import FireLabPaths

MAX_WORKER_INPUT_BYTES = 4096
MAX_WORKER_OUTPUT_BYTES = 512 * 1024
WORKER_TIMEOUT_SECONDS = 30
logger = logging.getLogger(__name__)


class WorkerFailure(RuntimeError):
    pass


class WorkerTimeout(WorkerFailure):
    pass


class WorkerOutputTooLarge(WorkerFailure):
    pass


def build_worker_environment(paths: FireLabPaths) -> dict[str, str]:
    """Construct a fixed allowlist; never inherit the server environment."""
    return {
        "PATH": "/usr/bin:/bin",
        "HOME": str(paths.worker_home),
        "TMPDIR": str(paths.worker_tmp),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
    }


def _drain_bounded(stream, *, limit: int | None = None) -> tuple[bytes, int, bool]:
    captured = bytearray()
    total = 0
    overflow = False
    while True:
        chunk = stream.read(16384)
        if not chunk:
            break
        total += len(chunk)
        if limit is None:
            continue
        remaining = max(0, limit - len(captured))
        if remaining:
            captured.extend(chunk[:remaining])
        if len(chunk) > remaining:
            overflow = True
    return bytes(captured), total, overflow


class SiraResearchRunner:
    def __init__(self, paths: FireLabPaths, *, timeout: int = WORKER_TIMEOUT_SECONDS):
        if type(timeout) is not int or not 1 <= timeout <= 30:
            raise ValueError("worker timeout must be 1..30 seconds")
        self.paths = paths
        self.timeout = timeout
        self.paths.prepare()

    def run(self, query: str) -> dict[str, Any]:
        payload = json.dumps({"protocol": 1, "query": query}, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if len(payload) > MAX_WORKER_INPUT_BYTES:
            raise WorkerFailure("worker input exceeded its bound")
        self.paths.assert_isolated_sira_root()
        env = build_worker_environment(self.paths)
        command = [
            str(Path(sys.executable).resolve()), "-I", "-B",
            str(self.paths.worker_script), str(self.paths.repo_src), str(self.paths.sira_root),
        ]
        try:
            process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=self.paths.worker_cwd,
                env=env,
                start_new_session=True,
                close_fds=True,
            )
        except OSError as exc:
            logger.warning("FireLab worker start failed (%s)", type(exc).__name__)
            raise WorkerFailure("research worker could not start") from None

        stdout_result: list[tuple[bytes, int, bool]] = []
        stderr_result: list[tuple[bytes, int, bool]] = []
        stdout_thread = threading.Thread(
            target=lambda: stdout_result.append(_drain_bounded(process.stdout, limit=MAX_WORKER_OUTPUT_BYTES)),
            daemon=True,
        )
        stderr_thread = threading.Thread(
            target=lambda: stderr_result.append(_drain_bounded(process.stderr, limit=None)),
            daemon=True,
        )
        stdout_thread.start()
        stderr_thread.start()
        try:
            try:
                assert process.stdin is not None
                process.stdin.write(payload)
                process.stdin.close()
            except OSError:
                pass
            try:
                process.wait(timeout=self.timeout)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait()
                logger.warning("FireLab worker timed out")
                raise WorkerTimeout("research worker timed out") from None
        finally:
            if process.stdin and not process.stdin.closed:
                process.stdin.close()
            stdout_thread.join(timeout=2)
            stderr_thread.join(timeout=2)
            if process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait()

        self.paths.assert_isolated_sira_root()
        if not stdout_result:
            raise WorkerFailure("research worker returned no response")
        output, output_size, overflow = stdout_result[0]
        stderr_size = stderr_result[0][1] if stderr_result else 0
        if overflow or output_size > MAX_WORKER_OUTPUT_BYTES:
            logger.warning("FireLab worker output exceeded limit (stderr_bytes=%d)", stderr_size)
            raise WorkerOutputTooLarge("research worker response exceeded its limit")
        if process.returncode != 0:
            logger.warning("FireLab worker failed (exit=%d, stderr_bytes=%d)", process.returncode, stderr_size)
            raise WorkerFailure("research worker failed")
        try:
            result = json.loads(output.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError):
            raise WorkerFailure("research worker response was invalid") from None
        if not isinstance(result, dict):
            raise WorkerFailure("research worker response was invalid")
        return result
