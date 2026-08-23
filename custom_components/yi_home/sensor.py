"""Sensors for YI Home cameras."""

from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import YiHomeCoordinator
from .entity import YiHomeCameraEntity


_FAILURE_STAGE_BY_EXIT_CODE = {
    1: "relay_failure_legacy",
    75: "media_stall_process_state_unavailable",
    76: "media_stall_qemu_alive_ffmpeg_alive",
    77: "media_stall_qemu_alive_ffmpeg_missing",
    78: "media_stall_qemu_missing_ffmpeg_alive",
    79: "media_stall_qemu_missing_ffmpeg_missing",
    81: "native_worker_exit",
    82: "mpegts_mux_exit",
    83: "no_video_frames",
    84: "no_audio_frames",
    85: "relay_exception",
    86: "relay_failure_unclassified",
    87: "relay_eof",
    88: "relay_runtime_error",
    89: "relay_timeout",
    90: "relay_broken_pipe",
    91: "relay_os_error",
    92: "relay_value_error",
}


def _failure_stage(exit_code: object) -> str | None:
    if isinstance(exit_code, bool) or not isinstance(exit_code, int):
        return None
    return _FAILURE_STAGE_BY_EXIT_CODE.get(exit_code)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up camera runtime status sensors."""
    coordinator: YiHomeCoordinator = entry.runtime_data.coordinator
    cameras = coordinator.data.get("cameras", []) if coordinator.data else []
    async_add_entities(
        YiHomeRuntimeSensor(coordinator, str(camera["stable_id"]))
        for camera in cameras
        if isinstance(camera, dict) and isinstance(camera.get("stable_id"), str)
    )


class YiHomeRuntimeSensor(YiHomeCameraEntity, SensorEntity):
    """Current managed runtime state for one camera."""

    _attr_name = "Runtime status"

    def __init__(self, coordinator: YiHomeCoordinator, stable_id: str) -> None:
        super().__init__(coordinator, stable_id)
        self._attr_unique_id = f"{stable_id}_runtime_status"

    @property
    def native_value(self) -> str | None:
        camera = self.camera_data
        if camera is None:
            return None
        value = camera.get("runtime_state")
        return str(value) if value is not None else None

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        camera = self.camera_data or {}
        runtime = camera.get("runtime")
        runtime = runtime if isinstance(runtime, dict) else {}
        last_exit_code = runtime.get("last_exit_code")
        return {
            "desired_running": camera.get("persisted_desired_running"),
            "process_alive": runtime.get("process_alive"),
            "restart_count": runtime.get("restart_count"),
            "last_reason": runtime.get("last_reason"),
            "last_exit_code": last_exit_code,
            "last_failure_stage": _failure_stage(last_exit_code),
            "publisher_attached": runtime.get("media_publisher_attached"),
            "published_bytes": runtime.get("published_bytes"),
            "publisher_error": runtime.get("publisher_error"),
        }
