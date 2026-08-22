#!/usr/bin/env python3
"""Reusable state core for the future YI Home Add-on service.

The backend owns secret-safe account discovery snapshots and proven capability
state.  HTTP is intentionally layered separately in yi_addon_service.py so the
same backend can later be driven by Home Assistant Add-on lifecycle code and
tests without coupling protocol/runtime state to a web framework.

No secret-bearing CameraMaterial is retained here. Runtime material is resolved
only when a camera session is actually started by the later lifecycle manager.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import yi_cloud_probe as cloud
from yi_camera_manager import CameraDevice, YiCameraManager
from yi_capability_cache import CapabilityRecord, YiCapabilityCache


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _safe_error(exc: Exception) -> dict[str, str]:
    if isinstance(exc, cloud.YiCloudError):
        return {"category": exc.category, "message": exc.safe_message}
    if isinstance(exc, (TimeoutError, OSError)):
        return {"category": "transport_error", "message": "A backend transport operation failed."}
    return {"category": "backend_error", "message": "A backend operation failed."}


@dataclass(frozen=True)
class CameraState:
    device: CameraDevice
    capability: CapabilityRecord | None

    def safe_dict(self) -> dict[str, Any]:
        item = self.device.safe_dict()
        item["capability"] = self.capability.safe_dict() if self.capability is not None else None
        item["capability_state"] = "proven" if self.capability is not None else "unprobed"
        return item

    def status_dict(self) -> dict[str, Any]:
        capability = self.capability
        return {
            "stable_id": self.device.stable_id,
            "stream_id": self.device.stream_id,
            "name": self.device.name,
            "cloud_online_reported": self.device.cloud_online_reported,
            "transport": self.device.transport,
            "runtime_state": "not_managed_yet",
            "capability_state": "proven" if capability is not None else "unprobed",
            "profile": capability.profile if capability is not None else None,
            "media": (
                {
                    "video": {
                        "codec": capability.video_codec,
                        "width": capability.video_width,
                        "height": capability.video_height,
                    },
                    "audio": {
                        "codec": capability.audio_codec,
                        "sample_rate": capability.audio_sample_rate,
                        "channels": capability.audio_channels,
                    },
                }
                if capability is not None
                else None
            ),
            "secrets_exposed": False,
        }


class YiAddonBackend:
    """Thread-safe secret-safe state core for the Add-on API."""

    API_VERSION = "v1"
    SERVICE_NAME = "yi-home-addon"

    def __init__(self, *, timeout: float = 10.0, capability_cache: YiCapabilityCache | None = None) -> None:
        self.timeout = timeout
        self.capability_cache = capability_cache or YiCapabilityCache()
        self._lock = threading.RLock()
        self._cameras: dict[str, CameraState] = {}
        self._last_discovery_at: str | None = None
        self._last_error: dict[str, str] | None = None
        self._discovery_generation = 0

    def _capability_for(self, stable_id: str) -> CapabilityRecord | None:
        try:
            return self.capability_cache.get_success(stable_id)
        except (RuntimeError, ValueError, OSError):
            # A broken cache must never make account discovery unusable.
            return None

    def discover(self, *, fetch_tnp: bool = True) -> dict[str, Any]:
        manager = YiCameraManager(timeout=self.timeout)
        try:
            devices = manager.discover(fetch_tnp=fetch_tnp)
            snapshot = {
                device.stable_id: CameraState(device=device, capability=self._capability_for(device.stable_id))
                for device in devices
            }
        except Exception as exc:
            safe = _safe_error(exc)
            with self._lock:
                self._last_error = safe
            raise
        finally:
            manager.close()

        now = _utc_now()
        with self._lock:
            self._cameras = snapshot
            self._last_discovery_at = now
            self._last_error = None
            self._discovery_generation += 1
            generation = self._discovery_generation

        return {
            "ok": True,
            "camera_count": len(snapshot),
            "probe_candidates": sum(1 for camera in snapshot.values() if camera.device.probe_candidate),
            "proven_capabilities": sum(1 for camera in snapshot.values() if camera.capability is not None),
            "discovered_at": now,
            "generation": generation,
            "secrets_exposed": False,
        }

    def health(self) -> dict[str, Any]:
        with self._lock:
            return {
                "ok": True,
                "service": self.SERVICE_NAME,
                "api_version": self.API_VERSION,
                "camera_count": len(self._cameras),
                "last_discovery_at": self._last_discovery_at,
                "discovery_generation": self._discovery_generation,
                "last_error": dict(self._last_error) if self._last_error is not None else None,
                "runtime_lifecycle_ready": False,
                "secrets_exposed": False,
            }

    def cameras(self) -> dict[str, Any]:
        with self._lock:
            cameras = [state.safe_dict() for state in self._cameras.values()]
            return {
                "ok": True,
                "camera_count": len(cameras),
                "cameras": cameras,
                "last_discovery_at": self._last_discovery_at,
                "secrets_exposed": False,
            }

    def camera(self, stable_id: str) -> dict[str, Any] | None:
        with self._lock:
            state = self._cameras.get(stable_id)
            if state is None:
                return None
            return {"ok": True, "camera": state.safe_dict(), "secrets_exposed": False}

    def camera_status(self, stable_id: str) -> dict[str, Any] | None:
        with self._lock:
            state = self._cameras.get(stable_id)
            return None if state is None else {"ok": True, "status": state.status_dict()}

    def lifecycle_not_ready(self, stable_id: str, operation: str) -> tuple[int, dict[str, Any]]:
        with self._lock:
            if stable_id not in self._cameras:
                return 404, {
                    "ok": False,
                    "error": {"code": "camera_not_found", "message": "Unknown camera stable_id."},
                    "secrets_exposed": False,
                }
        return 409, {
            "ok": False,
            "error": {
                "code": "runtime_lifecycle_not_ready",
                "message": f"Camera {operation} is not enabled until the Phase 6C lifecycle manager is attached.",
            },
            "secrets_exposed": False,
        }
