"""Integration tests: real WebSocket push, reconnect, auth, and schema flows.

These join the two halves of the WS contract — the server's broadcast and the
client's ``websocket-client`` watcher — over a real network connection, which
unit tests (TestClient + mocked WebSocketApp) cannot do.
"""

import json
import threading
import time
import urllib.error
import urllib.request

import pytest

import nacho.storage.remote as remote_mod
from nacho import Nacho
from nacho.storage.remote import RemoteStorageBackend

WAIT = 15.0  # generous cap; events fire in milliseconds when things work


def _http_json(method, url, payload=None, api_key=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    if api_key:
        req.add_header("Authorization", f"Bearer {api_key}")
    with urllib.request.urlopen(req, timeout=5) as resp:
        body = resp.read().decode()
        return resp.status, (json.loads(body) if body else None)


class Recorder:
    """Collects on_remote_change payloads and lets tests await a predicate."""

    def __init__(self):
        self._payloads = []
        self._cond = threading.Condition()

    def __call__(self, data):
        with self._cond:
            self._payloads.append(data)
            self._cond.notify_all()

    def wait_for(self, predicate, timeout=WAIT):
        with self._cond:
            ok = self._cond.wait_for(
                lambda: any(predicate(p) for p in self._payloads), timeout=timeout
            )
            assert ok, f"no matching payload within {timeout}s; got: {self._payloads}"


def _watching_backend(url, app_name="default", api_key=None):
    backend = RemoteStorageBackend(url=url, app_name=app_name, api_key=api_key)
    recorder = Recorder()
    backend.on_remote_change = recorder
    backend.start_watching()
    # The server sends initial_config on subscribe — once it arrives we know
    # the WS is live, so later asserts are race-free without sleeps.
    recorder.wait_for(lambda p: isinstance(p, dict))
    return backend, recorder


def test_ws_live_update_reaches_subscribed_client(live_server):
    """A REST write by one client is pushed live to another client's watcher."""
    backend, recorder = _watching_backend(live_server)
    try:
        status, _ = _http_json(
            "PUT",
            live_server + "/api/apps/default/config",
            {"data": {"feature": "on"}},
        )
        assert status == 200
        recorder.wait_for(lambda p: p.get("feature") == "on")
    finally:
        backend.close()


def test_ws_update_fans_out_to_all_subscribers(live_server):
    """One REST write reaches every connected watcher, not just one.

    The server-side broadcast loop is otherwise only ever exercised with a
    single subscriber, so a fan-out regression (e.g. the first send error
    aborting the loop) would go unnoticed without this.
    """
    watchers = [_watching_backend(live_server) for _ in range(3)]
    try:
        status, _ = _http_json(
            "PUT",
            live_server + "/api/apps/default/config",
            {"data": {"fanout": "yes"}},
        )
        assert status == 200
        for _, recorder in watchers:
            recorder.wait_for(lambda p: p.get("fanout") == "yes")
    finally:
        for backend, _ in watchers:
            backend.close()


def test_ws_watcher_survives_server_restart(make_live_server, monkeypatch):
    """The watcher reconnects after a restart and receives post-restart pushes."""
    monkeypatch.setattr(remote_mod, "_WS_RECONNECT_DELAY", 0.2)
    server = make_live_server()
    backend, recorder = _watching_backend(server.url)
    try:
        server.stop()
        make_live_server(port=server.port, data_dir=server.data_dir)

        # Poll the write until the watcher has resubscribed and sees it: the
        # exact reconnect moment is unobservable from outside, so retry writes.
        deadline = threading.Event()

        def keep_writing():
            i = 0
            while not deadline.is_set():
                i += 1
                try:
                    _http_json(
                        "PUT",
                        server.url + "/api/apps/default/config",
                        {"data": {"generation": i}},
                    )
                except urllib.error.URLError:
                    pass
                deadline.wait(0.3)

        writer = threading.Thread(target=keep_writing, daemon=True)
        writer.start()
        try:
            recorder.wait_for(lambda p: "generation" in p)
        finally:
            deadline.set()
            writer.join(timeout=5)
    finally:
        backend.close()


def test_public_sdk_adopts_lower_revision_from_new_server_generation(
    make_live_server, monkeypatch, tmp_path
):
    """The README-level SDK flow recovers when an ephemeral server restarts at r1."""
    monkeypatch.setattr(remote_mod, "_WS_RECONNECT_DELAY", 0.2)
    server = make_live_server(data_dir=tmp_path / "old-state")
    _http_json("PUT", server.url + "/api/apps/default/config", {"data": {"old": 1}})
    _http_json("PUT", server.url + "/api/apps/default/config", {"data": {"old": 2}})

    backend = RemoteStorageBackend(server.url, watch=True)
    config = Nacho(storage=backend, events=True)
    changed = threading.Event()

    @config.on_change("@global")
    def record_change(**_):
        changed.set()

    try:
        assert config.get_all() == {"old": 2}
        old_generation = backend.generation
        assert backend.revision == 3

        server.stop()
        make_live_server(port=server.port, data_dir=tmp_path / "new-state")

        deadline = time.monotonic() + WAIT
        while time.monotonic() < deadline and config.get_all() != {}:
            changed.wait(0.5)
            changed.clear()
        assert config.get_all() == {}
        assert backend.revision == 1
        assert backend.generation != old_generation

        _http_json("PUT", server.url + "/api/apps/default/config", {"data": {"fresh": True}})
        deadline = time.monotonic() + WAIT
        while time.monotonic() < deadline and config.get("fresh") is not True:
            changed.wait(0.5)
            changed.clear()
        assert config.get("fresh") is True
        assert backend.watching
        assert backend.last_watch_error is None
    finally:
        config.cleanup()


def test_auth_enforced_over_real_transport(make_live_server):
    """REST and WS both honour the API key on a live server."""
    server = make_live_server(api_key="sekret")

    with pytest.raises(urllib.error.HTTPError) as exc:
        _http_json("GET", server.url + "/api/apps/default/config")
    assert exc.value.code == 401

    status, body = _http_json("GET", server.url + "/api/apps/default/config", api_key="sekret")
    assert status == 200 and body == {}

    # The WS handshake carries the bearer header and receives live pushes.
    backend, recorder = _watching_backend(server.url, api_key="sekret")
    try:
        _http_json(
            "PUT",
            server.url + "/api/apps/default/config",
            {"data": {"secured": True}},
            api_key="sekret",
        )
        recorder.wait_for(lambda p: p.get("secured") is True)
    finally:
        backend.close()


def test_schema_rejects_invalid_write_on_live_server(live_server):
    """A schema-violating write is refused by a real server with a 400."""
    schema = {
        "type": "object",
        "properties": {"port": {"type": "integer"}},
        "required": ["port"],
    }
    status, _ = _http_json(
        "POST",
        live_server + "/api/apps",
        {"name": "svc", "data": {"port": 80}, "schema": schema},
    )
    assert status == 201

    with pytest.raises(urllib.error.HTTPError) as exc:
        _http_json(
            "PUT",
            live_server + "/api/apps/svc/config",
            {"data": {"port": "not-an-int"}},
        )
    assert exc.value.code == 400

    status, body = _http_json("GET", live_server + "/api/apps/svc/config")
    assert status == 200 and body == {"port": 80}


def test_rollback_on_live_server_reaches_watcher(live_server):
    """A rollback is a write like any other: watchers see the restored config."""
    status, _ = _http_json(
        "PUT", live_server + "/api/apps/default/config", {"data": {"stage": "v1"}}
    )
    assert status == 200
    status, _ = _http_json(
        "PUT", live_server + "/api/apps/default/config", {"data": {"stage": "v2"}}
    )
    assert status == 200

    backend, recorder = _watching_backend(live_server)
    try:
        status, body = _http_json("GET", live_server + "/api/apps/default/history")
        assert status == 200
        revisions = [e["revision"] for e in body["data"]]
        target = revisions[-2]  # the {"stage": "v1"} snapshot

        status, body = _http_json(
            "POST", live_server + "/api/apps/default/rollback", {"revision": target}
        )
        assert status == 200
        recorder.wait_for(lambda p: p.get("stage") == "v1")
    finally:
        backend.close()
