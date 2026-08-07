from __future__ import annotations

import json
from io import StringIO

import pytest
from mcp.types import CallToolResult, TextContent

from scripts import healthcheck


def result(payload: dict[str, object]) -> CallToolResult:
    return CallToolResult(
        content=[TextContent(type="text", text=json.dumps(payload))],
        structuredContent=payload,
    )


def test_validate_tool_names_requires_exact_surface() -> None:
    healthcheck.validate_tool_names(set(healthcheck.REQUIRED_TOOLS))
    with pytest.raises(healthcheck.HealthcheckError, match="unexpected"):
        healthcheck.validate_tool_names(healthcheck.REQUIRED_TOOLS | {"play_audio"})
    with pytest.raises(healthcheck.HealthcheckError, match="missing"):
        healthcheck.validate_tool_names({"xiaoai_health"})


def test_health_payload_requires_bridge_and_speaker_health() -> None:
    healthy = {"success": True, "data": {"status": "healthy", "speaker_ready": True}}
    assert healthcheck.health_payload(result(healthy)) == healthy

    for unhealthy in (
        {"success": False, "data": {"status": "healthy", "speaker_ready": True}},
        {"success": True, "data": {"status": "degraded", "speaker_ready": True}},
        {"success": True, "data": {"status": "healthy", "speaker_ready": False}},
    ):
        with pytest.raises(healthcheck.HealthcheckError, match="not healthy"):
            healthcheck.health_payload(result(unhealthy))


def test_main_emits_one_json_object_and_nonzero_on_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def failed_probe(timeout_seconds: float) -> dict[str, object]:
        raise healthcheck.HealthcheckError(f"failed within {timeout_seconds}s")

    monkeypatch.setattr(healthcheck, "probe", failed_probe)
    output = StringIO()
    assert healthcheck.main(["--timeout", "3"], output=output) == 1
    assert json.loads(output.getvalue()) == {
        "healthy": False,
        "error": "failed within 3.0s",
    }
    assert output.getvalue().count("\n") == 1


def test_probe_can_only_call_non_playing_health_tool() -> None:
    assert healthcheck.HEALTH_TOOL == "xiaoai_health"
    assert healthcheck.HEALTH_TOOL != "xiaoai_send_text"
