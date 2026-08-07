from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from open_xiaoai_mcp import server
from open_xiaoai_mcp.client import BridgeError


class FakeClient:
    async def send_text(self, text: str, *, blocking: bool, timeout_ms: int) -> dict[str, object]:
        return {"success": True, "text": text, "blocking": blocking, "timeout": timeout_ms}

    async def health(self) -> dict[str, object]:
        return {"success": True, "data": {"status": "healthy"}}

    async def status(self) -> dict[str, object]:
        return {"success": True, "data": {"status": "idle"}}

    async def interrupt(self) -> dict[str, object]:
        raise BridgeError("bridge_unreachable", "无法连接小爱音箱桥接服务")


@pytest.fixture(autouse=True)
def fake_client(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server, "get_client", FakeClient)


@pytest.mark.asyncio
async def test_tool_functions_return_bridge_data(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        server,
        "get_local_now",
        lambda: datetime(2026, 8, 6, 12, tzinfo=ZoneInfo("Asia/Shanghai")),
    )
    assert (await server.xiaoai_send_text("你好", True, 20_000))["text"] == "你好"
    assert (await server.xiaoai_health())["success"] is True
    assert (await server.xiaoai_status())["data"] == {"status": "idle"}


@pytest.mark.asyncio
async def test_tool_function_converts_bridge_error() -> None:
    assert await server.xiaoai_interrupt() == {
        "success": False,
        "error": {
            "code": "bridge_unreachable",
            "message": "无法连接小爱音箱桥接服务",
        },
    }


@pytest.mark.asyncio
async def test_fastmcp_exposes_all_required_tools() -> None:
    tools = await server.mcp.list_tools()
    assert {tool.name for tool in tools} >= {
        "xiaoai_send_text",
        "xiaoai_health",
        "xiaoai_status",
        "xiaoai_interrupt",
    }
    send_tool = next(tool for tool in tools if tool.name == "xiaoai_send_text")
    assert send_tool.inputSchema["properties"]["timeout_ms"]["maximum"] == 600_000
    assert set(send_tool.inputSchema["properties"]) == {"text", "blocking", "timeout_ms"}


@pytest.mark.parametrize(
    ("hour", "minute", "blocked"),
    [
        (21, 59, False),
        (22, 0, True),
        (23, 59, True),
        (0, 0, True),
        (8, 59, True),
        (9, 0, False),
    ],
)
def test_quiet_hours_boundaries(hour: int, minute: int, blocked: bool) -> None:
    at = datetime(2026, 8, 6, hour, minute, tzinfo=ZoneInfo("Asia/Shanghai"))
    result = server.quiet_hours_error(at)
    assert (result is not None) is blocked


def test_http_config_restricts_non_loopback_bind(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XIAOAI_MCP_TRANSPORT", "streamable-http")
    monkeypatch.setenv("XIAOAI_MCP_HOST", "0.0.0.0")
    monkeypatch.delenv("XIAOAI_MCP_ALLOW_REMOTE", raising=False)
    with pytest.raises(ValueError, match="ALLOW_REMOTE"):
        server.load_server_config()


def test_http_config_builds_loopback_server_without_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XIAOAI_MCP_TRANSPORT", "streamable-http")
    monkeypatch.setenv("XIAOAI_MCP_PORT", "18765")
    config = server.load_server_config()
    http_mcp = server.create_mcp(config)
    assert config.path == "/mcp"
    assert http_mcp.settings.stateless_http is True
    assert http_mcp.settings.json_response is True


@pytest.mark.asyncio
async def test_quiet_hours_refuses_without_creating_or_calling_bridge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        server,
        "get_local_now",
        lambda: datetime(2026, 8, 6, 7, 59, tzinfo=ZoneInfo("Asia/Shanghai")),
    )

    def unexpected_client() -> FakeClient:
        pytest.fail("静默时段不得创建或调用桥接客户端")

    monkeypatch.setattr(server, "get_client", unexpected_client)
    result = await server.xiaoai_send_text("不应播放", False, 60_000)

    assert result == {
        "success": False,
        "error": {
            "code": "quiet_hours",
            "message": "静默时段禁止发送播报请求",
            "reason": "quiet_hours_policy",
            "local_time": "2026-08-06T07:59:00+08:00",
            "timezone": "Asia/Shanghai",
            "window": "22:00-09:00",
        },
    }
