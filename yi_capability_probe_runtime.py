#!/usr/bin/env python3
"""Bounded live capability probe used by the YI Home Add-on backend.

The probe resolves a camera only by secret-safe stable_id, runs the proven
native relay for a bounded duration, validates observed H264/AAC media with
ffprobe, and only then atomically updates the capability cache.

A failed probe never overwrites a previously proven capability record.
"""

from __future__ import annotations

import json
import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

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

    def safe_dict(self) -> dict[str, Any]:
        return {
            "stable_id": self.stable_id,
            "profile": self.profile,
            "duration_seconds": self.duration_seconds,
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
    """Run one bounded secret-safe capability proof for a stable_id."""

    def __init__(
        self,
        config: RuntimeLifecycleConfig,
        capability_cache: YiCapabilityCache,
        *,
        duration_seconds: float = 8.0,
        timeout_margin_seconds: float = 45.0,
    ) -> None:
        config.validate()
        if duration_seconds <= 0 or timeout_margin_seconds <= 0:
            raise ValueError("probe timing values must be greater than zero")
        self.config = config
        self.capability_cache = capability_cache
        self.duration_seconds = float(duration_seconds)
        self.timeout_margin_seconds = float(timeout_margin_seconds)

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

    def probe(self, stable_id: str) -> CapabilityProbeResult:
        key = _stable_id(stable_id)
        probe_dir = self.config.state_dir / "probes"
        probe_dir.mkdir(parents=True, exist_ok=True)

        with tempfile.TemporaryDirectory(prefix=f"yi-probe-{key[:8]}-", dir=probe_dir) as temporary:
            work = Path(temporary)
            media_path = work / "probe.ts"
            probe_json = work / "ffprobe.json"
            timeout = self.duration_seconds + self.timeout_margin_seconds

            try:
                completed = subprocess.run(
                    self._relay_command(key, media_path),
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=timeout,
                    check=False,
                )
            except subprocess.TimeoutExpired as exc:
                raise CapabilityProbeError(
                    "probe_timeout",
                    "The live camera capability probe timed out.",
                ) from exc
            except OSError as exc:
                raise CapabilityProbeError(
                    "probe_spawn_failed",
                    "The live camera capability probe could not be started.",
                ) from exc

            if completed.returncode != 0 or not media_path.is_file() or media_path.stat().st_size <= 0:
                raise CapabilityProbeError(
                    "probe_runtime_failed",
                    "The camera did not produce valid media during the capability probe.",
                )

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
                        timeout=15.0,
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
            )
