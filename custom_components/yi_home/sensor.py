"""Sensors for YI Home cameras."""

from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import YiHomeCoordinator
from .entity import YiHomeCameraEntity


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
        return {
            "desired_running": camera.get("persisted_desired_running"),
            "process_alive": runtime.get("process_alive"),
            "restart_count": runtime.get("restart_count"),
            "last_reason": runtime.get("last_reason"),
            "publisher_attached": runtime.get("media_publisher_attached"),
        }
