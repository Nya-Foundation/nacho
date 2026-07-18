"""Unit tests for the shared NachoClient REST wrapper.

HTTP traffic is stubbed at requests.request; live behavior is covered by
the integration suite.
"""

import pytest
import requests

from nacho.client import NachoClient
from nacho.storage.base import AuthError, ConflictError, NotFoundError, RemoteError


class FakeResponse:
    def __init__(self, status_code=200, payload=None, headers=None):
        self.status_code = status_code
        self._payload = payload
        self.reason = "Fake Reason"
        self.headers = headers or {}

    def json(self):
        if self._payload is None:
            raise ValueError("no body")
        return self._payload


@pytest.fixture
def http(monkeypatch):
    """Records requests and replays canned responses by URL suffix."""
    routes = {"get": [], "put": [], "post": [], "patch": [], "delete": [], "calls": []}

    def dispatch(method, url, **kwargs):
        routes["calls"].append((method.lower(), url, kwargs))
        for matcher, response in routes[method.lower()]:
            if url.rstrip("/").endswith(matcher):
                if isinstance(response, Exception):
                    raise response
                return response
        return FakeResponse(200, {"data": {}})

    monkeypatch.setattr(requests, "request", dispatch)
    return routes


@pytest.fixture
def client():
    return NachoClient("http://srv/", app_name="svc", api_key="k")


def _last_call(http):
    return http["calls"][-1]


def test_base_url_is_normalized_and_auth_header_sent(http, client):
    client.health()
    method, url, kwargs = _last_call(http)
    assert url == "http://srv/health"
    assert kwargs["headers"] == {"Authorization": "Bearer k"}


def test_no_auth_header_without_key(http):
    NachoClient("http://srv").health()
    assert _last_call(http)[2]["headers"] == {}


def test_error_mapping_from_status_codes(http, client):
    http["get"].append(("/401", FakeResponse(401, {"detail": "who are you"})))
    http["get"].append(("/404", FakeResponse(404, {"detail": "gone"})))
    http["get"].append(("/409", FakeResponse(409, {"detail": "clash"})))
    http["get"].append(("/500", FakeResponse(500, {"detail": "boom"})))
    http["get"].append(("/502", FakeResponse(502, None)))

    with pytest.raises(AuthError, match="who are you"):
        client.request("GET", "/401")
    with pytest.raises(NotFoundError, match="gone"):
        client.request("GET", "/404")
    with pytest.raises(ConflictError, match="clash"):
        client.request("GET", "/409")
    with pytest.raises(RemoteError, match="boom") as excinfo:
        client.request("GET", "/500")
    assert excinfo.value.status == 500
    # No JSON body: falls back to a generic message with the status.
    with pytest.raises(RemoteError, match="502"):
        client.request("GET", "/502")


def test_conflict_detail_carries_revisions(http, client):
    http["put"].append(
        (
            "/config",
            FakeResponse(
                409, {"detail": {"error": "revision_conflict", "expected": 3, "actual": 5}}
            ),
        )
    )
    with pytest.raises(ConflictError) as excinfo:
        client.put_config({"a": 1}, revision=3)
    assert excinfo.value.expected == 3 and excinfo.value.actual == 5


def test_allowed_statuses_do_not_raise(http, client):
    http["get"].append(("/api/apps/svc", FakeResponse(404, {"detail": "no app"})))
    resp = client.request("GET", "/api/apps/svc", allowed=(404,))
    assert resp.status_code == 404


def test_transport_error_is_wrapped(http, client):
    http["get"].append(("/health", requests.ConnectionError("refused")))
    with pytest.raises(RemoteError, match="GET .* failed"):
        client.health()


def test_config_endpoints_and_revision_header(http, client):
    http["get"].append(
        ("/api/apps/svc/config", FakeResponse(200, {"a": 1}, headers={"X-Nacho-Revision": "4"}))
    )
    data, rev = client.get_config()
    assert data == {"a": 1} and rev == 4

    http["get"].append(
        (
            "/config/a",
            FakeResponse(200, {"path": "a", "value": 1}, headers={"X-Nacho-Revision": "4"}),
        )
    )
    value, rev = client.get_path("a")
    assert value == 1 and rev == 4

    client.set_path("a", 2, revision=4, value_type="int")
    method, url, kwargs = _last_call(http)
    assert (method, url) == ("put", "http://srv/api/apps/svc/config/a")
    assert kwargs["json"] == {"value": 2, "type": "int", "revision": 4}

    client.delete_path("a", revision=4)
    method, url, kwargs = _last_call(http)
    assert (method, url) == ("delete", "http://srv/api/apps/svc/config/a")
    assert kwargs["params"] == {"revision": 4}


def test_app_endpoints(http, client):
    client.create_app(data={"a": 1}, schema={"type": "object"}, description="d")
    method, url, kwargs = _last_call(http)
    assert (method, url) == ("post", "http://srv/api/apps")
    assert kwargs["json"]["name"] == "svc"
    assert kwargs["json"]["schema"] == {"type": "object"}
    assert kwargs["json"]["description"] == "d"

    client.get_app_info()
    assert _last_call(http)[1] == "http://srv/api/apps/svc"

    client.list_apps()
    assert _last_call(http)[1] == "http://srv/api/apps"

    client.delete_app()
    assert _last_call(http)[0] == "delete"

    client.update_metadata(name="renamed", revision=2)
    method, url, kwargs = _last_call(http)
    assert (method, url) == ("patch", "http://srv/api/apps/svc/metadata")
    assert kwargs["json"] == {"name": "renamed", "revision": 2}


def test_schema_validate_history_and_convert_endpoints(http, client):
    http["get"].append(("/schema", FakeResponse(200, {"data": {"type": "object"}})))
    assert client.get_schema() == {"type": "object"}

    client.put_schema({"type": "object"}, revision=3)
    assert _last_call(http)[2]["json"] == {
        "schema": {"type": "object"},
        "schema_format": "json",
        "revision": 3,
    }

    http["post"].append(("/validate", FakeResponse(200, {"valid": True, "errors": []})))
    assert client.validate({"a": 1})["valid"] is True

    http["get"].append(("/history", FakeResponse(200, {"data": [{"revision": 2}]})))
    assert client.list_history() == [{"revision": 2}]

    http["get"].append(("/history/2", FakeResponse(200, {"data": {"revision": 2}})))
    assert client.get_history_snapshot(2) == {"revision": 2}

    client.rollback(2, expected_revision=5)
    assert _last_call(http)[2]["json"] == {"revision": 2, "expected_revision": 5}

    client.convert({"a": 1}, from_fmt="json", to_fmt="yaml")
    assert _last_call(http)[2]["json"] == {"data": {"a": 1}, "from": "json", "to": "yaml"}
