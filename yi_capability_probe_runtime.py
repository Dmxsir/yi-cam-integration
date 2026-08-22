#!/usr/bin/env python3
"""Bounded live capability probe used by the YI Home Add-on backend.

The probe resolves a camera only by secret-safe stable_id, runs the proven
native relay for a bounded duration, validates observed H264/AAC media with
ffprobe, and only then atomically updates the capability cache.

A failed probe never overwrites a previously proven capability record.
Transient PPPP session handoff failures are retried in a bounded way because a
reprobe may follow immediately after stopping an existing camera runtime.
Every relay attempt owns a dedicated process group so timeout or Add-on shutdown
cannot leave relay/QEMU/FFmpeg descendants behind.

A relay that already produced media may take longer than the probe budget to
finish its native worker shutdown. In that case the probe terminates the whole
process group and lets ffprobe decide success from the actual captured media.
Capability support is therefore based on observed media, not worker exit speed.
"""

from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO

from yi_camera_runtime import PROVEN_PROFILE
from yi_capability_cache import CapabilityRecord, YiCapabilityCache
from yi_runtime_lifecycle import RuntimeLifecycleConfig

STABLE_ID_RE = re.compile(r"^[0-9a-f]{20}$")


class CapabilityProbeError(RuntimeError):
    def __init__(self, category: str, safe_message: str) -> None:
        super().__init__(safe_message)
        self.category = category
        self.safe_message = safe_message


@dataclass(frozen=True)
class CapabilityProbeResult:
    stable_id: str
    profile: str
    capability: CapabilityRecord
    duration_seconds: float
    attempts_used: int
    forced_shutdown_after_media: bool

    def safe_dict(self) -> dict[str, Any]:
        return {
            "stable_id": self.stable_id,
            "profile": self.profile,
            "duration_seconds": self.duration_seconds,
            "attempts_used": self.attempts_used,
            "forced_shutdown_after_media": self.forced_shutdown_after_media,
            "capability": self.capability.safe_dict(),
            "secrets_exposed": False,
        }


def _stable_id(value: str) -> str:
    normalized = value.strip().casefold()
    if not STABLE_ID_RE.fullmatch(normalized):
        raise ValueError("stable_id must be exactly 20 lowercase hexadecimal characters")
    return normalized


def _validated_media(probe_json: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        payload = json.loads(probe_json.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CapabilityProbeError(
            "media_validation_failed",
            "The live probe did not produce readable media metadata.",
        ) from exc

    streams = payload.get("streams") if isinstance(payload, dict) else None
    if not isinstance(streams, list):
        raise CapabilityProbeError(
            "media_validation_failed",
            "The live probe did not produce a valid media stream list.",
        )

    video = next(
        (
            item
            for item in streams
            if isinstance(item, dict)
            and item.get("codec_type") == "video"
            and item.get("codec_name") == "h264"
            and int(item.get("width", 0) or 0) > 0
            and int(item.get("height", 0) or 0) > 0
        ),
        None,
    )
    audio = next(
        (
            item
            for item in streams
            if isinstance(item, dict)
            and item.get("codec_type") == "audio"
            and item.get("codec_name") == "aac"
            and int(item.get("sample_rate", 0) or 0) > 0
            and int(item.get("channels", 0) or 0) > 0
        ),
        None,
    )
    if video is None or audio is None:
        raise CapabilityProbeError(
            "media_validation_failed",
            "The live probe did not prove both H264 video and AAC audio.",
        )
    return video, audio


class YiCapabilityProbe:
    """Run bounded secret-safe capability proofs and own their child processes."""

    def __init__(
        self,
        config: RuntimeLifecycleConfig,
        capability_cache: YiCapabilityCache,
        *,
        duration_seconds: float = 8.0,
        timeout_margin_seconds: float = 15.0,
        attempts: int = 2,
        session_settle_seconds: float = 3.0,
        retry_delay_seconds: float = 2.0,
        terminate_grace_seconds: float = 3.0,
    ) -> None:
        config.validate()
        if duration_seconds <= 0 or timeout_margin_seconds <= 0:
            raise ValueError("probe timing values must be greater than zero")
        if attempts < 1 or attempts > 3:
            raise ValueError("probe attempts must be between 1 and 3")
        if session_settle_seconds < 0 or retry_delay_seconds < 0:
            raise ValueError("probe handoff delays must not be negative")
        if terminate_grace_seconds <= 0:
            raise ValueError("probe terminate grace must be greater than zero")
        self.config = config
        self.capability_cache = capability_cache
        self.duration_seconds = float(duration_seconds)
        self.timeout_margin_seconds = float(timeout_margin_seconds)
        self.attempts = int(attempts)
        self.session_settle_seconds = float(session_settle_seconds)
        self.retry_delay_seconds = float(retry_delay_seconds)
        self.terminate_grace_seconds = float(terminate_grace_seconds)
        self._active_lock = threading.RLock()
        self._active: dict[int, subprocess.Popen[bytes]] = {}
        self._shutdown = threading.Event()

    @property
    def attempt_timeout_seconds(self) -> float:
        return self.duration_seconds + self.timeout_margin_seconds

    def _relay_command(self, stable_id: str, output: Path) -> list[str]:
        cfg = self.config
        return [
            cfg.python,
            str(cfg.stable_relay),
            "--stable-id",
            stable_id,
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
            "--duration",
            f"{self.duration_seconds:g}",
            "--output",
            str(output),
        ]

    def _terminate_group(self, process: subprocess.Popen[bytes]) -> None:
        if process.poll() is not None:
            return
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        except (PermissionError, OSError):
            try:
                process.terminate()
            except ProcessLookupError:
                return
        try:
            process.wait(timeout=self.terminate_grace_seconds)
            return
        except subprocess.TimeoutExpired:
            pass
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            return
        except (PermissionError, OSError):
            try:
                process.kill()
            except ProcessLookupError:
                return
        try:
            process.wait(timeout=2.0)
        except subprocess.TimeoutExpired:
            pass

    def _register(self, process: subprocess.Popen[bytes]) -> None:
        with self._active_lock:
            if self._shutdown.is_set():
                self._terminate_group(process)
                raise CapabilityProbeError(
                    "probe_cancelled",
                    "The live capability probe was cancelled because the Add-on is shutting down.",
                )
            self._active[process.pid] = process

    def _unregister(self, process: subprocess.Popen[bytes]) -> None:
        with self._active_lock:
            self._active.pop(process.pid, None)

    def _sleep_interruptible(self, seconds: float) -> None:
        if seconds <= 0:
            return
        if self._shutdown.wait(seconds):
            raise CapabilityProbeError(
                "probe_cancelled",
                "The live capability probe was cancelled because the Add-on is shutting down.",
            )

    def _run_relay_attempt(
        self,
        key: str,
        media_path: Path,
        log_stream: BinaryIO,
        attempt: int,
    ) -> bool:
        """Run one relay attempt.

        Returns True when the relay exceeded the process deadline only after it
        had already produced media. The caller must still validate that media
        with ffprobe before treating the capability probe as successful.
        """
        marker = (
            f"\n=== reprobe attempt {attempt}/{self.attempts}; "
            f"timeout={self.attempt_timeout_seconds:g}s ===\n"
        ).encode("utf-8")
        log_stream.write(marker)
        log_stream.flush()
        try:
            process = subprocess.Popen(
                self._relay_command(key, media_path),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=log_stream,
                start_new_session=True,
            )
        except OSError as exc:
            raise CapabilityProbeError(
                "probe_spawn_failed",
                "The live camera capability probe could not be started.",
            ) from exc

        self._register(process)
        forced_shutdown_after_media = False
        try:
            try:
                returncode = process.wait(timeout=self.attempt_timeout_seconds)
            except subprocess.TimeoutExpired as exc:
                self._terminate_group(process)
                if media_path.is_file() and media_path.stat().st_size > 0:
                    forced_shutdown_after_media = True
                    log_stream.write(
                        b"reprobe_attempt_timeout_after_media=true; action=ffprobe_validate\n"
                    )
                    log_stream.flush()
                    return forced_shutdown_after_media
                raise CapabilityProbeError(
                    "probe_timeout",
                    "The live camera capability probe timed out before producing media.",
                ) from exc

            if returncode != 0 or not media_path.is_file() or media_path.stat().st_size <= 0:
                raise CapabilityProbeError(
                    "probe_runtime_failed",
                    "The camera did not produce valid media during the capability probe.",
                )
            return forced_shutdown_after_media
        finally:
            if process.poll() is None:
                self._terminate_group(process)
            self._unregister(process)

    def probe(self, stable_id: str, *, session_handoff: bool = False) -> CapabilityProbeResult:
        if self._shutdown.is_set():
            raise CapabilityProbeError(
                "probe_cancelled",
                "The live capability probe is unavailable because the Add-on is shutting down.",
            )
        key = _stable_id(stable_id)
        probe_dir = self.config.state_dir / "probes"
        probe_dir.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(probe_dir, 0o700)
        except OSError:
            pass
        last_log = probe_dir / f"{key}-last.log"

        if session_handoff:
            self._sleep_interruptible(self.session_settle_seconds)

        with tempfile.TemporaryDirectory(prefix=f"yi-probe-{key[:8]}-", dir=probe_dir) as temporary:
            work = Path(temporary)
            media_path = work / "probe.ts"
            probe_json = work / "ffprobe.json"
            last_error: CapabilityProbeError | None = None
            attempts_used = 0
            forced_shutdown_after_media = False

            with last_log.open("wb", buffering=0) as log_stream:
                try:
                    os.chmod(last_log, 0o600)
                except OSError:
                    pass
                for attempt in range(1, self.attempts + 1):
                    attempts_used = attempt
                    media_path.unlink(missing_ok=True)
                    try:
                        forced_shutdown_after_media = self._run_relay_attempt(
                            key, media_path, log_stream, attempt
                        )
                        last_error = None
                        break
                    except CapabilityProbeError as exc:
                        last_error = exc
                        log_stream.write(
                            f"reprobe_attempt_result={exc.category}\n".encode("utf-8")
                        )
                        log_stream.flush()
                        retryable = exc.category in {"probe_runtime_failed", "probe_timeout"}
                        if attempt >= self.attempts or not retryable:
                            raise
                        self._sleep_interruptible(self.retry_delay_seconds)

            if last_error is not None:
                raise last_error

            try:
                with probe_json.open("wb") as output:
                    metadata = subprocess.run(
                        [
                            self.config.ffprobe,
                            "-v",
                            "error",
                            "-show_entries",
                            "stream=codec_name,codec_type,width,height,sample_rate,channels",
                            "-of",
                            "json",
                            str(media_path),
                        ],
                        stdin=subprocess.DEVNULL,
                        stdout=output,
                        stderr=subprocess.DEVNULL,
                        timeout=10.0,
                        check=False,
                    )
            except (subprocess.TimeoutExpired, OSError) as exc:
                raise CapabilityProbeError(
                    "media_validation_failed",
                    "The live probe media could not be validated.",
                ) from exc

            if metadata.returncode != 0:
                raise CapabilityProbeError(
                    "media_validation_failed",
                    "The live probe media could not be validated.",
                )

            video, audio = _validated_media(probe_json)
            record = self.capability_cache.record_success(
                stable_id=key,
                profile=PROVEN_PROFILE,
                video_codec="h264",
                video_width=int(video["width"]),
                video_height=int(video["height"]),
                audio_codec="aac",
                audio_sample_rate=int(audio["sample_rate"]),
                audio_channels=int(audio["channels"]),
                source="addon_api_reprobe",
            )
            return CapabilityProbeResult(
                stable_id=key,
                profile=PROVEN_PROFILE,
                capability=record,
                duration_seconds=self.duration_seconds,
                attempts_used=attempts_used,
                forced_shutdown_after_media=forced_shutdown_after_media,
            )

    def shutdown(self) -> None:
        self._shutdown.set()
        with self._active_lock:
            processes = list(self._active.values())
        for process in processes:
            self._terminate_group(process)
