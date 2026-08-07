#!/usr/bin/env python3
"""Non-playing stdio healthcheck for the Open XiaoAI MCP server."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import sys
from datetime import timedelta
from pathlib import Path
from typing import Any, TextIO

import anyio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import CallToolResult

PROJECT_DIR = Path(__file__).resolve().parents[1]
REQUIRED_TOOLS = {
    "xiaoai_send_text",
    "xiaoai_health",
    "xiaoai_status",
    "xiaoai_interrupt",
}
HEALTH_TOOL = "xiaoai_health"
DEFAULT_TIMEOUT_SECONDS = 15.0


class HealthcheckError(RuntimeError):
    """A concise, expected probe failure."""


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
    if (
        payload.get("success") is not True
        or not isinstance(data, dict)
        or data.get("status") != "healthy"
        or data.get("speaker_ready") is not True
    ):
        raise HealthcheckError("bridge or speaker is not healthy")
    return payload


async def probe(timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS) -> dict[str, Any]:
    """Start the local MCP, initialize it, inspect tools, and call health only."""
    uv = shutil.which("uv")
    if uv is None:
        raise HealthcheckError("uv executable not found")
    params = StdioServerParameters(
        command=uv,
        args=["--directory", str(PROJECT_DIR), "run", "open-xiaoai-mcp"],
        env=dict(os.environ),
        cwd=PROJECT_DIR,
    )
    with anyio.fail_after(timeout_seconds), open(os.devnull, "w", encoding="utf-8") as errlog:
        async with stdio_client(params, errlog=errlog) as (read_stream, write_stream):
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
        "tools": sorted(names),
        "bridge_status": payload["data"]["status"],
        "speaker_ready": payload["data"]["speaker_ready"],
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    return parser


def main(argv: list[str] | None = None, *, output: TextIO = sys.stdout) -> int:
    """Emit exactly one JSON object and return a monitoring-friendly status."""
    args = _parser().parse_args(argv)
    if args.timeout <= 0:
        print(json.dumps({"healthy": False, "error": "timeout must be positive"}), file=output)
        return 2
    try:
        report = asyncio.run(probe(args.timeout))
    except BaseException as exc:
        if isinstance(exc, (KeyboardInterrupt, SystemExit)):
            raise
        message = str(exc).strip() or type(exc).__name__
        print(json.dumps({"healthy": False, "error": message}, ensure_ascii=False), file=output)
        return 1
    print(json.dumps(report, ensure_ascii=False, sort_keys=True), file=output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
