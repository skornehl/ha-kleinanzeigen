"""Client for the kleinanzeigen_bridge add-on's local HTTP API."""
from __future__ import annotations

from typing import Any

from aiohttp import ClientError, ClientSession, ClientTimeout

TIMEOUT = ClientTimeout(total=15)


class BridgeError(Exception):
    """The bridge is unreachable or rejected the request."""


class BridgeClient:
    def __init__(self, session: ClientSession, base_url: str) -> None:
        self._session = session
        self._base_url = base_url.rstrip("/")

    async def _request(self, method: str, path: str, payload: dict | None = None) -> dict[str, Any]:
        try:
            async with self._session.request(
                method, f"{self._base_url}{path}", json=payload, timeout=TIMEOUT
            ) as resp:
                data = await resp.json(content_type=None)
                if resp.status >= 400:
                    raise BridgeError(_describe(resp.status, data))
                return data
        except (ClientError, TimeoutError, ValueError) as err:
            raise BridgeError(f"Bridge nicht erreichbar: {err}") from err

    async def health(self) -> dict[str, Any]:
        return await self._request("GET", "/health")

    async def status(self) -> dict[str, Any]:
        return await self._request("GET", "/api/status")

    async def refresh(self) -> dict[str, Any]:
        return await self._request("POST", "/api/refresh")

    async def republish(self, ids: list[str] | None = None) -> dict[str, Any]:
        payload = {"all": True} if ids is None else {"ids": ids}
        return await self._request("POST", "/api/republish", payload)

    async def continue_job(self) -> dict[str, Any]:
        return await self._request("POST", "/api/continue")

    async def cancel(self) -> dict[str, Any]:
        return await self._request("POST", "/api/cancel")


def _describe(status: int, data: Any) -> str:
    if isinstance(data, dict):
        if data.get("error") == "busy":
            return "Es läuft bereits ein Auftrag"
        if data.get("error") == "not_allowed":
            return "Noch nicht erlaubt: " + "; ".join(data.get("blocked", []))
    return f"HTTP {status}"
