#!/usr/bin/env python3
"""Supervise a continuous native YI relay and fail fast on media stalls.

The proven relay remains responsible for PPPP/TNP and MPEG-TS generation. This
wrapper only forwards its stdout to go2rtc and watches for forward progress. If
the child stops producing bytes after startup, the wrapper terminates the full
relay process group and exits non-zero so a persistent go2rtc preload consumer
can recreate a fresh producer/session without leaving QEMU/FFmpeg orphans.
"""

from __future__ import annotations

import argparse
import errno
import os
import selectors
import signal
import subprocess
import sys
import time
from typing import BinaryIO


def log(message: str) -> None:
    try:
        print(f"[yi-session-supervisor] {message}", file=sys.stderr, flush=True)
    except (BrokenPipeError, OSError, ValueError):
        pass


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Watch a native YI relay for media stalls")
    p.add_argument("--startup-timeout", type=float, default=45.0)
    p.add_argument("--stall-timeout", type=float, default=12.0)
    p.add_argument("--terminate-grace", type=float, default=3.0)
    p.add_argument("command", nargs=argparse.REMAINDER)
    return p


def signal_child_group(child: subprocess.Popen[bytes], sig: signal.Signals) -> None:
    """Signal the relay and every descendant in its dedicated process group."""
    try:
        os.killpg(child.pid, sig)
        return
    except ProcessLookupError:
        return
    except (PermissionError, OSError):
        # Defensive fallback. With start_new_session=True the child PID is the
        # process-group ID, so killpg is the normal path.
        if child.poll() is None:
            try:
                child.send_signal(sig)
            except ProcessLookupError:
                pass


def terminate_child(child: subprocess.Popen[bytes], grace: float) -> None:
    if child.poll() is not None:
        return
    log("terminate_scope=process_group; signal=SIGTERM")
    signal_child_group(child, signal.SIGTERM)
    try:
        child.wait(timeout=max(0.1, grace))
        return
    except subprocess.TimeoutExpired:
        pass
    log("terminate_scope=process_group; signal=SIGKILL")
    signal_child_group(child, signal.SIGKILL)
    try:
        child.wait(timeout=2.0)
    except subprocess.TimeoutExpired:
        pass


def write_all(output: BinaryIO, data: bytes) -> None:
    view = memoryview(data)
    while view:
        written = output.write(view)
        if written is None:
            output.flush()
            return
        view = view[written:]
    output.flush()


def main() -> int:
    args = parser().parse_args()
    command = list(args.command)
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        raise SystemExit("missing relay command after --")
    if args.startup_timeout <= 0 or args.stall_timeout <= 0:
        raise SystemExit("timeouts must be greater than zero")

    log(
        f"START startup_timeout={args.startup_timeout:g}s; "
        f"stall_timeout={args.stall_timeout:g}s"
    )
    child = subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=None,
        bufsize=0,
        start_new_session=True,
    )
    if child.stdout is None:
        raise RuntimeError("failed to capture relay stdout")

    stop_requested = False

    def handle_signal(_signum: int, _frame: object) -> None:
        nonlocal stop_requested
        stop_requested = True
        terminate_child(child, args.terminate_grace)

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    fd = child.stdout.fileno()
    os.set_blocking(fd, False)
    selector = selectors.DefaultSelector()
    selector.register(fd, selectors.EVENT_READ)

    launched = time.monotonic()
    last_data = launched
    started = False
    total = 0

    try:
        while True:
            now = time.monotonic()
            limit = args.stall_timeout if started else args.startup_timeout
            elapsed = now - last_data
            wait_for = max(0.05, min(1.0, limit - elapsed))
            events = selector.select(wait_for)

            if events:
                try:
                    chunk = os.read(fd, 65536)
                except BlockingIOError:
                    chunk = b""
                if chunk:
                    if not started:
                        started = True
                        log(f"media_started=true; first_chunk_bytes={len(chunk)}")
                    last_data = time.monotonic()
                    total += len(chunk)
                    try:
                        write_all(sys.stdout.buffer, chunk)
                    except BrokenPipeError:
                        log("consumer_closed=true; reason=EPIPE")
                        terminate_child(child, args.terminate_grace)
                        return 0
                    except OSError as exc:
                        if exc.errno == errno.EPIPE:
                            log("consumer_closed=true; reason=EPIPE")
                            terminate_child(child, args.terminate_grace)
                            return 0
                        raise
                    continue

                rc = child.poll()
                if rc is not None:
                    log(f"relay_exit_rc={rc}; forwarded_bytes={total}")
                    return rc if rc != 0 else 0

            rc = child.poll()
            if rc is not None:
                log(f"relay_exit_rc={rc}; forwarded_bytes={total}")
                return rc if rc != 0 else 0

            now = time.monotonic()
            elapsed = now - last_data
            if not started and elapsed >= args.startup_timeout:
                log(
                    f"startup_stall_detected=true; silence_seconds={elapsed:.1f}; "
                    "action=terminate_and_recreate"
                )
                terminate_child(child, args.terminate_grace)
                return 75
            if started and elapsed >= args.stall_timeout:
                log(
                    f"media_stall_detected=true; silence_seconds={elapsed:.1f}; "
                    f"forwarded_bytes={total}; action=terminate_and_recreate"
                )
                terminate_child(child, args.terminate_grace)
                return 75
            if stop_requested:
                return 0
    finally:
        selector.close()
        if child.poll() is None:
            terminate_child(child, args.terminate_grace)


if __name__ == "__main__":
    raise SystemExit(main())
