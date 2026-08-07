import pytest

from _native_stub import ensure_open_xiaoai_server_stub

ensure_open_xiaoai_server_stub()

from core.services.speaker import (  # noqa: E402
    CommandResult,
    PlayResult,
    SpeakerManager,
    _safe_truncate,
)


@pytest.fixture
def manager():
    return SpeakerManager()


def test_exit_zero_is_success(manager):
    res = CommandResult(stdout="ok", stderr="", exit_code=0, ok=True)

    result = manager._build_play_result(res)

    assert isinstance(result, PlayResult)
    assert result.success is True
    assert result.started is True
    assert result.completed is True
    assert result.exit_code == 0
    assert result.error is None
    assert bool(result) is True


def test_exit_nonzero_started_and_completed_but_not_success(manager):
    res = CommandResult(stdout="", stderr="boom", exit_code=1, ok=True)

    result = manager._build_play_result(res)

    assert result.success is False
    assert result.started is True
    assert result.completed is True
    assert result.exit_code == 1
    assert result.error == "Playback command exited with non-zero status"
    assert bool(result) is False


def test_transport_failure_unknown_start_not_completed(manager):
    res = CommandResult(stdout="error", stderr="raw device response", exit_code=-1, ok=False)

    result = manager._build_play_result(res)

    assert result.success is False
    assert result.started is None
    assert result.completed is False
    assert result.exit_code is None
    assert result.error == "Failed to communicate with device shell"
    assert bool(result) is False


def test_error_field_does_not_leak_exception_details(manager):
    res = CommandResult(stdout="error", stderr="raw device response", exit_code=-1, ok=False)

    result = manager._build_play_result(res)

    assert result.started is None
    assert "Traceback" not in result.error
    assert "Exception" not in result.error
    assert result.error == "Failed to communicate with device shell"


def test_stdout_stderr_are_bounded():
    huge = "x" * 5000

    truncated = _safe_truncate(huge, limit=800)

    assert len(truncated) < len(huge)
    assert truncated.startswith("x" * 800)
    assert "truncated" in truncated


def test_safe_truncate_handles_none():
    assert _safe_truncate(None) == ""


def test_safe_truncate_short_value_unchanged():
    assert _safe_truncate("short") == "short"
