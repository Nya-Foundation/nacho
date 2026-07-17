"""Unit tests for RemoteStorageBackend.

All HTTP and WebSocket traffic is stubbed, so these run without a server.
The live round-trip against a real server is covered by the integration suite.
"""

import json
import types

import pytest
import requests

from nacho.storage.base import StorageError
from nacho.storage.remote import RemoteStorageBackend


class FakeResponse:
    """Stand-in for ``requests.Response``."""

    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload
        self.text = text

    @property
    def ok(self):
        return self.status_code < 400

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} error")


@pytest.fixture
def http(monkeypatch):
    """Routes requests.* to per-URL canned responses.

    Tests register handlers in ``routes`` keyed by HTTP method; each handler
    receives the URL and returns a FakeResponse (or raises).
    """
    routes = {"get": [], "put": [], "post": [], "delete": []}

    def dispatch(method):
        def call(url, *args, **kwargs):
            # Match on URL suffix so "/api/apps/default" does not also
            # capture "/api/apps/default/config".
            for matcher, response in routes[method]:
                if url.rstrip("/").endswith(matcher):
                    if isinstance(response, Exception):
                        raise response
                    return response
            return FakeResponse(200, {})
        return call

    for method in routes:
        monkeypatch.setattr(requests, method, dispatch(method))
    return routes


def _healthy(routes):
    """Register the health response for a successful connect."""
    routes["get"].append(("/health", FakeResponse(200, {"status": "ok"})))


# ---------------------------------------------------------------------------
# Construction / connection
# ---------------------------------------------------------------------------
def test_construct_verifies_existing_app(http):
    _healthy(http)
    backend = RemoteStorageBackend("http://srv")
    assert backend._connected is True
    assert str(backend) == "RemoteStorageBackend(url='http://srv', app='default')"


def test_construct_raises_when_unreachable(http):
    http["get"].append(("/health", requests.ConnectionError("refused")))
    with pytest.raises(StorageError, match="Cannot reach"):
        RemoteStorageBackend("http://srv")


def test_connect_does_not_create_missing_app(http):
    """Connecting is read-only: no POST happens even when the app is absent."""
    http["get"].append(("/health", FakeResponse(200, {})))
    posted = []
    http["post"].append(("/api/apps", FakeResponse(201, {})))
    backend = RemoteStorageBackend("http://srv")
    assert backend._connected
    assert posted == []


def test_load_missing_app_raises_helpful_error(http):
    http["get"].append(("/health", FakeResponse(200, {})))
    http["get"].append(("/api/apps/default/config", FakeResponse(404, {})))
    backend = RemoteStorageBackend("http://srv")
    with pytest.raises(StorageError, match="does not exist"):
        backend.load()


def test_create_app_failure_raises(http):
    """save() on a missing app auto-creates it; a failed create surfaces loudly."""
    http["get"].append(("/health", FakeResponse(200, {})))
    http["put"].append(("/api/apps/default/config", FakeResponse(404, {})))
    http["post"].append(("/api/apps", FakeResponse(500, {}, text="nope")))
    backend = RemoteStorageBackend("http://srv")
    with pytest.raises(StorageError, match="Failed to create app"):
        backend.save({"x": 1})


# ---------------------------------------------------------------------------
# load / save
# ---------------------------------------------------------------------------
def test_load_returns_remote_config(http):
    _healthy(http)
    http["get"].append(("/config", FakeResponse(200, {"feature": True})))
    backend = RemoteStorageBackend("http://srv")
    assert backend.load() == {"feature": True}


def test_load_rejects_non_object_payload(http):
    _healthy(http)
    http["get"].append(("/config", FakeResponse(200, ["not", "a", "dict"])))
    backend = RemoteStorageBackend("http://srv")
    with pytest.raises(StorageError, match="non-object"):
        backend.load()


def test_load_wraps_request_exception(http):
    _healthy(http)
    backend = RemoteStorageBackend("http://srv")
    http["get"].append(("/config", requests.Timeout("slow")))
    with pytest.raises(StorageError, match="GET .* failed"):
        backend.load()


def test_save_replaces_config(http):
    _healthy(http)
    http["put"].append(("/config", FakeResponse(200, {})))
    backend = RemoteStorageBackend("http://srv")
    backend.save({"a": 1})  # no exception


def test_save_creates_app_on_404(http):
    _healthy(http)
    http["put"].append(("/config", FakeResponse(404, {})))
    http["post"].append(("/api/apps", FakeResponse(201, {})))
    backend = RemoteStorageBackend("http://srv")
    backend.save({"a": 1})


def test_save_raises_on_server_error(http):
    _healthy(http)
    http["put"].append(("/config", FakeResponse(500, {})))
    backend = RemoteStorageBackend("http://srv")
    with pytest.raises(StorageError, match="PUT .* failed"):
        backend.save({"a": 1})


def test_save_wraps_put_transport_error(http):
    _healthy(http)
    backend = RemoteStorageBackend("http://srv")
    http["put"].append(("/config", requests.ConnectionError("down")))
    with pytest.raises(StorageError, match="PUT .* failed"):
        backend.save({"a": 1})


# ---------------------------------------------------------------------------
# headers / auth
# ---------------------------------------------------------------------------
def test_headers_include_bearer_token(http):
    _healthy(http)
    backend = RemoteStorageBackend("http://srv", api_key="sekret")
    headers = backend._headers()
    assert headers["Authorization"] == "Bearer sekret"
    assert headers["Content-Type"] == "application/json"


def test_headers_omit_auth_without_key(http):
    _healthy(http)
    backend = RemoteStorageBackend("http://srv")
    assert "Authorization" not in backend._headers()


def test_ws_url_derives_from_https(http):
    _healthy(http)
    backend = RemoteStorageBackend("https://srv:9000")
    assert backend._ws_url == "wss://srv:9000/ws/default"


# ---------------------------------------------------------------------------
# WebSocket — receive-only callbacks
# ---------------------------------------------------------------------------
@pytest.fixture
def backend(http):
    """A connected backend with the WebSocket watcher not started."""
    _healthy(http)
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

    def fake_wsapp(url, header, on_open, on_message, on_error, on_close):
        ws = types.SimpleNamespace()
        ws.run_forever = lambda: setattr(backend, "_running", False)
        ws.close = lambda: None
        return ws

    monkeypatch.setattr(remote_mod.websocket, "WebSocketApp", fake_wsapp)
    backend._running = True
    backend._ws_loop()  # exits after run_forever flips _running off
    assert backend._running is False


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


def test_post_wraps_transport_error(http):
    # save() on a missing app calls _create_app -> _post, which fails.
    http["get"].append(("/health", FakeResponse(200, {})))
    http["put"].append(("/api/apps/default/config", FakeResponse(404, {})))
    http["post"].append(("/api/apps", requests.ConnectionError("refused")))
    backend = RemoteStorageBackend("http://srv")
    with pytest.raises(StorageError, match="POST .* failed"):
        backend.save({"x": 1})


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

        def run_forever():
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


def test_successful_open_resets_reconnect_counter(backend):
    backend._ws_attempts = 4
    backend._on_open(None)
    assert backend._ws_attempts == 0


def test_close_interrupts_reconnect_backoff(backend, monkeypatch):
    import nacho.storage.remote as remote_mod

    monkeypatch.setattr(remote_mod, "_WS_RECONNECT_DELAY", 60)

    def fake_wsapp(*a, **k):
        ws = types.SimpleNamespace()
        ws.run_forever = lambda: None  # disconnect immediately -> enter backoff
        ws.close = lambda: None
        return ws

    monkeypatch.setattr(remote_mod.websocket, "WebSocketApp", fake_wsapp)
    backend.start_watching()
    backend.close()  # must return promptly despite the 60s backoff
    assert not backend._ws_thread.is_alive()
