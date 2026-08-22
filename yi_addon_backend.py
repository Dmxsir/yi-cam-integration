#!/usr/bin/env python3
"""Reusable state core for the future YI Home Add-on service.

The backend owns secret-safe account discovery snapshots, proven capability
state and (when configured) per-camera runtime lifecycle state. HTTP remains a
separate layer in yi_addon_service.py.

No secret-bearing CameraMaterial is retained here. Runtime material is resolved
inside the selected camera process only when that runtime is started.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import yi_cloud_probe as cloud
from yi_camera_manager import CameraDevice, YiCameraManager
from yi_capability_cache import CapabilityRecord, YiCapabilityCache
from yi_runtime_lifecycle import YiRuntimeLifecycleManager


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

    def safe_dict(self, runtime: dict[str, Any] | None = None) -> dict[str, Any]:
        item = self.device.safe_dict()
        item["capability"] = self.capability.safe_dict() if self.capability is not None else None
        item["capability_state"] = "proven" if self.capability is not None else "unprobed"
        if runtime is not None:
            item["runtime_state"] = runtime.get("runtime_state")
            item["runtime"] = runtime
        return item

    def status_dict(self, runtime: dict[str, Any] | None = None) -> dict[str, Any]:
        capability = self.capability
        runtime_state = runtime.get("runtime_state") if runtime is not None else "not_managed"
        return {
            "stable_id": self.device.stable_id,
            "stream_id": self.device.stream_id,
            "name": self.device.name,
            "cloud_online_reported": self.device.cloud_online_reported,
            "transport": self.device.transport,
            "runtime_state": runtime_state,
            "runtime": runtime,
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

    def __init__(
        self,
        *,
        timeout: float = 10.0,
        capability_cache: YiCapabilityCache | None = None,
        lifecycle: YiRuntimeLifecycleManager | None = None,
    ) -> None:
        self.timeout = timeout
        self.capability_cache = capability_cache or YiCapabilityCache()
        self.lifecycle = lifecycle
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

    def _runtime_for(self, stable_id: str) -> dict[str, Any] | None:
        if self.lifecycle is None:
            return None
        try:
            return self.lifecycle.status(stable_id)
        except (RuntimeError, ValueError, OSError):
            return {
                "stable_id": stable_id,
                "runtime_state": "error",
                "desired_running": False,
                "process_alive": False,
                "pid": None,
                "last_error": "Runtime status is unavailable.",
                "secrets_exposed": False,
            }

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
            "runtime_lifecycle_ready": self.lifecycle is not None,
            "secrets_exposed": False,
        }

    def health(self) -> dict[str, Any]:
        with self._lock:
            camera_count = len(self._cameras)
            last_discovery_at = self._last_discovery_at
            generation = self._discovery_generation
            last_error = dict(self._last_error) if self._last_error is not None else None
        return {
            "ok": True,
            "service": self.SERVICE_NAME,
            "api_version": self.API_VERSION,
            "camera_count": camera_count,
            "last_discovery_at": last_discovery_at,
            "discovery_generation": generation,
            "last_error": last_error,
            "runtime_lifecycle_ready": self.lifecycle is not None,
            "managed_runtime_count": self.lifecycle.managed_count() if self.lifecycle is not None else 0,
            "secrets_exposed": False,
        }

    def cameras(self) -> dict[str, Any]:
        with self._lock:
            states = list(self._cameras.values())
            last_discovery_at = self._last_discovery_at
        cameras = [state.safe_dict(self._runtime_for(state.device.stable_id)) for state in states]
        return {
            "ok": True,
            "camera_count": len(cameras),
            "cameras": cameras,
            "last_discovery_at": last_discovery_at,
            "secrets_exposed": False,
        }

    def camera(self, stable_id: str) -> dict[str, Any] | None:
        with self._lock:
            state = self._cameras.get(stable_id)
        if state is None:
            return None
        return {
            "ok": True,
            "camera": state.safe_dict(self._runtime_for(stable_id)),
            "secrets_exposed": False,
        }

    def camera_status(self, stable_id: str) -> dict[str, Any] | None:
        with self._lock:
            state = self._cameras.get(stable_id)
        if state is None:
            return None
        return {"ok": True, "status": state.status_dict(self._runtime_for(stable_id))}

    def _camera_exists(self, stable_id: str) -> bool:
        with self._lock:
            return stable_id in self._cameras

    def _runtime_operation(self, stable_id: str, operation: str) -> tuple[int, dict[str, Any]]:
        if not self._camera_exists(stable_id):
            return 404, {
                "ok": False,
                "error": {"code": "camera_not_found", "message": "Unknown camera stable_id."},
                "secrets_exposed": False,
            }
        if self.lifecycle is None:
            return 409, {
                "ok": False,
                "error": {
                    "code": "runtime_lifecycle_not_ready",
                    "message": "The camera runtime lifecycle manager is not enabled.",
                },
                "secrets_exposed": False,
            }
        try:
            if operation == "start":
                runtime = self.lifecycle.start(stable_id)
            elif operation == "stop":
                runtime = self.lifecycle.stop(stable_id)
            elif operation == "restart":
                runtime = self.lifecycle.restart(stable_id)
            else:
                raise ValueError("unsupported runtime operation")
        except (RuntimeError, ValueError, OSError):
            return 500, {
                "ok": False,
                "error": {
                    "code": "runtime_operation_failed",
                    "message": f"Camera {operation} operation failed.",
                },
                "secrets_exposed": False,
            }
        return 200, {
            "ok": True,
            "operation": operation,
            "runtime": runtime,
            "secrets_exposed": False,
        }

    def start_camera(self, stable_id: str) -> tuple[int, dict[str, Any]]:
        return self._runtime_operation(stable_id, "start")

    def stop_camera(self, stable_id: str) -> tuple[int, dict[str, Any]]:
        return self._runtime_operation(stable_id, "stop")

    def restart_camera(self, stable_id: str) -> tuple[int, dict[str, Any]]:
        return self._runtime_operation(stable_id, "restart")

    def reprobe_not_ready(self, stable_id: str) -> tuple[int, dict[str, Any]]:
        if not self._camera_exists(stable_id):
            return 404, {
                "ok": False,
                "error": {"code": "camera_not_found", "message": "Unknown camera stable_id."},
                "secrets_exposed": False,
            }
        return 409, {
            "ok": False,
            "error": {
                "code": "reprobe_not_ready",
                "message": "Live capability reprobe is scheduled for Phase 6C.4.",
            },
            "secrets_exposed": False,
        }

    def shutdown(self) -> None:
        if self.lifecycle is not None:
            self.lifecycle.shutdown_all()
