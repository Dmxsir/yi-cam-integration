"""YI Home integration."""

from __future__ import annotations

from dataclasses import dataclass
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import YiHomeApi, YiHomeApiError
from .const import CONF_ADDON_SLUG, CONF_API_TOKEN
from .coordinator import YiHomeCoordinator
from .rtsp_export import YiHomeRtspExport, async_resolve_rtsp_export

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.BINARY_SENSOR, Platform.CAMERA, Platform.SENSOR, Platform.SWITCH]


@dataclass
class YiHomeRuntimeData:
    """Runtime-only state for one YI Home config entry."""

    api: YiHomeApi
    coordinator: YiHomeCoordinator
    rtsp_export: YiHomeRtspExport


type YiHomeConfigEntry = ConfigEntry[YiHomeRuntimeData]


async def async_setup_entry(hass: HomeAssistant, entry: YiHomeConfigEntry) -> bool:
    """Set up YI Home from a config entry."""
    api_host = str(entry.data[CONF_HOST])
    api = YiHomeApi(
        async_get_clientsession(hass),
        api_host,
        int(entry.data[CONF_PORT]),
        str(entry.data[CONF_API_TOKEN]),
    )
    try:
        await api.health()
    except YiHomeApiError as exc:
        raise ConfigEntryNotReady("YI Home App is not ready") from exc

    rtsp_export = await async_resolve_rtsp_export(
        hass,
        preferred_addon_slug=entry.data.get(CONF_ADDON_SLUG),
        api_host=api_host,
    )
    if (
        rtsp_export.addon_slug is not None
        and entry.data.get(CONF_ADDON_SLUG) != rtsp_export.addon_slug
    ):
        # Migrate existing development entries created before the Supervisor
        # slug was persisted by Config Flow. This value is secret-safe.
        data = dict(entry.data)
        data[CONF_ADDON_SLUG] = rtsp_export.addon_slug
        hass.config_entries.async_update_entry(entry, data=data)

    _LOGGER.debug(
        "YI external RTSP export resolved=%s host_available=%s port_mapped=%s",
        rtsp_export.addon_slug is not None,
        rtsp_export.host is not None,
        rtsp_export.port is not None,
    )

    coordinator = YiHomeCoordinator(hass, api, entry.entry_id)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = YiHomeRuntimeData(
        api=api,
        coordinator=coordinator,
        rtsp_export=rtsp_export,
    )
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: YiHomeConfigEntry) -> bool:
    """Unload YI Home."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
