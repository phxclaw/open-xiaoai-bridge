#!/usr/bin/env python3
"""Read-only healthcheck for the running Open XiaoAI Streamable HTTP MCP."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import timedelta
from typing import Any, TextIO

import anyio
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.types import CallToolResult

REQUIRED_TOOLS = {
    "xiaoai_send_text",
    "xiaoai_health",
    "xiaoai_status",
    "xiaoai_interrupt",
}
HEALTH_TOOL = "xiaoai_health"
DEFAULT_TIMEOUT_SECONDS = 15.0
DEFAULT_MCP_URL = "http://127.0.0.1:8765/mcp"


class HealthcheckError(RuntimeError):
    """A concise, expected probe failure."""


def error_message(exc: BaseException) -> str:
    """Unwrap AnyIO exception groups so monitors see the actionable cause."""
    children = getattr(exc, "exceptions", ())
    if isinstance(children, tuple):
        for child in children:
            message = error_message(child)
            if message:
                return message
    return str(exc).strip() or type(exc).__name__


def validate_tool_names(tool_names: set[str]) -> None:
    """Require the MCP surface to contain exactly the expected tools."""
    if tool_names != REQUIRED_TOOLS:
        missing = sorted(REQUIRED_TOOLS - tool_names)
        unexpected = sorted(tool_names - REQUIRED_TOOLS)
        raise HealthcheckError(f"tool mismatch (missing={missing}, unexpected={unexpected})")


def health_payload(result: CallToolResult) -> dict[str, Any]:
    """Extract and validate the structured xiaoai_health response."""
    if result.isError:
        raise HealthcheckError("xiaoai_health returned an MCP error")
    payload = result.structuredContent
    if not isinstance(payload, dict):
        # Compatibility with MCP servers which return JSON only as text content.
        texts = [getattr(item, "text", None) for item in result.content]
        text = next((item for item in texts if isinstance(item, str)), None)
        if text is None:
            raise HealthcheckError("xiaoai_health returned no JSON object")
        try:
            decoded = json.loads(text)
        except json.JSONDecodeError as exc:
            raise HealthcheckError("xiaoai_health returned invalid JSON") from exc
        if not isinstance(decoded, dict):
            raise HealthcheckError("xiaoai_health returned non-object JSON")
        payload = decoded

    data = payload.get("data")
    if payload.get("success") is not True:
        error = payload.get("error")
        if isinstance(error, dict):
            code = error.get("code")
            message = error.get("message")
            detail = ": ".join(str(item) for item in (code, message) if item)
            if detail:
                raise HealthcheckError(detail)
        raise HealthcheckError("xiaoai_health reported failure")
    if (
        not isinstance(data, dict)
        or data.get("status") != "healthy"
        or data.get("speaker_ready") is not True
    ):
        raise HealthcheckError("bridge or speaker is not healthy")
    return payload


async def probe(
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    mcp_url: str = DEFAULT_MCP_URL,
) -> dict[str, Any]:
    """Connect to the existing MCP, inspect tools, and call health only."""
    with anyio.fail_after(timeout_seconds):
        async with streamable_http_client(mcp_url) as (read_stream, write_stream, _):
            async with ClientSession(
                read_stream,
                write_stream,
                read_timeout_seconds=timedelta(seconds=timeout_seconds),
            ) as session:
                await session.initialize()
                tools = await session.list_tools()
                names = {tool.name for tool in tools.tools}
                validate_tool_names(names)
                result = await session.call_tool(HEALTH_TOOL, arguments={})
                payload = health_payload(result)
    return {
        "healthy": True,
        "mcp_url": mcp_url,
        "tools": sorted(names),
        "bridge_status": payload["data"]["status"],
        "speaker_ready": payload["data"]["speaker_ready"],
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--url", default=DEFAULT_MCP_URL)
    return parser


def main(argv: list[str] | None = None, *, output: TextIO = sys.stdout) -> int:
    """Emit exactly one JSON object and return a monitoring-friendly status."""
    args = _parser().parse_args(argv)
    if args.timeout <= 0:
        print(json.dumps({"healthy": False, "error": "timeout must be positive"}), file=output)
        return 2
    try:
        report = asyncio.run(probe(args.timeout, args.url))
    except BaseException as exc:
        if isinstance(exc, (KeyboardInterrupt, SystemExit)):
            raise
        message = error_message(exc)
        print(json.dumps({"healthy": False, "error": message}, ensure_ascii=False), file=output)
        return 1
    print(json.dumps(report, ensure_ascii=False, sort_keys=True), file=output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
