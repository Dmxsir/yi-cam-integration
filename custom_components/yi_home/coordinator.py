"""Data coordinator for YI Home camera inventory."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import YiHomeApi, YiHomeApiError


class YiHomeCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Refresh secret-safe camera state from the YI Home App."""

    def __init__(self, hass: HomeAssistant, api: YiHomeApi) -> None:
        self.api = api
        super().__init__(
            hass,
            logger=__import__("logging").getLogger(__name__),
            name="YI Home cameras",
            update_interval=timedelta(seconds=30),
        )

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            payload = await self.api.cameras()
        except YiHomeApiError as exc:
            raise UpdateFailed("Unable to refresh YI Home camera state") from exc
        if payload.get("secrets_exposed") is not False:
            raise UpdateFailed("YI Home App returned an unsafe camera payload")
        cameras = payload.get("cameras")
        if not isinstance(cameras, list):
            raise UpdateFailed("YI Home App returned an invalid camera inventory")
        return payload

    def camera(self, stable_id: str) -> dict[str, Any] | None:
        """Return one camera from the latest secret-safe snapshot."""
        if not self.data:
            return None
        for camera in self.data.get("cameras", []):
            if isinstance(camera, dict) and camera.get("stable_id") == stable_id:
                return camera
        return None
