from _native_stub import ensure_open_xiaoai_server_stub

ensure_open_xiaoai_server_stub()

from core.services.api_server import _play_result_payload  # noqa: E402
from core.services.speaker import PlayResult  # noqa: E402


def test_structured_play_result_retains_all_fields():
    result = PlayResult(
        success=True,
        started=True,
        completed=True,
        exit_code=0,
        stdout="hello",
        stderr="",
        error=None,
    )

    payload = _play_result_payload(result)

    assert payload == {
        "success": True,
        "started": True,
        "completed": True,
        "exit_code": 0,
        "stdout": "hello",
        "stderr": "",
        "error": None,
    }


def test_structured_play_result_failure_retains_all_fields():
    result = PlayResult(
        success=False,
        started=False,
        completed=False,
        exit_code=None,
        stdout="error",
        stderr="raw",
        error="Failed to communicate with device shell",
    )

    payload = _play_result_payload(result)

    assert payload["success"] is False
    assert payload["started"] is False
    assert payload["completed"] is False
    assert payload["exit_code"] is None
    assert payload["error"] == "Failed to communicate with device shell"


def test_transport_timeout_payload_reports_unknown_start():
    """A shell transport timeout cannot prove playback never started, so the
    API payload must expose started=None (JSON null) rather than false."""
    result = PlayResult(
        success=False,
        started=None,
        completed=False,
        exit_code=None,
        stdout="error",
        stderr="run_shell error: request timeout",
        error="Failed to communicate with device shell",
    )

    payload = _play_result_payload(result)

    assert payload == {
        "success": False,
        "started": None,
        "completed": False,
        "exit_code": None,
        "stdout": "error",
        "stderr": "run_shell error: request timeout",
        "error": "Failed to communicate with device shell",
    }


def test_legacy_bool_result_falls_back_to_plain_success_shape():
    assert _play_result_payload(True) == {"success": True}
    assert _play_result_payload(False) == {"success": False}
