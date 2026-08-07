"""FastMCP server for Open XiaoAI (stdio or loopback Streamable HTTP)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Any
from zoneinfo import ZoneInfo

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from .client import DEFAULT_TIMEOUT_MS, MAX_TIMEOUT_MS, BridgeError, XiaoAIClient

QUIET_HOURS_TIMEZONE = "Asia/Shanghai"
QUIET_HOURS_WINDOW = "22:00-09:00"
_QUIET_HOURS_START_MINUTES = 22 * 60
_QUIET_HOURS_END_MINUTES = 9 * 60
_SHANGHAI = ZoneInfo(QUIET_HOURS_TIMEZONE)
HTTP_TRANSPORT = "streamable-http"
DEFAULT_HTTP_HOST = "127.0.0.1"
DEFAULT_HTTP_PORT = 8765
DEFAULT_HTTP_PATH = "/mcp"


@dataclass(frozen=True)
class ServerConfig:
    """Runtime configuration loaded from environment variables."""

    transport: str = "stdio"
    host: str = DEFAULT_HTTP_HOST
    port: int = DEFAULT_HTTP_PORT
    path: str = DEFAULT_HTTP_PATH
    allow_remote: bool = False


def _env_bool(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def load_server_config() -> ServerConfig:
    """Load and validate the MCP transport configuration."""
    transport = os.getenv("XIAOAI_MCP_TRANSPORT", "stdio").strip().lower()
    if transport not in {"stdio", HTTP_TRANSPORT}:
        raise ValueError("XIAOAI_MCP_TRANSPORT must be 'stdio' or 'streamable-http'")
    host = os.getenv("XIAOAI_MCP_HOST", DEFAULT_HTTP_HOST).strip()
    port = int(os.getenv("XIAOAI_MCP_PORT", str(DEFAULT_HTTP_PORT)))
    path = "/" + os.getenv("XIAOAI_MCP_PATH", DEFAULT_HTTP_PATH).strip().strip("/")
    allow_remote = _env_bool("XIAOAI_MCP_ALLOW_REMOTE")
    if not 1 <= port <= 65_535:
        raise ValueError("XIAOAI_MCP_PORT must be between 1 and 65535")
    if (
        transport == HTTP_TRANSPORT
        and host not in {"127.0.0.1", "localhost", "::1"}
        and not allow_remote
    ):
        raise ValueError("Non-loopback HTTP bind requires XIAOAI_MCP_ALLOW_REMOTE=true")
    return ServerConfig(transport, host, port, path, allow_remote)


def create_mcp(config: ServerConfig) -> FastMCP[Any]:
    """Create a server restricted to loopback unless explicitly overridden."""
    return FastMCP(
        "Open XiaoAI",
        instructions="通过本机或局域网 Open XiaoAI Bridge 控制小爱音箱。",
        host=config.host,
        port=config.port,
        streamable_http_path=config.path,
        stateless_http=True,
        json_response=True,
    )


def get_client() -> XiaoAIClient:
    """Create a client so environment changes are respected without import side effects."""
    return XiaoAIClient()


def get_local_now() -> datetime:
    """Return current time for the non-bypassable server-side quiet-hours policy."""
    return datetime.now(_SHANGHAI)


def quiet_hours_error(at: datetime) -> dict[str, Any] | None:
    """Return a structured refusal during 22:00-09:00 (overnight) in Asia/Shanghai."""
    local_time = at.astimezone(_SHANGHAI)
    minutes_since_midnight = local_time.hour * 60 + local_time.minute
    in_quiet_hours = (
        minutes_since_midnight >= _QUIET_HOURS_START_MINUTES
        or minutes_since_midnight < _QUIET_HOURS_END_MINUTES
    )
    if not in_quiet_hours:
        return None
    return {
        "success": False,
        "error": {
            "code": "quiet_hours",
            "message": "静默时段禁止发送播报请求",
            "reason": "quiet_hours_policy",
            "local_time": local_time.isoformat(timespec="seconds"),
            "timezone": QUIET_HOURS_TIMEZONE,
            "window": QUIET_HOURS_WINDOW,
        },
    }


async def _safe_call(operation: Any) -> dict[str, Any]:
    try:
        result: dict[str, Any] = await operation
        return result
    except BridgeError as exc:
        return exc.as_result()


async def xiaoai_send_text(
    text: Annotated[str, Field(min_length=1, max_length=10_000, description="要播报的文字")],
    blocking: Annotated[bool, Field(description="是否等待音箱播放完成")] = False,
    timeout_ms: Annotated[
        int,
        Field(
            ge=1_000,
            le=MAX_TIMEOUT_MS,
            description="播放等待超时(毫秒, 通常只需在 blocking=true 时调大)",
        ),
    ] = DEFAULT_TIMEOUT_MS,
) -> dict[str, Any]:
    """让小爱音箱播报文字。"""
    refusal = quiet_hours_error(get_local_now())
    if refusal is not None:
        return refusal
    return await _safe_call(get_client().send_text(text, blocking=blocking, timeout_ms=timeout_ms))


async def xiaoai_health() -> dict[str, Any]:
    """检查 Open XiaoAI Bridge 是否健康以及音箱是否就绪。"""
    return await _safe_call(get_client().health())


async def xiaoai_status() -> dict[str, Any]:
    """获取音箱当前播放状态。"""
    return await _safe_call(get_client().status())


async def xiaoai_interrupt() -> dict[str, Any]:
    """立即打断音箱当前播放。"""
    return await _safe_call(get_client().interrupt())


SERVER_CONFIG = load_server_config()
mcp = create_mcp(SERVER_CONFIG)
for _tool in (xiaoai_send_text, xiaoai_health, xiaoai_status, xiaoai_interrupt):
    mcp.tool()(_tool)


def main() -> None:
    """Run the configured transport; stdio remains the backwards-compatible default."""
    mcp.run(transport=SERVER_CONFIG.transport)  # type: ignore[arg-type]


if __name__ == "__main__":
    main()
