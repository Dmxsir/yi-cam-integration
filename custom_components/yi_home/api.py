"""Internal App API client for the YI Home integration."""

from __future__ import annotations

from typing import Any

import aiohttp


class YiHomeApiError(RuntimeError):
    """Base YI Home App API error."""


class YiHomeCannotConnect(YiHomeApiError):
    """The YI Home App cannot be reached."""


class YiHomeInvalidAuth(YiHomeApiError):
    """The App bearer token is not accepted."""


class YiHomeAccountError(YiHomeApiError):
    """YI rejected or could not validate the account configuration."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class YiHomeApi:
    """Small secret-safe client for the App's versioned API."""

    def __init__(self, session: aiohttp.ClientSession, host: str, port: int, token: str) -> None:
        self._session = session
        self._base = f"http://{host}:{port}/api/v1"
        self._headers = {"Authorization": f"Bearer {token}"}

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            async with self._session.request(
                method,
                f"{self._base}{path}",
                headers=self._headers,
                json=json_body,
                timeout=aiohttp.ClientTimeout(total=20),
            ) as response:
                try:
                    payload = await response.json(content_type=None)
                except (aiohttp.ContentTypeError, ValueError) as exc:
                    raise YiHomeApiError("invalid_response") from exc
        except (aiohttp.ClientError, TimeoutError) as exc:
            raise YiHomeCannotConnect from exc

        if response.status == 401:
            raise YiHomeInvalidAuth
        if response.status >= 400:
            error = payload.get("error") if isinstance(payload, dict) else None
            code = error.get("code") if isinstance(error, dict) else None
            raise YiHomeAccountError(str(code or "api_error"))
        if not isinstance(payload, dict):
            raise YiHomeApiError("invalid_response")
        return payload

    async def health(self) -> dict[str, Any]:
        """Return secret-safe App health state."""
        return await self._request("GET", "/health")

    async def account_status(self) -> dict[str, Any]:
        """Return secret-safe account configuration state."""
        return await self._request("GET", "/account")

    async def configure_account(self, payload: dict[str, str]) -> dict[str, Any]:
        """Validate and persist YI credentials in the App."""
        return await self._request("POST", "/account", json_body=payload)

    async def cameras(self) -> dict[str, Any]:
        """Return secret-safe camera inventory."""
        return await self._request("GET", "/cameras")
