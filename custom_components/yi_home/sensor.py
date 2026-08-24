"""Sensors for YI Home cameras."""

from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import YiHomeCoordinator
from .entity import YiHomeCameraEntity
from .rtsp_export import YiHomeRtspExport


_FAILURE_STAGE_BY_EXIT_CODE = {
    1: "relay_failure_legacy",
    74: "startup_stall",
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
    93: "relay_native_stream_header",
    94: "relay_native_media_record",
    95: "relay_audio_unit_validation",
    96: "relay_audio_format_changed",
    97: "relay_video_unit_validation",
    98: "relay_worker_pipe_setup",
    100: "media_stall_native_header_wait",
    101: "media_stall_native_payload_wait",
    102: "media_stall_audio_pipe_write",
    103: "media_stall_video_pipe_write",
    104: "media_stall_mux_starting",
    105: "media_stall_relay_processing",
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
    """Set up camera sensors, including cameras discovered later."""
    coordinator: YiHomeCoordinator = entry.runtime_data.coordinator
    rtsp_export: YiHomeRtspExport = entry.runtime_data.rtsp_export
    known_ids: set[str] = set()

    @callback
    def async_add_new_entities() -> None:
        new_ids = coordinator.camera_ids() - known_ids
        if not new_ids:
            return
        known_ids.update(new_ids)
        entities: list[SensorEntity] = []
        for stable_id in sorted(new_ids):
            entities.append(YiHomeRuntimeSensor(coordinator, stable_id))
            entities.append(
                YiHomeFrigateRtspSensor(coordinator, stable_id, rtsp_export)
            )
        async_add_entities(entities)

    async_add_new_entities()
    entry.async_on_unload(coordinator.async_add_listener(async_add_new_entities))


class YiHomeRuntimeSensor(YiHomeCameraEntity, SensorEntity):
    """Current managed runtime state for one camera."""

    _attr_translation_key = "runtime_status"

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


class YiHomeFrigateRtspSensor(YiHomeCameraEntity, SensorEntity):
    """Ready-to-copy LAN RTSP endpoint for optional Frigate consumption."""

    _attr_translation_key = "frigate_rtsp"
    _attr_icon = "mdi:video-network-outline"

    def __init__(
        self,
        coordinator: YiHomeCoordinator,
        stable_id: str,
        rtsp_export: YiHomeRtspExport,
    ) -> None:
        super().__init__(coordinator, stable_id)
        self._attr_unique_id = f"{stable_id}_frigate_rtsp"
        self._rtsp_export = rtsp_export

    @property
    def available(self) -> bool:
        """Only expose a usable value while the external App port is mapped."""
        return super().available and self._rtsp_export.available

    @property
    def native_value(self) -> str | None:
        """Return the complete secret-safe external RTSP URL."""
        return self._rtsp_export.url_for(self._stable_id)

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        """Expose only non-secret export metadata."""
        return {
            "external_rtsp_port": self._rtsp_export.port,
            "external_host": self._rtsp_export.host,
            "app_slug": self._rtsp_export.addon_slug,
            "requires_stream_enabled": True,
        }
