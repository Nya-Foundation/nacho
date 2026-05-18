"""End-to-end tests: the ``nacho`` CLI driving a live server.

Marked ``e2e`` (skipped by default). These exercise the full stack — the CLI
binary, the HTTP client, and a real server process — exactly as a user would.
"""

import shutil
import subprocess

import pytest

nacho_bin = shutil.which("nacho")
pytestmark = pytest.mark.skipif(nacho_bin is None, reason="nacho CLI not on PATH")


def _run(*args):
    return subprocess.run(
        [nacho_bin, *args], capture_output=True, text=True, timeout=30
    )


def test_cli_set_get_against_live_server(live_server):
    """`nacho set` then `nacho get --remote` round-trips a value."""
    set_result = _run(
        "set", "feature.enabled", "true",
        "--remote", live_server, "--app-name", "default",
    )
    assert set_result.returncode == 0, set_result.stderr

    get_result = _run(
        "get", "feature.enabled",
        "--remote", live_server, "--app-name", "default",
    )
    assert get_result.returncode == 0, get_result.stderr
    assert "True" in get_result.stdout


def test_cli_connect_dumps_remote_config(live_server):
    """`nacho connect` retrieves the full remote configuration."""
    _run("set", "team", "platform", "--remote", live_server, "--app-name", "default")
    result = _run(
        "connect", "--remote", live_server, "--app-name", "default", "--format", "json"
    )
    assert result.returncode == 0, result.stderr
    assert "platform" in result.stdout
