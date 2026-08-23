"""Live-view camera entities for YI Home."""

from __future__ import annotations

import re

from homeassistant.components.camera import Camera, CameraEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import CONF_RTSP_PORT
from .coordinator import YiHomeCoordinator
from .entity import YiHomeCameraEntity

DEFAULT_RTSP_PORT = 8554
_SAFE_RTSP_PATH = re.compile(r"^/yi_[0-9a-f]{12}$")


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up App-backed YI live-view cameras."""
    coordinator: YiHomeCoordinator = entry.runtime_data.coordinator
    cameras = coordinator.data.get("cameras", []) if coordinator.data else []
    host = str(entry.data[CONF_HOST])
    rtsp_port = int(entry.data.get(CONF_RTSP_PORT, DEFAULT_RTSP_PORT))

    async_add_entities(
        YiHomeLiveCamera(coordinator, str(camera["stable_id"]), host, rtsp_port)
        for camera in cameras
        if isinstance(camera, dict) and isinstance(camera.get("stable_id"), str)
    )


class YiHomeLiveCamera(YiHomeCameraEntity, Camera):
    """Expose the App-owned go2rtc RTSP publication as a HA camera."""

    _attr_name = None
    _attr_supported_features = CameraEntityFeature.STREAM

    def __init__(
        self,
        coordinator: YiHomeCoordinator,
        stable_id: str,
        host: str,
        rtsp_port: int,
    ) -> None:
        super().__init__(coordinator, stable_id)
        self._attr_unique_id = f"{stable_id}_camera"
        self._rtsp_host = host
        self._rtsp_port = rtsp_port

    @property
    def use_stream_for_stills(self) -> bool:
        """Generate still images from the same App-owned stream."""
        return True

    @property
    def is_streaming(self) -> bool:
        """Return whether App publication currently has live media."""
        camera = self.camera_data
        if not isinstance(camera, dict):
            return False
        runtime = camera.get("runtime")
        publication = camera.get("publication")
        return bool(
            isinstance(runtime, dict)
            and runtime.get("process_alive") is True
            and isinstance(publication, dict)
            and publication.get("publisher_ready") is True
            and publication.get("producer_media_ready") is True
        )

    async def stream_source(self) -> str | None:
        """Return the internal App-owned RTSP source when publication is ready."""
        camera = self.camera_data
        if not isinstance(camera, dict):
            return None

        runtime = camera.get("runtime")
        publication = camera.get("publication")
        if not (
            isinstance(runtime, dict)
            and runtime.get("process_alive") is True
            and isinstance(publication, dict)
            and publication.get("configured") is True
            and publication.get("publisher_ready") is True
            and publication.get("producer_media_ready") is True
        ):
            return None

        path = publication.get("rtsp_path")
        if not isinstance(path, str) or _SAFE_RTSP_PATH.fullmatch(path) is None:
            return None

        port = publication.get("rtsp_port")
        if not isinstance(port, int) or not 1 <= port <= 65535:
            port = self._rtsp_port
        if not 1 <= port <= 65535:
            return None

        return f"rtsp://{self._rtsp_host}:{port}{path}"
