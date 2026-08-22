#!/usr/bin/env python3
"""Per-camera supervised runtime lifecycle manager for the YI Home Add-on.

The lifecycle manager is the Add-on-owned replacement for relying on go2rtc
preload entries to recreate a failed native PPPP/TNP producer. Each camera is
managed independently by secret-safe stable_id.

For Phase 6C.2 the supervised MPEG-TS output is intentionally drained to
/dev/null. Phase 6C.5 will attach the Add-on-owned media publisher to this
output. This separation lets lifecycle/start/stop/restart semantics be proven
before media publication ownership is moved.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

STABLE_ID_RE = re.compile(r"^[0-9a-f]{20}$")


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def default_runtime_state_dir() -> Path:
    override = os.getenv("YI_RUNTIME_STATE_DIR")
    if override:
        return Path(override).expanduser()
    state_home = os.getenv("XDG_STATE_HOME")
    base = Path(state_home).expanduser() if state_home else Path.home() / ".local" / "state"
    return base / "yi-cam-integration" / "runtime"


def _stable_id(value: str) -> str:
    normalized = value.strip().casefold()
    if not STABLE_ID_RE.fullmatch(normalized):
        raise ValueError("stable_id must be exactly 20 lowercase hexadecimal characters")
    return normalized


@dataclass(frozen=True)
class RuntimeLifecycleConfig:
    python: str
    env_file: Path
    runtime_root: Path
    worker_dir: Path
    stable_relay: Path
    supervisor: Path
    state_dir: Path
    qemu: str = "qemu-aarch64"
    ffmpeg: str = "ffmpeg"
    ffprobe: str = "ffprobe"
    startup_timeout: float = 45.0
    stall_timeout: float = 12.0
    terminate_grace: float = 3.0
    restart_delay: float = 1.0
    max_restart_delay: float = 30.0

    def validate(self) -> None:
        if not Path(self.python).is_file():
            raise RuntimeError(f"runtime python missing: {self.python}")
        for path, label in (
            (self.env_file, "env file"),
            (self.stable_relay, "stable relay"),
            (self.supervisor, "supervisor"),
        ):
            if not path.is_file():
                raise RuntimeError(f"{label} missing: {path}")
        if not self.runtime_root.is_dir():
            raise RuntimeError(f"runtime root missing: {self.runtime_root}")
        if not self.worker_dir.is_dir():
            raise RuntimeError(f"worker directory missing: {self.worker_dir}")
        if self.startup_timeout <= 0 or self.stall_timeout <= 0:
            raise RuntimeError("runtime timeouts must be greater than zero")
        if self.terminate_grace <= 0 or self.restart_delay < 0 or self.max_restart_delay <= 0:
            raise RuntimeError("runtime lifecycle timing configuration is invalid")


class _CameraRuntimeController:
    def __init__(self, stable_id: str, config: RuntimeLifecycleConfig) -> None:
        self.stable_id = _stable_id(stable_id)
        self.config = config
        self.lock = threading.RLock()
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None
        self.process: subprocess.Popen[bytes] | None = None
        self.desired_running = False
        self.state = "stopped"
        self.pid: int | None = None
        self.generation = 0
        self.restart_count = 0
        self.last_exit_code: int | None = None
        self.last_error: str | None = None
        self.last_reason: str | None = None
        self.started_at: str | None = None
        self.updated_at = _utc_now()

    @property
    def log_path(self) -> Path:
        return self.config.state_dir / f"{self.stable_id}.log"

    def _set_state(self, state: str, *, reason: str | None = None, error: str | None = None) -> None:
        with self.lock:
            self.state = state
            self.last_reason = reason
            self.last_error = error
            self.updated_at = _utc_now()

    def safe_status(self) -> dict[str, Any]:
        with self.lock:
            process_alive = self.process is not None and self.process.poll() is None
            return {
                "stable_id": self.stable_id,
                "runtime_state": self.state,
                "desired_running": self.desired_running,
                "process_alive": process_alive,
                "pid": self.pid if process_alive else None,
                "generation": self.generation,
                "restart_count": self.restart_count,
                "last_exit_code": self.last_exit_code,
                "last_reason": self.last_reason,
                "last_error": self.last_error,
                "started_at": self.started_at,
                "updated_at": self.updated_at,
                "media_publisher_attached": False,
                "secrets_exposed": False,
            }

    def _command(self) -> list[str]:
        cfg = self.config
        return [
            cfg.python,
            str(cfg.supervisor),
            "--startup-timeout",
            f"{cfg.startup_timeout:g}",
            "--stall-timeout",
            f"{cfg.stall_timeout:g}",
            "--terminate-grace",
            f"{cfg.terminate_grace:g}",
            "--",
            cfg.python,
            str(cfg.stable_relay),
            "--stable-id",
            self.stable_id,
            "--env-file",
            str(cfg.env_file),
            "--runtime",
            str(cfg.runtime_root),
            "--worker-dir",
            str(cfg.worker_dir),
            "--qemu",
            cfg.qemu,
            "--ffmpeg",
            cfg.ffmpeg,
            "--ffprobe",
            cfg.ffprobe,
            "--stdout",
        ]

    def _terminate_process(self, process: subprocess.Popen[bytes]) -> None:
        if process.poll() is not None:
            return
        try:
            process.terminate()
        except ProcessLookupError:
            return
        try:
            process.wait(timeout=self.config.terminate_grace + 5.0)
            return
        except subprocess.TimeoutExpired:
            pass
        try:
            process.kill()
        except ProcessLookupError:
            return
        try:
            process.wait(timeout=2.0)
        except subprocess.TimeoutExpired:
            pass

    def _run(self) -> None:
        first_launch = True
        consecutive_restarts = 0
        try:
            while not self.stop_event.is_set():
                with self.lock:
                    if not self.desired_running:
                        break
                self._set_state("starting" if first_launch else "restarting")
                self.config.state_dir.mkdir(parents=True, exist_ok=True)
                try:
                    log_stream = self.log_path.open("ab", buffering=0)
                    try:
                        process = subprocess.Popen(
                            self._command(),
                            stdin=subprocess.DEVNULL,
                            stdout=subprocess.DEVNULL,
                            stderr=log_stream,
                            start_new_session=True,
                        )
                    except Exception:
                        log_stream.close()
                        raise
                except OSError:
                    self._set_state(
                        "error",
                        reason="spawn_failed",
                        error="The supervised camera runtime could not be started.",
                    )
                    with self.lock:
                        self.desired_running = False
                    break

                launched_mono = time.monotonic()
                with self.lock:
                    self.process = process
                    self.pid = process.pid
                    self.generation += 1
                    self.started_at = _utc_now()
                    self.last_error = None
                    self.last_reason = "started" if first_launch else "recreated_after_exit"
                    self.state = "running"
                    self.updated_at = _utc_now()
                first_launch = False

                rc = process.wait()
                log_stream.close()
                runtime_seconds = time.monotonic() - launched_mono
                with self.lock:
                    self.process = None
                    self.pid = None
                    self.last_exit_code = rc
                    should_continue = self.desired_running and not self.stop_event.is_set()

                if not should_continue:
                    break

                consecutive_restarts = 0 if runtime_seconds >= 60.0 else consecutive_restarts + 1
                with self.lock:
                    self.restart_count += 1
                    self.state = "restarting"
                    self.last_reason = "media_stall" if rc == 75 else "runtime_exit"
                    self.updated_at = _utc_now()

                delay = min(
                    self.config.restart_delay * (2 ** min(max(consecutive_restarts - 1, 0), 5)),
                    self.config.max_restart_delay,
                )
                if self.stop_event.wait(delay):
                    break
        finally:
            with self.lock:
                process = self.process
            if process is not None and process.poll() is None:
                self._terminate_process(process)
            with self.lock:
                self.process = None
                self.pid = None
                if self.state != "error":
                    self.state = "stopped"
                    self.last_reason = "stopped"
                self.updated_at = _utc_now()

    def start(self) -> dict[str, Any]:
        with self.lock:
            if self.desired_running and self.thread is not None and self.thread.is_alive():
                return self.safe_status()
            self.stop_event = threading.Event()
            self.desired_running = True
            self.last_error = None
            self.state = "starting"
            self.last_reason = "start_requested"
            self.updated_at = _utc_now()
            self.thread = threading.Thread(
                target=self._run,
                name=f"yi-runtime-{self.stable_id[:8]}",
                daemon=True,
            )
            thread = self.thread
        thread.start()
        return self.safe_status()

    def stop(self) -> dict[str, Any]:
        with self.lock:
            self.desired_running = False
            self.stop_event.set()
            process = self.process
            thread = self.thread
            if self.state not in {"stopped", "error"}:
                self.state = "stopping"
                self.last_reason = "stop_requested"
                self.updated_at = _utc_now()
        if process is not None and process.poll() is None:
            self._terminate_process(process)
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=self.config.terminate_grace + 8.0)
        with self.lock:
            if self.thread is thread and (thread is None or not thread.is_alive()):
                self.thread = None
            if self.process is None and self.state != "error":
                self.state = "stopped"
                self.last_reason = "stopped"
                self.updated_at = _utc_now()
        return self.safe_status()

    def restart(self) -> dict[str, Any]:
        self.stop()
        with self.lock:
            self.last_reason = "restart_requested"
        return self.start()


class YiRuntimeLifecycleManager:
    """Own independent supervised camera runtimes by stable_id."""

    def __init__(self, config: RuntimeLifecycleConfig) -> None:
        config.validate()
        self.config = config
        self.config.state_dir.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self.config.state_dir, 0o700)
        except OSError:
            pass
        self._lock = threading.RLock()
        self._controllers: dict[str, _CameraRuntimeController] = {}

    def _controller(self, stable_id: str) -> _CameraRuntimeController:
        key = _stable_id(stable_id)
        with self._lock:
            controller = self._controllers.get(key)
            if controller is None:
                controller = _CameraRuntimeController(key, self.config)
                self._controllers[key] = controller
            return controller

    def start(self, stable_id: str) -> dict[str, Any]:
        return self._controller(stable_id).start()

    def stop(self, stable_id: str) -> dict[str, Any]:
        return self._controller(stable_id).stop()

    def restart(self, stable_id: str) -> dict[str, Any]:
        return self._controller(stable_id).restart()

    def status(self, stable_id: str) -> dict[str, Any]:
        key = _stable_id(stable_id)
        with self._lock:
            controller = self._controllers.get(key)
        if controller is None:
            return {
                "stable_id": key,
                "runtime_state": "stopped",
                "desired_running": False,
                "process_alive": False,
                "pid": None,
                "generation": 0,
                "restart_count": 0,
                "last_exit_code": None,
                "last_reason": None,
                "last_error": None,
                "started_at": None,
                "updated_at": None,
                "media_publisher_attached": False,
                "secrets_exposed": False,
            }
        return controller.safe_status()

    def managed_count(self) -> int:
        with self._lock:
            return sum(
                1
                for controller in self._controllers.values()
                if controller.safe_status()["desired_running"]
            )

    def shutdown_all(self) -> None:
        with self._lock:
            controllers = list(self._controllers.values())
        for controller in controllers:
            controller.stop()


def build_default_config(
    *,
    env_file: Path,
    root: Path | None = None,
    python: str | None = None,
    runtime_root: Path | None = None,
    worker_dir: Path | None = None,
    state_dir: Path | None = None,
    startup_timeout: float = 45.0,
    stall_timeout: float = 12.0,
    terminate_grace: float = 3.0,
    restart_delay: float = 1.0,
    max_restart_delay: float = 30.0,
) -> RuntimeLifecycleConfig:
    project_root = (root or Path(__file__).resolve().parent).resolve()
    selected_runtime = (runtime_root or project_root / ".analysis" / "phase3" / "bionic-root").resolve()
    selected_worker = (
        worker_dir or selected_runtime / "data" / "local" / "tmp" / "yi-phase3g"
    ).resolve()
    return RuntimeLifecycleConfig(
        python=python or sys.executable,
        env_file=env_file.resolve(),
        runtime_root=selected_runtime,
        worker_dir=selected_worker,
        stable_relay=project_root / "yi_native_av_relay_stable.py",
        supervisor=project_root / "yi_native_session_supervisor.py",
        state_dir=(state_dir or default_runtime_state_dir()).resolve(),
        startup_timeout=startup_timeout,
        stall_timeout=stall_timeout,
        terminate_grace=terminate_grace,
        restart_delay=restart_delay,
        max_restart_delay=max_restart_delay,
    )
