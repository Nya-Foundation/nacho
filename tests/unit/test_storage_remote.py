"""Unit tests for RemoteStorageBackend and NachoClient.

All HTTP and WebSocket traffic is stubbed, so these run without a server.
The live round-trip against a real server is covered by the integration suite.
"""

import json
import types

import pytest
import requests

from nacho.storage.base import AuthError, ConflictError, StorageError
from nacho.storage.remote import RemoteStorageBackend


class FakeResponse:
    """Stand-in for ``requests.Response``."""

    def __init__(self, status_code=200, payload=None, text="", headers=None):
        self.status_code = status_code
        self._payload = payload
        self.text = text
        self.reason = "Fake Reason"
        self.headers = headers or {}

    @property
    def ok(self):
        return self.status_code < 400

    def json(self):
        if self._payload is None:
            raise ValueError("no body")
        return self._payload


@pytest.fixture
def http(monkeypatch):
    """Routes requests.request to per-URL canned responses.

    Tests register handlers in ``routes`` keyed by HTTP method; each entry is
    a (url-suffix, FakeResponse-or-Exception) pair. Requests are recorded in
    ``routes["calls"]`` as (method, url, kwargs).
    """
    routes = {"get": [], "put": [], "post": [], "patch": [], "delete": [], "calls": []}

    def dispatch(method, url, **kwargs):
        routes["calls"].append((method.lower(), url, kwargs))
        # Match on URL suffix so "/api/apps/default" does not also
        # capture "/api/apps/default/config".
        for matcher, response in routes[method.lower()]:
            if url.rstrip("/").endswith(matcher):
                if isinstance(response, Exception):
                    raise response
                return response
        return FakeResponse(200, {})

    monkeypatch.setattr(requests, "request", dispatch)
    return routes


# ---------------------------------------------------------------------------
# Construction / connection
# ---------------------------------------------------------------------------
def test_construct_verifies_existing_app(http):
    backend = RemoteStorageBackend("http://srv")
    assert backend._connected is True
    assert str(backend) == "RemoteStorageBackend(url='http://srv', app='default')"


def test_construct_raises_when_unreachable(http):
    http["get"].append(("/api/apps/default", requests.ConnectionError("refused")))
    with pytest.raises(StorageError, match="Cannot reach"):
        RemoteStorageBackend("http://srv")


def test_construct_raises_auth_error_on_bad_key(http):
    http["get"].append(
        ("/api/apps/default", FakeResponse(401, {"error": "Unauthorized: invalid API key"}))
    )
    with pytest.raises(AuthError, match="Unauthorized"):
        RemoteStorageBackend("http://srv", api_key="wrong")


def test_construct_tolerates_missing_app(http):
    """Connecting is read-only: a 404 for the app is fine, and no POST happens."""
    http["get"].append(("/api/apps/default", FakeResponse(404, {"detail": "not found"})))
    backend = RemoteStorageBackend("http://srv")
    assert backend._connected
    assert all(method != "post" for method, _, _ in http["calls"])


def test_load_missing_app_raises_helpful_error(http):
    http["get"].append(("/api/apps/default/config", FakeResponse(404, {"detail": "nope"})))
    backend = RemoteStorageBackend("http://srv")
    with pytest.raises(StorageError, match="does not exist"):
        backend.load()


def test_create_app_failure_raises(http):
    """save() on a missing app auto-creates it; a failed create surfaces loudly."""
    http["put"].append(("/api/apps/default/config", FakeResponse(404, {"detail": "no app"})))
    http["post"].append(("/api/apps", FakeResponse(500, {}, text="nope")))
    backend = RemoteStorageBackend("http://srv")
    with pytest.raises(StorageError, match="POST .* failed"):
        backend.save({"x": 1})


# ---------------------------------------------------------------------------
# load / save
# ---------------------------------------------------------------------------
def test_load_returns_remote_config(http):
    http["get"].append(("/config", FakeResponse(200, {"feature": True})))
    backend = RemoteStorageBackend("http://srv")
    assert backend.load() == {"feature": True}


def test_load_rejects_non_object_payload(http):
    http["get"].append(("/config", FakeResponse(200, ["not", "a", "dict"])))
    backend = RemoteStorageBackend("http://srv")
    with pytest.raises(StorageError, match="non-object"):
        backend.load()


def test_load_wraps_request_exception(http):
    backend = RemoteStorageBackend("http://srv")
    http["get"].append(("/config", requests.Timeout("slow")))
    with pytest.raises(StorageError, match="GET .* failed"):
        backend.load()


def test_save_replaces_config(http):
    http["put"].append(("/config", FakeResponse(200, {"revision": 2})))
    backend = RemoteStorageBackend("http://srv")
    backend.save({"a": 1})  # no exception
    assert backend.revision == 2


def test_save_creates_app_on_404(http):
    http["put"].append(("/config", FakeResponse(404, {"detail": "no app"})))
    http["post"].append(("/api/apps", FakeResponse(201, {"app": {"revision": 1}})))
    backend = RemoteStorageBackend("http://srv")
    backend.save({"a": 1})
    assert backend.revision == 1


def test_save_raises_on_server_error(http):
    http["put"].append(("/config", FakeResponse(500, {"detail": "boom"})))
    backend = RemoteStorageBackend("http://srv")
    with pytest.raises(StorageError, match="boom"):
        backend.save({"a": 1})


def test_save_wraps_put_transport_error(http):
    backend = RemoteStorageBackend("http://srv")
    http["put"].append(("/config", requests.ConnectionError("down")))
    with pytest.raises(StorageError, match="PUT .* failed"):
        backend.save({"a": 1})


# ---------------------------------------------------------------------------
# Revision tracking / optimistic concurrency
# ---------------------------------------------------------------------------
def test_load_records_revision_header(http):
    http["get"].append(("/config", FakeResponse(200, {"a": 1}, headers={"X-Nacho-Revision": "7"})))
    backend = RemoteStorageBackend("http://srv")
    backend.load()
    assert backend.revision == 7


def test_save_sends_last_seen_revision(http):
    http["get"].append(("/config", FakeResponse(200, {"a": 1}, headers={"X-Nacho-Revision": "7"})))
    http["put"].append(("/config", FakeResponse(200, {"revision": 8})))
    backend = RemoteStorageBackend("http://srv")
    backend.load()
    backend.save({"a": 2})
    put_calls = [kw for method, _, kw in http["calls"] if method == "put"]
    assert put_calls[0]["json"]["revision"] == 7
    assert backend.revision == 8


def test_save_conflict_raises_typed_error(http):
    http["get"].append(("/config", FakeResponse(200, {"a": 1}, headers={"X-Nacho-Revision": "7"})))
    http["put"].append(
        (
            "/config",
            FakeResponse(
                409, {"detail": {"error": "revision_conflict", "expected": 7, "actual": 9}}
            ),
        )
    )
    backend = RemoteStorageBackend("http://srv")
    backend.load()
    with pytest.raises(ConflictError, match="revision race") as excinfo:
        backend.save({"a": 2})
    assert excinfo.value.expected == 7
    assert excinfo.value.actual == 9
    assert isinstance(excinfo.value, StorageError)  # existing catch-alls still work


def test_stale_ws_revision_is_dropped(http):
    backend = RemoteStorageBackend("http://srv")
    received = []
    backend.on_remote_change = received.append
    backend._on_message(None, json.dumps({"type": "update", "revision": 5, "data": {"x": 1}}))
    backend._on_message(None, json.dumps({"type": "update", "revision": 4, "data": {"x": 0}}))
    backend._on_message(None, json.dumps({"type": "update", "revision": 5, "data": {"x": 1}}))
    assert received == [{"x": 1}]
    assert backend.revision == 5


def test_new_server_generation_accepts_lower_initial_revision(http):
    backend = RemoteStorageBackend("http://srv")
    received = []
    backend.on_remote_change = received.append
    backend._on_message(
        None,
        json.dumps({"type": "update", "generation": "old", "revision": 5, "data": {"old": True}}),
    )
    backend._on_message(
        None,
        json.dumps({"type": "initial_config", "generation": "new", "revision": 1, "data": {}}),
    )
    assert received == [{"old": True}, {}]
    assert backend.generation == "new"
    assert backend.revision == 1


def test_rest_generation_change_resets_revision_scope(http):
    http["get"].append(
        (
            "/config",
            FakeResponse(
                200,
                {"fresh": True},
                headers={"X-Nacho-Revision": "1", "X-Nacho-Generation": "new"},
            ),
        )
    )
    backend = RemoteStorageBackend("http://srv")
    backend._revision = 9
    backend._generation = "old"
    assert backend.load() == {"fresh": True}
    assert backend.revision == 1
    assert backend.generation == "new"


def test_stale_rest_load_returns_newer_pushed_snapshot(http):
    http["get"].append(
        ("/config", FakeResponse(200, {"old": True}, headers={"X-Nacho-Revision": "3"}))
    )
    backend = RemoteStorageBackend("http://srv")
    backend._on_message(None, json.dumps({"type": "update", "revision": 9, "data": {"new": True}}))
    assert backend.load() == {"new": True}
    assert backend.revision == 9


# ---------------------------------------------------------------------------
# headers / auth
# ---------------------------------------------------------------------------
def test_client_headers_include_bearer_token(http):
    backend = RemoteStorageBackend("http://srv", api_key="sekret")
    assert backend._client.headers()["Authorization"] == "Bearer sekret"
    assert backend._ws_headers() == {"Authorization": "Bearer sekret"}


def test_headers_omit_auth_without_key(http):
    backend = RemoteStorageBackend("http://srv")
    assert backend._client.headers() == {}
    assert backend._ws_headers() is None


def test_ws_url_derives_from_https(http):
    backend = RemoteStorageBackend("https://srv:9000")
    assert backend._ws_url == "wss://srv:9000/ws/default"


# ---------------------------------------------------------------------------
# WebSocket — receive-only callbacks
# ---------------------------------------------------------------------------
@pytest.fixture
def backend(http):
    """A connected backend with the WebSocket watcher not started."""
    return RemoteStorageBackend("http://srv", auto_connect=False)


def test_on_message_dispatches_update_to_callback(backend):
    received = []
    backend.on_remote_change = received.append
    backend._on_message(None, json.dumps({"type": "update", "data": {"x": 1}}))
    assert received == [{"x": 1}]


def test_on_message_handles_initial_config(backend):
    received = []
    backend.on_remote_change = received.append
    backend._on_message(None, json.dumps({"type": "initial_config", "data": {"y": 2}}))
    assert received == [{"y": 2}]


def test_on_message_ignores_malformed_json(backend):
    backend.on_remote_change = lambda d: pytest.fail("should not be called")
    backend._on_message(None, "{not json")  # no raise


def test_on_message_ignores_non_object(backend):
    backend.on_remote_change = lambda d: pytest.fail("should not be called")
    backend._on_message(None, json.dumps(["a", "list"]))


def test_on_message_ignores_invalid_payload(backend):
    backend.on_remote_change = lambda d: pytest.fail("should not be called")
    backend._on_message(None, json.dumps({"type": "update", "data": "not-a-dict"}))


def test_on_message_swallows_callback_errors(backend):
    def angry(_data):
        raise RuntimeError("handler blew up")

    backend.on_remote_change = angry
    backend._on_message(None, json.dumps({"type": "update", "data": {"x": 1}}))  # no raise


def test_ws_lifecycle_callbacks_are_safe(backend):
    # These only log; assert they never raise.
    backend._on_open(None)
    backend._on_error(None, RuntimeError("x"))
    backend._on_close(None, 1000, "bye")


# ---------------------------------------------------------------------------
# WebSocket — watcher thread
# ---------------------------------------------------------------------------
def test_ws_loop_runs_one_iteration(backend, monkeypatch):
    import nacho.storage.remote as remote_mod

    ping_kwargs = {}

    def fake_wsapp(url, header, on_open, on_message, on_error, on_close):
        ws = types.SimpleNamespace()

        def run_forever(**kwargs):
            ping_kwargs.update(kwargs)
            backend._running = False

        ws.run_forever = run_forever
        ws.close = lambda: None
        return ws

    monkeypatch.setattr(remote_mod.websocket, "WebSocketApp", fake_wsapp)
    backend._running = True
    backend._ws_loop()  # exits after run_forever flips _running off
    assert backend._running is False
    # Keepalive pings must be enabled so half-open connections are detected.
    assert ping_kwargs["ping_interval"] > 0
    assert ping_kwargs["ping_timeout"] > 0


def test_close_is_idempotent(backend):
    backend.close()
    backend.close()  # second call must not raise


def test_cleanup_delegates_to_close(backend):
    backend.cleanup()  # no raise; just exercises the StorageBackend hook


def test_connect_with_watch_starts_the_watcher(backend, monkeypatch):
    started = []
    monkeypatch.setattr(backend, "start_watching", lambda: started.append(True))
    backend.connect(watch=True)
    assert started == [True]


def test_start_watching_spawns_a_thread(backend, monkeypatch):
    monkeypatch.setattr(backend, "_ws_loop", lambda: None)
    backend.start_watching()
    assert backend._ws_thread is not None
    backend.start_watching()  # already running -> no second thread
    backend.close()


def test_close_shuts_down_an_active_socket(backend, monkeypatch):
    closed = []
    backend._ws = types.SimpleNamespace(close=lambda: closed.append(True))
    backend.close()
    assert closed == [True]


def test_close_joins_a_live_watcher_thread(backend, monkeypatch):
    import time

    def loop():
        while backend._running:
            time.sleep(0.01)

    monkeypatch.setattr(backend, "_ws_loop", loop)
    backend.start_watching()
    deadline = time.time() + 5
    while not backend._ws_thread.is_alive() and time.time() < deadline:
        time.sleep(0.01)
    assert backend._ws_thread.is_alive()
    backend.close()  # signals stop, then joins the thread
    assert not backend._ws_thread.is_alive()


def test_ws_loop_gives_up_after_max_reconnects(backend, monkeypatch):
    import nacho.storage.remote as remote_mod

    monkeypatch.setattr(remote_mod, "_WS_RECONNECT_DELAY", 0)
    calls = []

    def fake_wsapp(*a, **k):
        ws = types.SimpleNamespace()

        def run_forever(**kwargs):
            calls.append(1)
            if len(calls) == 1:
                raise RuntimeError("ws crashed")  # exercises the except branch

        ws.run_forever = run_forever
        ws.close = lambda: None
        return ws

    monkeypatch.setattr(remote_mod.websocket, "WebSocketApp", fake_wsapp)
    backend._reconnect = 1
    backend._running = True
    backend._ws_loop()  # crash -> reconnect -> exceed limit -> give up
    assert len(calls) >= 2
    assert backend._running is False
    assert backend.watching is False


def test_permanent_close_code_stops_reconnecting(backend):
    backend._running = True
    backend._on_close(None, 1008, "Unauthorized")
    assert backend._running is False

    backend._running = True
    backend._on_close(None, 4004, "App not found")
    assert backend._running is False


def test_transient_close_code_keeps_retrying(backend):
    backend._running = True
    backend._on_close(None, 1006, "abnormal")
    assert backend._running is True


def test_rejected_handshake_stops_reconnecting(backend):
    backend._running = True
    error = types.SimpleNamespace(status_code=401)
    backend._on_error(None, error)
    assert backend._running is False


def test_successful_open_resets_reconnect_counter(backend):
    backend._ws_attempts = 4
    backend._on_open(types.SimpleNamespace(close=lambda: None))
    assert backend._ws_attempts == 0


def test_close_interrupts_reconnect_backoff(backend, monkeypatch):
    import nacho.storage.remote as remote_mod

    monkeypatch.setattr(remote_mod, "_WS_RECONNECT_DELAY", 60)

    def fake_wsapp(*a, **k):
        ws = types.SimpleNamespace()
        ws.run_forever = lambda **kw: None  # disconnect immediately -> enter backoff
        ws.close = lambda: None
        return ws

    monkeypatch.setattr(remote_mod.websocket, "WebSocketApp", fake_wsapp)
    backend.start_watching()
    backend.close()  # must return promptly despite the 60s backoff
    assert not backend._ws_thread.is_alive()
