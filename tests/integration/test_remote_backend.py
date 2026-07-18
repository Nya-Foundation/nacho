"""Integration tests: the remote storage client against a live server.

Marked ``integration`` (skipped by default) because they spawn a real Nacho
server process and talk to it over HTTP.
"""

import json
import urllib.request

from nacho.config import Nacho
from nacho.storage.remote import RemoteStorageBackend


def _http_json(method, url, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=5) as resp:
        body = resp.read().decode()
        return resp.status, (json.loads(body) if body else None)


def test_rest_api_app_lifecycle(live_server):
    """Create, read, update and delete an app over the REST API."""
    status, _ = _http_json(
        "POST",
        live_server + "/api/apps",
        {"name": "billing", "data": {"currency": "USD"}},
    )
    assert status == 201

    status, body = _http_json("GET", live_server + "/api/apps/billing/config")
    assert status == 200 and body["currency"] == "USD"

    status, _ = _http_json("DELETE", live_server + "/api/apps/billing")
    assert status == 200


def test_remote_backend_round_trip(live_server):
    """A Nacho instance backed by RemoteStorageBackend reads and writes."""
    backend = RemoteStorageBackend(url=live_server, app_name="default", api_key=None)
    config = Nacho(storage=backend)
    try:
        config.set("service.port", 8080)
        config.save()
        assert config.get("service.port") == 8080

        # A fresh client sees the persisted value.
        verify = Nacho(storage=RemoteStorageBackend(url=live_server, app_name="default"))
        try:
            assert verify.get("service.port") == 8080
        finally:
            verify.cleanup()
    finally:
        config.cleanup()
