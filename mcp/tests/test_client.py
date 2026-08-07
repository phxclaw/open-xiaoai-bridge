from __future__ import annotations

import httpx
import pytest

from open_xiaoai_mcp.client import BridgeError, XiaoAIClient


def client_for(handler: httpx.AsyncBaseTransport) -> XiaoAIClient:
    return XiaoAIClient("http://bridge.test:9092", transport=handler)


@pytest.mark.asyncio
async def test_send_text_posts_expected_payload() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/api/play/text"
        assert request.read() == b'{"text":"hello","blocking":true,"timeout":42000}'
        return httpx.Response(200, json={"success": True})

    result = await client_for(httpx.MockTransport(handler)).send_text(
        "hello", blocking=True, timeout_ms=42_000
    )
    assert result == {"success": True}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "path", "call"),
    [
        ("GET", "/api/health", "health"),
        ("GET", "/api/status", "status"),
        ("POST", "/api/interrupt", "interrupt"),
    ],
)
async def test_control_endpoints(method: str, path: str, call: str) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == method
        assert request.url.path == path
        return httpx.Response(200, json={"success": True, "endpoint": path})

    client = client_for(httpx.MockTransport(handler))
    result = await getattr(client, call)()
    assert result["success"] is True


@pytest.mark.asyncio
async def test_http_error_is_structured_and_preserves_safe_bridge_message() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(503, json={"success": False, "error": "not ready"})
    )
    with pytest.raises(BridgeError) as caught:
        await client_for(transport).status()
    assert caught.value.as_result() == {
        "success": False,
        "error": {
            "code": "bridge_http_error",
            "message": "not ready",
            "status_code": 503,
        },
    }


@pytest.mark.asyncio
async def test_invalid_json_is_structured() -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(200, text="oops"))
    with pytest.raises(BridgeError, match="非 JSON") as caught:
        await client_for(transport).health()
    assert caught.value.code == "invalid_response"


@pytest.mark.asyncio
async def test_network_timeout_is_structured() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    with pytest.raises(BridgeError) as caught:
        await client_for(httpx.MockTransport(handler)).health()
    assert caught.value.code == "bridge_timeout"
    assert "slow" not in caught.value.message
