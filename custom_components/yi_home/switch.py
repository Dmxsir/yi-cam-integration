"""Switches for YI Home camera runtimes."""

from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api import YiHomeApiError
from .coordinator import YiHomeCoordinator
from .entity import YiHomeCameraEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up runtime switches, including cameras discovered later."""
    coordinator: YiHomeCoordinator = entry.runtime_data.coordinator
    known_ids: set[str] = set()

    @callback
    def async_add_new_entities() -> None:
        new_ids = coordinator.camera_ids() - known_ids
        if not new_ids:
            return
        known_ids.update(new_ids)
        async_add_entities(
            YiHomeStreamSwitch(coordinator, stable_id)
            for stable_id in sorted(new_ids)
        )

    async_add_new_entities()
    entry.async_on_unload(coordinator.async_add_listener(async_add_new_entities))


class YiHomeStreamSwitch(YiHomeCameraEntity, SwitchEntity):
    """Persist and control desired-running state for one YI camera."""

    _attr_translation_key = "stream"

    def __init__(self, coordinator: YiHomeCoordinator, stable_id: str) -> None:
        super().__init__(coordinator, stable_id)
        self._attr_unique_id = f"{stable_id}_stream"

    @property
    def is_on(self) -> bool | None:
        camera = self.camera_data
        if camera is None:
            return None
        desired = camera.get("persisted_desired_running")
        if isinstance(desired, bool):
            return desired
        runtime = camera.get("runtime")
        if isinstance(runtime, dict) and isinstance(runtime.get("desired_running"), bool):
            return bool(runtime["desired_running"])
        return False

    async def async_turn_on(self, **kwargs: object) -> None:
        try:
            await self.coordinator.api.start_camera(self._stable_id)
        except YiHomeApiError as exc:
            raise HomeAssistantError("YI Home could not start this camera stream") from exc
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: object) -> None:
        try:
            await self.coordinator.api.stop_camera(self._stable_id)
        except YiHomeApiError as exc:
            raise HomeAssistantError("YI Home could not stop this camera stream") from exc
        await self.coordinator.async_request_refresh()
