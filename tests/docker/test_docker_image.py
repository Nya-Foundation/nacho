"""Docker tests: build the image, run it, exercise core functionality.

Marked ``docker`` (skipped by default). They require a working Docker daemon
and take a minute or so because the image is built from scratch.
"""

import json
import shutil
import socket
import subprocess
import time
import urllib.request
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
IMAGE_TAG = "nacho:pytest-docker"

pytestmark = pytest.mark.skipif(
    shutil.which("docker") is None, reason="docker CLI not available"
)


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _http_json(method, url, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=5) as resp:
        body = resp.read().decode()
        return resp.status, (json.loads(body) if body else None)


@pytest.fixture(scope="module")
def docker_server():
    """Build the image, run a container, yield its base URL."""
    build = subprocess.run(
        ["docker", "build", "-t", IMAGE_TAG, "."],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=600,
    )
    assert build.returncode == 0, f"docker build failed:\n{build.stderr}"

    port = _free_port()
    run = subprocess.run(
        ["docker", "run", "-d", "--rm", "-p", f"{port}:8000", IMAGE_TAG],
        capture_output=True, text=True, timeout=60,
    )
    assert run.returncode == 0, f"docker run failed:\n{run.stderr}"
    container_id = run.stdout.strip()

    base_url = f"http://127.0.0.1:{port}"
    try:
        deadline = time.time() + 30
        while time.time() < deadline:
            try:
                urllib.request.urlopen(base_url + "/health", timeout=1)
                break
            except Exception:
                time.sleep(0.3)
        else:
            logs = subprocess.run(
                ["docker", "logs", container_id], capture_output=True, text=True
            )
            pytest.fail(f"container never became healthy:\n{logs.stdout}\n{logs.stderr}")
        yield base_url
    finally:
        subprocess.run(["docker", "rm", "-f", container_id], capture_output=True)


def test_container_health(docker_server):
    """The containerised server reports a healthy /health endpoint."""
    status, body = _http_json("GET", docker_server + "/health")
    assert status == 200 and body["status"] == "ok"


def test_container_serves_ui(docker_server):
    """The management UI is bundled into the image."""
    with urllib.request.urlopen(docker_server + "/ui", timeout=5) as resp:
        assert resp.status == 200
        assert "Nacho" in resp.read().decode()


def test_container_app_and_config_lifecycle(docker_server):
    """Core remote functionality works end-to-end against the container."""
    status, _ = _http_json(
        "POST", docker_server + "/api/apps",
        {"name": "orders", "data": {"region": "eu"}},
    )
    assert status == 201

    status, body = _http_json("GET", docker_server + "/api/apps/orders/config")
    assert status == 200 and body["region"] == "eu"

    # Update a single path and read it back.
    status, _ = _http_json(
        "PUT", docker_server + "/api/apps/orders/config/region", {"value": "us"}
    )
    assert status == 200
    status, body = _http_json("GET", docker_server + "/api/apps/orders/config")
    assert body["region"] == "us"


def test_container_remote_backend(docker_server):
    """The Python remote client talks to the containerised server."""
    from nacho.config import Nacho
    from nacho.storage.remote import RemoteStorageBackend

    config = Nacho(storage=RemoteStorageBackend(url=docker_server, app_name="default"))
    try:
        config.set("dockerized", True)
        config.save()
        assert config.get("dockerized") is True
    finally:
        config.cleanup()
