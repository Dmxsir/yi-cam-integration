"""Binary sensors for YI Home cameras."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import YiHomeCoordinator
from .entity import YiHomeCameraEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up authoritative camera availability sensors, including later additions."""
    coordinator: YiHomeCoordinator = entry.runtime_data.coordinator
    known_ids: set[str] = set()

    @callback
    def async_add_new_entities() -> None:
        new_ids = coordinator.camera_ids() - known_ids
        if not new_ids:
            return
        known_ids.update(new_ids)
        async_add_entities(
            YiHomeOnlineBinarySensor(coordinator, stable_id)
            for stable_id in sorted(new_ids)
        )

    async_add_new_entities()
    entry.async_on_unload(coordinator.async_add_listener(async_add_new_entities))


class YiHomeOnlineBinarySensor(YiHomeCameraEntity, BinarySensorEntity):
    """Authoritative PPPP_CheckDevOnline state for a YI camera."""

    _attr_translation_key = "online"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

    def __init__(self, coordinator: YiHomeCoordinator, stable_id: str) -> None:
        super().__init__(coordinator, stable_id)
        self._attr_unique_id = f"{stable_id}_online"

    @property
    def is_on(self) -> bool | None:
        camera = self.camera_data
        if camera is None:
            return None
        state = camera.get("availability_state")
        if state == "online":
            return True
        if state == "offline":
            return False
        return None

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        camera = self.camera_data or {}
        return {
            "source": camera.get("availability_source"),
            "last_online_at": camera.get("last_online_at"),
        }
