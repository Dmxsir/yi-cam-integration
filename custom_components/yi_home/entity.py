"""Shared YI Home camera entity helpers."""

from __future__ import annotations

from typing import Any

from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import YiHomeCoordinator


class YiHomeCameraEntity(CoordinatorEntity[YiHomeCoordinator]):
    """Base entity backed by one secret-safe YI camera record."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: YiHomeCoordinator, stable_id: str) -> None:
        super().__init__(coordinator)
        self._stable_id = stable_id

    @property
    def camera_data(self) -> dict[str, Any] | None:
        """Latest camera payload."""
        return self.coordinator.camera(self._stable_id)

    @property
    def available(self) -> bool:
        """Entity is available while the App and camera record are available."""
        return super().available and self.camera_data is not None

    @property
    def device_info(self) -> DeviceInfo:
        """Attach all entities for a camera to one Home Assistant device."""
        camera = self.camera_data or {}
        name = str(camera.get("name") or "YI Camera")
        return DeviceInfo(
            identifiers={(DOMAIN, self._stable_id)},
            name=name,
            manufacturer="YI Technology",
        )
