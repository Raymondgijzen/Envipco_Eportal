from __future__ import annotations

import asyncio
import csv
from dataclasses import dataclass
from datetime import date
from io import StringIO
from typing import Any

import aiohttp

from .const import EP_BASE


class EnvipcoApiError(Exception):
    """Generic API error."""


@dataclass
class EnvipcoEPortalApiClient:
    session: aiohttp.ClientSession
    username: str
    password: str

    _api_key: str | None = None
    _lock: asyncio.Lock = asyncio.Lock()

    async def _request_text(self, url: str) -> tuple[int, str]:
        async with self.session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
            return resp.status, await resp.text()

    async def _request_json(self, url: str) -> tuple[int, Any]:
        async with self.session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
            data = await resp.json(content_type=None)
            return resp.status, data

    async def login(self) -> str:
        url = f"{EP_BASE}/login?username={self.username}&password={self.password}"
        status, data = await self._request_json(url)
        if status != 200 or not isinstance(data, dict) or "ApiKey" not in data:
            raise EnvipcoApiError(f"Login failed: HTTP {status} - {data}")
        self._api_key = data["ApiKey"]
        return self._api_key

    async def get_api_key(self) -> str:
        async with self._lock:
            if self._api_key:
                return self._api_key
            return await self.login()

    async def _ensure_key_and_retry_json(self, url_builder) -> Any:
        api_key = await self.get_api_key()
        url = url_builder(api_key)
        status, data = await self._request_json(url)
        if status in (303, 304):
            async with self._lock:
                self._api_key = None
                api_key = await self.login()
            url = url_builder(api_key)
            status, data = await self._request_json(url)
        if status != 200:
            raise EnvipcoApiError(f"HTTP {status}: {data}")
        return data

    async def _ensure_key_and_retry_csv(self, url_builder) -> list[dict[str, str]]:
        api_key = await self.get_api_key()
        url = url_builder(api_key)
        status, text = await self._request_text(url)
        if status in (303, 304):
            async with self._lock:
                self._api_key = None
                api_key = await self.login()
            url = url_builder(api_key)
            status, text = await self._request_text(url)
        if status != 200:
            raise EnvipcoApiError(f"HTTP {status}: {text}")

        reader = csv.DictReader(StringIO(text))
        return [row for row in reader]

    async def rvm_stats(self, rvms: list[str], for_date: date) -> dict[str, Any]:
        # Docs: if rvms parameter is blank or not specified, all rvms the user has access to are used.
        def build(api_key: str) -> str:
            parts = [f"{EP_BASE}/rvmStats?apiKey={api_key}&rvmDate={for_date.isoformat()}"]
            for rvm in rvms or []:
                parts.append(f"&rvms={rvm}")
            return "".join(parts)

        data = await self._ensure_key_and_retry_json(build)
        if isinstance(data, dict):
            return data.get("rvmData", {}) or {}
        return {}

    async def rejects(self, rvms: list[str], start: date, end: date, include_acceptance: bool = True) -> list[dict[str, str]]:
        def build(api_key: str) -> str:
            parts = [f"{EP_BASE}/rejects?apiKey={api_key}&startDate={start.isoformat()}&endDate={end.isoformat()}"]
            if include_acceptance:
                parts.append("&acceptance=yes")
            for rvm in rvms or []:
                parts.append(f"&rvms={rvm}")
            return "".join(parts)

        return await self._ensure_key_and_retry_csv(build)

    async def rvms(self) -> list[str]:
        """Return all machine serial numbers available for the user.

        The PDF documentation doesn't define a dedicated '/rvms' endpoint.
        It *does* say: rvmStats will return all RVMs when the 'rvms' parameter is omitted.
        So we call rvmStats for today without rvms and use the keys of rvmData.
        """
        data = await self.rvm_stats(rvms=[], for_date=date.today())
        if isinstance(data, dict):
            return sorted([str(k).strip() for k in data.keys() if str(k).strip()])
        return []
