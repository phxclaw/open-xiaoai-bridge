"""Async client for the Open XiaoAI bridge HTTP API."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import httpx

DEFAULT_BRIDGE_URL = "http://127.0.0.1:9092"
DEFAULT_TIMEOUT_MS = 60_000
MAX_TIMEOUT_MS = 600_000


@dataclass(slots=True)
class BridgeError(Exception):
    """A safe, structured bridge communication error."""

    code: str
    message: str
    status_code: int | None = None

    def as_result(self) -> dict[str, Any]:
        error: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.status_code is not None:
            error["status_code"] = self.status_code
        return {"success": False, "error": error}


class XiaoAIClient:
    """Small, stateless API client with bounded timeouts."""

    def __init__(
        self,
        base_url: str | None = None,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        configured_url = (
            base_url if base_url is not None else os.getenv("XIAOAI_BRIDGE_URL", DEFAULT_BRIDGE_URL)
        )
        self.base_url = configured_url.rstrip("/")
        self.transport = transport

    async def send_text(
        self, text: str, *, blocking: bool = False, timeout_ms: int = DEFAULT_TIMEOUT_MS
    ) -> dict[str, Any]:
        read_seconds = timeout_ms / 1000 + 5 if blocking else 15.0
        return await self._request(
            "POST",
            "/api/play/text",
            json={"text": text, "blocking": blocking, "timeout": timeout_ms},
            read_timeout=read_seconds,
        )

    async def health(self) -> dict[str, Any]:
        return await self._request("GET", "/api/health")

    async def status(self) -> dict[str, Any]:
        return await self._request("GET", "/api/status")

    async def interrupt(self) -> dict[str, Any]:
        return await self._request("POST", "/api/interrupt")

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        read_timeout: float = 10.0,
    ) -> dict[str, Any]:
        timeout = httpx.Timeout(connect=5.0, read=read_timeout, write=10.0, pool=5.0)
        try:
            async with httpx.AsyncClient(
                base_url=self.base_url,
                timeout=timeout,
                transport=self.transport,
                follow_redirects=False,
            ) as client:
                response = await client.request(method, path, json=json)
        except httpx.TimeoutException as exc:
            raise BridgeError("bridge_timeout", "小爱音箱桥接服务请求超时") from exc
        except httpx.RequestError as exc:
            raise BridgeError("bridge_unreachable", "无法连接小爱音箱桥接服务") from exc

        try:
            body = response.json()
        except ValueError as exc:
            raise BridgeError(
                "invalid_response",
                "小爱音箱桥接服务返回了非 JSON 响应",
                response.status_code,
            ) from exc

        if not isinstance(body, dict):
            raise BridgeError(
                "invalid_response",
                "小爱音箱桥接服务返回的 JSON 不是对象",
                response.status_code,
            )

        if response.is_error:
            bridge_message = body.get("error")
            message = bridge_message if isinstance(bridge_message, str) else "桥接服务请求失败"
            raise BridgeError("bridge_http_error", message, response.status_code)

        return body
