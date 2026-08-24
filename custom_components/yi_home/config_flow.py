"""Config flow for YI Home."""

from __future__ import annotations

import logging
from typing import Any, override

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_PORT
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.service_info.hassio import HassioServiceInfo

from .api import (
    YiHomeAccountError,
    YiHomeApi,
    YiHomeApiError,
    YiHomeCannotConnect,
    YiHomeInvalidAuth,
)
from .const import (
    CLIENT_ANDROID_VERSION,
    CLIENT_DEVICE_BRAND,
    CLIENT_DEVICE_MODEL,
    CLIENT_LANGUAGE,
    CONF_ACCOUNT,
    CONF_ADDON_SLUG,
    CONF_API_TOKEN,
    CONF_COUNTRY,
    CONF_REGION,
    CONF_RTSP_PORT,
    DEFAULT_COUNTRY,
    DEFAULT_REGION,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)
REGIONS = {"eu": "Europe", "us": "United States", "sea": "Asia / Pacific", "cn": "China"}


class YiHomeConfigFlow(ConfigFlow, domain=DOMAIN):
    """Configure YI Home from Supervisor App discovery."""

    VERSION = 1

    def __init__(self) -> None:
        self._discovery: dict[str, Any] | None = None
        self._app_name = "YI Home"

    def _api(self) -> YiHomeApi:
        assert self._discovery is not None
        return YiHomeApi(
            async_get_clientsession(self.hass),
            str(self._discovery[CONF_HOST]),
            int(self._discovery[CONF_PORT]),
            str(self._discovery[CONF_API_TOKEN]),
        )

    async def _create_entry(
        self, *, region: str | None = None, country: str | None = None
    ) -> ConfigFlowResult:
        assert self._discovery is not None
        data: dict[str, Any] = {
            CONF_HOST: self._discovery[CONF_HOST],
            CONF_PORT: int(self._discovery[CONF_PORT]),
            CONF_API_TOKEN: self._discovery[CONF_API_TOKEN],
        }
        if CONF_ADDON_SLUG in self._discovery:
            data[CONF_ADDON_SLUG] = str(self._discovery[CONF_ADDON_SLUG])
        if CONF_RTSP_PORT in self._discovery:
            data[CONF_RTSP_PORT] = int(self._discovery[CONF_RTSP_PORT])
        if region is not None:
            data[CONF_REGION] = region
        if country is not None:
            data[CONF_COUNTRY] = country
        # YI account/password are intentionally not stored in the HA config entry.
        return self.async_create_entry(title=self._app_name, data=data)

    @override
    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """YI Home is configured through its Home Assistant App discovery."""
        return self.async_abort(reason="app_required")

    @override
    async def async_step_hassio(
        self, discovery_info: HassioServiceInfo
    ) -> ConfigFlowResult:
        """Handle discovery published by the YI Home App."""
        await self._async_handle_discovery_without_unique_id()

        config = dict(discovery_info.config)
        # Older development builds published the App API credential as `token`.
        # Normalize it in-memory without ever logging or persisting both copies.
        if not config.get(CONF_API_TOKEN) and config.get("token"):
            config[CONF_API_TOKEN] = config.pop("token")

        required = (CONF_HOST, CONF_PORT, CONF_API_TOKEN)
        if any(not config.get(key) for key in required) or config.get("api_version") != "v1":
            _LOGGER.warning("YI Home Hass.io discovery payload is incomplete or has an unsupported API version")
            return self.async_abort(reason="invalid_discovery")

        # Preserve the actual Supervisor slug (`local_yi_home` during local
        # development, later the public App slug) so external RTSP port mapping
        # can be resolved without guessing.
        if discovery_info.slug:
            config[CONF_ADDON_SLUG] = discovery_info.slug

        self._discovery = config
        self._app_name = discovery_info.name or "YI Home"
        safe_host = str(config[CONF_HOST])
        safe_port = int(config[CONF_PORT])
        _LOGGER.warning(
            "Received YI Home Hass.io discovery for host=%s port=%s; credentials_exposed=false",
            safe_host,
            safe_port,
        )

        try:
            health = await self._api().health()
            account = await self._api().account_status()
        except (YiHomeCannotConnect, YiHomeInvalidAuth, YiHomeApiError) as exc:
            _LOGGER.warning(
                "YI Home Hass.io discovery health check failed for host=%s port=%s error=%s",
                safe_host,
                safe_port,
                type(exc).__name__,
            )
            return self.async_abort(reason="cannot_connect")

        if health.get("secrets_exposed") is not False or account.get("secrets_exposed") is not False:
            _LOGGER.error("YI Home backend failed the secret-safety contract during Hass.io discovery")
            return self.async_abort(reason="unsafe_backend")

        _LOGGER.warning(
            "YI Home Hass.io discovery validated for host=%s port=%s account_configured=%s",
            safe_host,
            safe_port,
            account.get("configured") is True,
        )
        if account.get("configured") is True:
            return await self._create_entry(
                region=account.get("region"),
                country=account.get("country"),
            )
        return await self.async_step_hassio_account()

    async def async_step_hassio_account(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Collect YI credentials and hand them directly to the App."""
        errors: dict[str, str] = {}
        if user_input is not None:
            payload = {
                "region": str(user_input[CONF_REGION]),
                "country": str(user_input[CONF_COUNTRY]).upper(),
                "account": str(user_input[CONF_ACCOUNT]),
                "password": str(user_input[CONF_PASSWORD]),
                # Internal API compatibility profile; never user-facing.
                "device_brand": CLIENT_DEVICE_BRAND,
                "device_model": CLIENT_DEVICE_MODEL,
                "android_version": CLIENT_ANDROID_VERSION,
                "language": CLIENT_LANGUAGE,
            }
            try:
                result = await self._api().configure_account(payload)
            except YiHomeInvalidAuth:
                return self.async_abort(reason="app_auth_failed")
            except YiHomeCannotConnect:
                errors["base"] = "cannot_connect"
            except YiHomeAccountError as exc:
                if exc.code == "invalid_credentials":
                    errors["base"] = "invalid_auth"
                elif exc.code == "rate_limit":
                    errors["base"] = "rate_limited"
                else:
                    errors["base"] = "account_setup_failed"
            except YiHomeApiError:
                errors["base"] = "account_setup_failed"
            else:
                if result.get("configured") is True and result.get("secrets_exposed") is False:
                    return await self._create_entry(
                        region=str(result.get("region") or payload["region"]),
                        country=str(result.get("country") or payload["country"]),
                    )
                errors["base"] = "account_setup_failed"

        return self.async_show_form(
            step_id="hassio_account",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_ACCOUNT): selector.TextSelector(),
                    vol.Required(CONF_PASSWORD): selector.TextSelector(
                        selector.TextSelectorConfig(
                            type=selector.TextSelectorType.PASSWORD
                        )
                    ),
                    vol.Required(CONF_COUNTRY, default=DEFAULT_COUNTRY): selector.TextSelector(),
                    vol.Required(CONF_REGION, default=DEFAULT_REGION): vol.In(REGIONS),
                }
            ),
            errors=errors,
        )
