"""Guarded stub for the native `open_xiaoai_server` extension.

The extension is a compiled Rust module (see native/) that may not be
built in every test environment. Tests that only exercise pure-Python
logic touching a small surface of it (e.g. speaker/api_server playback
result handling) can install a minimal stub instead of requiring a
native build. If the real extension is already importable, it is left
untouched so tests still exercise the genuine implementation.
"""

import importlib.util
import sys
import types


def ensure_open_xiaoai_server_stub() -> None:
    if "open_xiaoai_server" in sys.modules:
        return
    if importlib.util.find_spec("open_xiaoai_server") is not None:
        return

    stub = types.ModuleType("open_xiaoai_server")

    async def play_audio_file(*args, **kwargs):
        return None

    async def stop_playing(*args, **kwargs):
        return None

    stub.play_audio_file = play_audio_file
    stub.stop_playing = stop_playing
    sys.modules["open_xiaoai_server"] = stub
