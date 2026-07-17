"""End-to-end tests: the ``nacho`` CLI driving a live server.

Marked ``e2e`` (skipped by default). These exercise the full stack — the CLI
binary, the HTTP client, and a real server process — exactly as a user would.
"""

import json
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
    """`nacho set` then `nacho get --remote` round-trips a typed value."""
    set_result = _run(
        "set", "feature.enabled", "true",
        "--remote", live_server, "--app-name", "default",
    )
    assert set_result.returncode == 0, set_result.stderr

    get_result = _run(
        "get", "--format", "json",
        "--remote", live_server, "--app-name", "default",
    )
    assert get_result.returncode == 0, get_result.stderr
    assert json.loads(get_result.stdout) == {"feature": {"enabled": True}}


def test_cli_app_and_schema_lifecycle(live_server, tmp_path):
    """apps create → schema push → invalid write refused → validate --remote."""
    schema_file = tmp_path / "schema.json"
    schema_file.write_text(json.dumps({
        "type": "object",
        "properties": {"port": {"type": "integer"}},
        "required": ["port"],
    }))
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps({"port": 8080}))

    created = _run(
        "apps", "create", "svc", "--remote", live_server,
        "--config", str(config_file), "--schema", str(schema_file),
    )
    assert created.returncode == 0, created.stderr

    listed = _run("apps", "list", "--remote", live_server, "--format", "json")
    assert listed.returncode == 0, listed.stderr
    assert json.loads(listed.stdout)["svc"]["schema"] is True

    # A write the schema forbids fails loudly with a non-zero exit code.
    bad = _run("set", "port", "not-an-int", "--remote", live_server, "--app-name", "svc")
    assert bad.returncode == 1
    assert "port" in bad.stderr

    # The local file validates against the schema the server enforces.
    valid = _run(
        "validate", "--config", str(config_file),
        "--remote", live_server, "--app-name", "svc",
    )
    assert valid.returncode == 0, valid.stderr
    assert "successful" in valid.stdout

    bad_file = tmp_path / "bad.json"
    bad_file.write_text(json.dumps({"port": "nope"}))
    invalid = _run(
        "validate", "--config", str(bad_file),
        "--remote", live_server, "--app-name", "svc",
    )
    assert invalid.returncode == 1
    assert "port" in invalid.stdout

    deleted = _run("apps", "delete", "svc", "--remote", live_server)
    assert deleted.returncode == 0, deleted.stderr


def test_cli_auth_flow(make_live_server):
    """--api-key is required and sufficient against an auth-enabled server."""
    server = make_live_server(api_key="sekret")

    denied = _run("get", "--remote", server.url, "--app-name", "default")
    assert denied.returncode == 1
    assert "Unauthorized" in denied.stderr

    allowed = _run(
        "set", "answer", "42",
        "--remote", server.url, "--app-name", "default", "--api-key", "sekret",
    )
    assert allowed.returncode == 0, allowed.stderr

    fetched = _run(
        "get", "answer", "--format", "json",
        "--remote", server.url, "--app-name", "default", "--api-key", "sekret",
    )
    assert fetched.returncode == 0, fetched.stderr
    assert json.loads(fetched.stdout) == 42
