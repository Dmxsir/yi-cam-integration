"""YI Home integration."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import YiHomeApi, YiHomeApiError
from .const import CONF_API_TOKEN
from .coordinator import YiHomeCoordinator

PLATFORMS = [Platform.BINARY_SENSOR, Platform.SENSOR, Platform.SWITCH]


@dataclass
class YiHomeRuntimeData:
    """Runtime-only state for one YI Home config entry."""

    api: YiHomeApi
    coordinator: YiHomeCoordinator


type YiHomeConfigEntry = ConfigEntry[YiHomeRuntimeData]


async def async_setup_entry(hass: HomeAssistant, entry: YiHomeConfigEntry) -> bool:
    """Set up YI Home from a config entry."""
    api = YiHomeApi(
        async_get_clientsession(hass),
        str(entry.data[CONF_HOST]),
        int(entry.data[CONF_PORT]),
        str(entry.data[CONF_API_TOKEN]),
    )
    try:
        await api.health()
    except YiHomeApiError as exc:
        raise ConfigEntryNotReady("YI Home App is not ready") from exc

    coordinator = YiHomeCoordinator(hass, api)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = YiHomeRuntimeData(api=api, coordinator=coordinator)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: YiHomeConfigEntry) -> bool:
    """Unload YI Home."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
