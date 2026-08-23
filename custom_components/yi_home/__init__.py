"""YI Home integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import YiHomeApi, YiHomeApiError
from .const import CONF_API_TOKEN


type YiHomeConfigEntry = ConfigEntry[YiHomeApi]


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
    except YiHomeApiError:
        return False
    entry.runtime_data = api
    return True


async def async_unload_entry(hass: HomeAssistant, entry: YiHomeConfigEntry) -> bool:
    """Unload YI Home."""
    return True
