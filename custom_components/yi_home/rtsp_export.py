"""Resolve external RTSP export details for the YI Home App."""

from __future__ import annotations

from dataclasses import dataclass
from ipaddress import ip_interface, ip_address
import logging
import re
from typing import Any

from yarl import URL

from homeassistant.components.hassio import SupervisorError, get_supervisor_client
from homeassistant.core import HomeAssistant
from homeassistant.helpers.hassio import is_hassio
from homeassistant.helpers.network import NoURLAvailableError, get_url

from .const import RTSP_CONTAINER_PORT_KEY

_LOGGER = logging.getLogger(__name__)
_STABLE_ID_RE = re.compile(r"^[0-9a-f]{20}$")


@dataclass(frozen=True, slots=True)
class YiHomeRtspExport:
    """Secret-safe LAN export information for the App-owned RTSP service."""

    addon_slug: str | None
    host: str | None
    port: int | None

    @property
    def available(self) -> bool:
        """Return whether a usable external RTSP endpoint can be generated."""
        return self.host is not None and self.port is not None

    def url_for(self, stable_id: str) -> str | None:
        """Build one immutable external RTSP URL without exposing YI credentials."""
        if not self.available or _STABLE_ID_RE.fullmatch(stable_id) is None:
            return None
        assert self.host is not None
        assert self.port is not None
        path = f"/yi_{stable_id[:12]}"
        return str(URL.build(scheme="rtsp", host=self.host, port=self.port, path=path))


def _mapped_port(value: object) -> int | None:
    """Normalize one Supervisor network mapping value."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        port = value
    elif isinstance(value, str) and value.isdecimal():
        port = int(value)
    else:
        return None
    return port if 1 <= port <= 65535 else None


def _primary_ipv4(payload: dict[str, Any]) -> str | None:
    """Extract a routable primary IPv4 address from Supervisor network info."""
    interfaces = payload.get("interfaces")
    if not isinstance(interfaces, list):
        return None

    ordered = sorted(
        (item for item in interfaces if isinstance(item, dict)),
        key=lambda item: item.get("primary") is True,
        reverse=True,
    )
    for interface in ordered:
        if interface.get("enabled") is False:
            continue
        ipv4 = interface.get("ipv4")
        if not isinstance(ipv4, dict):
            continue
        addresses = ipv4.get("address")
        if not isinstance(addresses, list):
            continue
        for raw in addresses:
            if not isinstance(raw, str):
                continue
            try:
                address = ip_interface(raw).ip
            except ValueError:
                continue
            if (
                address.version == 4
                and not address.is_loopback
                and not address.is_unspecified
                and not address.is_link_local
            ):
                return str(address)
    return None


async def _async_lan_host(hass: HomeAssistant, supervisor: Any) -> str | None:
    """Resolve a LAN-reachable Home Assistant host, preferring Supervisor IPv4."""
    try:
        network_info = await supervisor.network.info()
    except SupervisorError:
        network_info = None
    if network_info is not None:
        host = _primary_ipv4(network_info.to_dict())
        if host is not None:
            return host

    try:
        internal_url = get_url(
            hass,
            allow_internal=True,
            allow_external=False,
            allow_cloud=False,
            prefer_external=False,
        )
    except NoURLAvailableError:
        internal_url = None
    if internal_url:
        host = URL(internal_url).host
        if host:
            try:
                parsed = ip_address(host)
            except ValueError:
                return host
            if not parsed.is_loopback and not parsed.is_unspecified:
                return host

    api = hass.config.api
    if api is not None:
        host = str(api.local_ip)
        try:
            parsed = ip_address(host)
        except ValueError:
            return host or None
        if not parsed.is_loopback and not parsed.is_unspecified:
            return host
    return None


async def _async_discovery_slug(
    supervisor: Any, *, api_host: str
) -> str | None:
    """Recover the originating App slug for entries created before slug persistence."""
    try:
        messages = await supervisor.discovery.list()
    except SupervisorError:
        return None

    for message in messages:
        config = getattr(message, "config", None)
        addon = getattr(message, "addon", None)
        if not isinstance(config, dict) or not isinstance(addon, str):
            continue
        if str(config.get("host") or "") == api_host:
            return addon
    return None


async def async_resolve_rtsp_export(
    hass: HomeAssistant,
    *,
    preferred_addon_slug: str | None,
    api_host: str,
) -> YiHomeRtspExport:
    """Resolve the App slug, LAN host and current external RTSP port mapping."""
    if not is_hassio(hass):
        _LOGGER.debug("Supervisor unavailable; YI external RTSP export disabled")
        return YiHomeRtspExport(addon_slug=None, host=None, port=None)

    supervisor = get_supervisor_client(hass)
    host = await _async_lan_host(hass, supervisor)

    candidates: list[str] = []
    if isinstance(preferred_addon_slug, str) and preferred_addon_slug.strip():
        candidates.append(preferred_addon_slug.strip())

    discovered_slug = await _async_discovery_slug(supervisor, api_host=api_host)
    if discovered_slug and discovered_slug not in candidates:
        candidates.append(discovered_slug)

    # Backward-compatible development/public-slug fallbacks. The discovery
    # result above remains authoritative when available.
    for fallback in ("local_yi_home", "yi_home"):
        if fallback not in candidates:
            candidates.append(fallback)

    for addon_slug in candidates:
        try:
            addon_info = await supervisor.addons.addon_info(addon_slug)
        except SupervisorError:
            continue
        network = addon_info.network
        if not isinstance(network, dict):
            network = {}
        port = _mapped_port(network.get(RTSP_CONTAINER_PORT_KEY))
        _LOGGER.debug(
            "Resolved YI RTSP export addon=%s host_available=%s port_mapped=%s",
            addon_slug,
            host is not None,
            port is not None,
        )
        return YiHomeRtspExport(addon_slug=addon_slug, host=host, port=port)

    _LOGGER.debug("Unable to resolve the YI Home App from Supervisor")
    return YiHomeRtspExport(addon_slug=discovered_slug, host=host, port=None)
