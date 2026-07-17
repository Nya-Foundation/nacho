"""Shared fixtures and collection hooks for Nacho tests."""

import json
import socket
import subprocess
import sys
import time
import urllib.request

import pytest

# Map each test subdirectory to the marker every test inside it should carry.
_DIR_MARKERS = {
    "unit": "unit",
    "smoke": "smoke",
    "integration": "integration",
    "e2e": "e2e",
    "docker": "docker",
}


def pytest_collection_modifyitems(config, items):
    """Auto-apply the unit/smoke/integration/e2e/docker marker by folder.

    This keeps individual test files free of boilerplate ``pytestmark`` lines:
    a test's location under tests/<kind>/ is the single source of truth.
    """
    for item in items:
        for part in item.nodeid.split("/"):
            marker = _DIR_MARKERS.get(part)
            if marker:
                item.add_marker(getattr(pytest.mark, marker))
                break


def _free_port():
    """Return a currently-unused localhost TCP port."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_for_health(base_url, timeout=20.0):
    """Block until ``base_url/health`` answers, or raise on timeout."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(base_url + "/health", timeout=1) as resp:
                if resp.status == 200:
                    return True
        except Exception:
            time.sleep(0.15)
    raise RuntimeError(f"server at {base_url} did not become healthy in {timeout}s")


class ServerHandle:
    """A running Nacho server subprocess plus enough state to restart it."""

    def __init__(self, proc, url, port, data_dir, api_key):
        self.proc = proc
        self.url = url
        self.port = port
        self.data_dir = data_dir
        self.api_key = api_key

    def stop(self, timeout=5.0):
        if self.proc.poll() is not None:
            return
        self.proc.terminate()
        try:
            self.proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait(timeout=timeout)


@pytest.fixture
def make_live_server(tmp_path):
    """Factory starting real Nacho servers through the actual CLI entrypoint.

    Returns a ``start(api_key=..., port=..., data_dir=...)`` callable yielding a
    :class:`ServerHandle`. Reusing a port and data_dir simulates a restart.
    """
    handles = []

    def start(*, api_key=None, port=None, data_dir=None):
        port = port or _free_port()
        data_dir = data_dir or (tmp_path / "server-state")
        cmd = [
            sys.executable, "-m", "nacho.cli.main", "server",
            "--host", "127.0.0.1", "--port", str(port), "--data-dir", str(data_dir),
        ]
        if api_key:
            cmd += ["--api-key", api_key]
        proc = subprocess.Popen(cmd)
        handle = ServerHandle(proc, f"http://127.0.0.1:{port}", port, data_dir, api_key)
        handles.append(handle)
        _wait_for_health(handle.url)
        return handle

    yield start
    for handle in handles:
        handle.stop()


@pytest.fixture
def live_server(make_live_server):
    """Base URL of a real, unauthenticated Nacho server subprocess."""
    return make_live_server().url


@pytest.fixture
def tmp_yaml(tmp_path):
    """Return a Path to a temporary YAML config file."""
    p = tmp_path / "config.yaml"
    p.write_text("database:\n  host: localhost\n  port: 5432\n")
    return p


@pytest.fixture
def tmp_json(tmp_path):
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"app": {"name": "test", "debug": True}}))
    return p


@pytest.fixture
def tmp_toml(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text('[server]\nhost = "0.0.0.0"\nport = 8080\n')
    return p


@pytest.fixture
def tmp_schema(tmp_path):
    schema = {
        "type": "object",
        "required": ["database"],
        "properties": {
            "database": {
                "type": "object",
                "required": ["host", "port"],
                "properties": {
                    "host": {"type": "string"},
                    "port": {"type": "integer", "minimum": 1, "maximum": 65535},
                },
            }
        },
    }
    p = tmp_path / "schema.json"
    p.write_text(json.dumps(schema))
    return p
