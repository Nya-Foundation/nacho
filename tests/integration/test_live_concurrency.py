"""Integration tests: optimistic concurrency, auth variants, and formats
over a real server subprocess.

The unit suite exercises these paths through TestClient; these tests prove
the same contracts hold over a real HTTP/WS transport — most importantly
that the revision mechanism actually prevents lost updates under real
concurrency, which is the one scenario in-process tests cannot reproduce.
"""

import threading

import pytest
import websocket

from nacho import Nacho
from nacho.client import NachoClient
from nacho.storage.base import AuthError, ConflictError
from nacho.storage.remote import RemoteStorageBackend

WAIT = 15.0


# ---------------------------------------------------------------------------
# Optimistic concurrency over a real transport
# ---------------------------------------------------------------------------
def test_stale_revision_write_conflicts_live(live_server):
    client_a = NachoClient(live_server)
    client_b = NachoClient(live_server)

    client_a.put_config({"counter": 0})
    _, rev_a = client_a.get_config()

    client_b.put_config({"counter": 100}, revision=rev_a)  # B wins the race

    with pytest.raises(ConflictError) as excinfo:
        client_a.put_config({"counter": 1}, revision=rev_a)  # A is now stale
    assert excinfo.value.expected == rev_a
    assert excinfo.value.actual == rev_a + 1

    data, _ = client_a.get_config()
    assert data == {"counter": 100}  # the conflicting write did not land


def test_concurrent_writers_lose_no_updates(live_server):
    """N threads increment one counter with revision-checked read-modify-write.

    Every 409 forces a re-read and retry, so the final counter must equal
    the total number of increments — the exact guarantee the revision
    mechanism exists to provide.
    """
    writers, increments = 4, 5
    NachoClient(live_server).put_config({"counter": 0})
    errors = []

    def work():
        client = NachoClient(live_server)
        try:
            for _ in range(increments):
                while True:
                    data, rev = client.get_config()
                    try:
                        client.put_config({"counter": data["counter"] + 1}, revision=rev)
                        break
                    except ConflictError:
                        continue  # somebody else won; re-read and retry
        except Exception as exc:  # pragma: no cover - surfaced via assert below
            errors.append(exc)

    threads = [threading.Thread(target=work) for _ in range(writers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=WAIT * 4)
    assert not errors
    data, _ = NachoClient(live_server).get_config()
    assert data["counter"] == writers * increments


def test_sdk_save_conflict_and_recovery_live(live_server):
    """Two SDK instances: the loser gets a ConflictError, reloads, and wins."""
    a = Nacho(storage=RemoteStorageBackend(live_server))
    b = Nacho(storage=RemoteStorageBackend(live_server))

    a.set("from_a", 1)
    a.save()
    b.set("from_b", 2)
    with pytest.raises(ConflictError):
        b.save()  # b's snapshot predates a's save

    b.load()
    b.set("from_b", 2)
    b.save()

    merged = Nacho(storage=RemoteStorageBackend(live_server)).get_all()
    assert merged["from_a"] == 1 and merged["from_b"] == 2


# ---------------------------------------------------------------------------
# Auth variants over a real transport
# ---------------------------------------------------------------------------
def test_wrong_api_key_rejected_live(make_live_server):
    server = make_live_server(api_key="right-key")

    with pytest.raises(AuthError):
        RemoteStorageBackend(server.url, api_key="wrong-key")

    with pytest.raises(AuthError):
        NachoClient(server.url, api_key="wrong-key").get_config()

    data, _ = NachoClient(server.url, api_key="right-key").get_config()
    assert data == {}


def test_cookie_auth_over_real_transport(make_live_server):
    server = make_live_server(api_key="sekret")

    # REST: the UI authenticates through this cookie, not the bearer header.
    import requests

    resp = requests.get(
        server.url + "/api/apps/default/config",
        cookies={"NACHO_api_key": "sekret"},
        timeout=5,
    )
    assert resp.status_code == 200

    resp = requests.get(
        server.url + "/api/apps/default/config",
        cookies={"NACHO_api_key": "wrong"},
        timeout=5,
    )
    assert resp.status_code == 401

    # WS handshake with the session cookie (how the browser connects).
    ws_url = server.url.replace("http://", "ws://") + "/ws/default"
    conn = websocket.create_connection(ws_url, cookie="NACHO_api_key=sekret", timeout=5)
    try:
        assert '"initial_config"' in conn.recv()
    finally:
        conn.close()

    with pytest.raises(Exception):
        conn = websocket.create_connection(ws_url, cookie="NACHO_api_key=wrong", timeout=5)
        conn.recv()  # server closes 1008 before sending anything


# ---------------------------------------------------------------------------
# Formats and read-only mode over a real transport
# ---------------------------------------------------------------------------
def test_yaml_and_toml_round_trip_live(live_server):
    client = NachoClient(live_server)

    client.put_config("database:\n  host: db.example.com\n  port: 5432\n", fmt="yaml")
    data, _ = client.get_config()
    assert data == {"database": {"host": "db.example.com", "port": 5432}}

    converted = client.convert(data, from_fmt="json", to_fmt="toml")
    assert "[database]" in converted["data"]

    client.put_config(converted["data"], fmt="toml")
    round_tripped, _ = client.get_config()
    assert round_tripped == data


def test_read_only_server_rejects_writes_live(make_live_server):
    server = make_live_server(extra_args=["--read-only"])
    client = NachoClient(server.url)

    data, _ = client.get_config()
    assert data == {}

    with pytest.raises(AuthError, match="read-only"):
        client.put_config({"x": 1})

    data, _ = client.get_config()
    assert data == {}
