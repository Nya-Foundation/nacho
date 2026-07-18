"""End-to-end tests: the ``nacho`` CLI driving a live server.

Marked ``e2e`` (skipped by default). These exercise the full stack — the CLI
binary, the HTTP client, and a real server process — exactly as a user would.
"""

import json
import os
import queue
import shutil
import subprocess
import threading
import urllib.request

import pytest

nacho_bin = shutil.which("nacho")
if nacho_bin is None and os.environ.get("CI"):
    # In CI a missing binary means a broken install, not an optional suite —
    # fail loudly instead of silently collecting zero e2e tests.
    raise RuntimeError("nacho CLI not on PATH in CI — the editable install is broken")
pytestmark = pytest.mark.skipif(nacho_bin is None, reason="nacho CLI not on PATH")


def _run(*args):
    return subprocess.run([nacho_bin, *args], capture_output=True, text=True, timeout=30)


def test_cli_set_get_against_live_server(live_server):
    """`nacho set` then `nacho get --remote` round-trips a typed value."""
    set_result = _run(
        "set",
        "feature.enabled",
        "true",
        "--remote",
        live_server,
        "--app-name",
        "default",
    )
    assert set_result.returncode == 0, set_result.stderr

    get_result = _run(
        "get",
        "--format",
        "json",
        "--remote",
        live_server,
        "--app-name",
        "default",
    )
    assert get_result.returncode == 0, get_result.stderr
    assert json.loads(get_result.stdout) == {"feature": {"enabled": True}}


def test_cli_app_and_schema_lifecycle(live_server, tmp_path):
    """apps create → schema push → invalid write refused → validate --remote."""
    schema_file = tmp_path / "schema.json"
    schema_file.write_text(
        json.dumps(
            {
                "type": "object",
                "properties": {"port": {"type": "integer"}},
                "required": ["port"],
            }
        )
    )
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps({"port": 8080}))

    created = _run(
        "apps",
        "create",
        "svc",
        "--remote",
        live_server,
        "--config",
        str(config_file),
        "--schema",
        str(schema_file),
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
        "validate",
        "--config",
        str(config_file),
        "--remote",
        live_server,
        "--app-name",
        "svc",
    )
    assert valid.returncode == 0, valid.stderr
    assert "successful" in valid.stdout

    bad_file = tmp_path / "bad.json"
    bad_file.write_text(json.dumps({"port": "nope"}))
    invalid = _run(
        "validate",
        "--config",
        str(bad_file),
        "--remote",
        live_server,
        "--app-name",
        "svc",
    )
    assert invalid.returncode == 1
    assert "port" in invalid.stdout

    deleted = _run("apps", "delete", "svc", "--remote", live_server)
    assert deleted.returncode == 0, deleted.stderr


def test_cli_auth_flow(make_live_server):
    """--api-key is required and sufficient against an auth-enabled server."""
    server = make_live_server(api_key="sekret")

    denied = _run("get", "--remote", server.url, "--app-name", "default")
    assert denied.returncode == 5  # dedicated auth-failure exit code
    assert "Unauthorized" in denied.stderr

    allowed = _run(
        "set",
        "answer",
        "42",
        "--remote",
        server.url,
        "--app-name",
        "default",
        "--api-key",
        "sekret",
    )
    assert allowed.returncode == 0, allowed.stderr

    fetched = _run(
        "get",
        "answer",
        "--format",
        "json",
        "--remote",
        server.url,
        "--app-name",
        "default",
        "--api-key",
        "sekret",
    )
    assert fetched.returncode == 0, fetched.stderr
    assert json.loads(fetched.stdout) == 42


def test_cli_wrong_api_key_is_rejected(make_live_server):
    """There is one key; anything else fails, for reads and writes alike."""
    server = make_live_server(api_key="sekret")

    seeded = _run(
        "set",
        "answer",
        "42",
        "--remote",
        server.url,
        "--app-name",
        "default",
        "--api-key",
        "sekret",
    )
    assert seeded.returncode == 0, seeded.stderr

    for command in (("get", "answer"), ("set", "answer", "43")):
        denied = _run(
            *command,
            "--remote",
            server.url,
            "--app-name",
            "default",
            "--api-key",
            "not-sekret",
        )
        assert denied.returncode == 5, denied.stderr  # auth-failure exit code


def test_cli_history_diff_flow(live_server):
    """`history diff` renders the change between a revision and the present."""
    for value in ("one", "two"):
        result = _run("set", "release", value, "--remote", live_server, "--app-name", "default")
        assert result.returncode == 0, result.stderr

    listed = _run(
        "history",
        "list",
        "--format",
        "json",
        "--remote",
        live_server,
        "--app-name",
        "default",
    )
    assert listed.returncode == 0, listed.stderr
    base = json.loads(listed.stdout)[1]["revision"]  # the "one" snapshot

    diffed = _run("history", "diff", str(base), "--remote", live_server, "--app-name", "default")
    assert diffed.returncode == 0, diffed.stderr
    assert '-  "release": "one"' in diffed.stdout
    assert '+  "release": "two"' in diffed.stdout


def test_cli_watch_streams_live_updates(live_server):
    """`nacho watch` prints the current config, then each pushed update.

    This is the only place the watch command runs against a real WebSocket;
    its unit tests substitute a fake backend.
    """
    proc = subprocess.Popen(
        [nacho_bin, "watch", "--remote", live_server, "--app-name", "default"],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    lines = queue.Queue()

    def pump():
        for line in proc.stdout:
            lines.put(line)

    threading.Thread(target=pump, daemon=True).start()
    try:
        # First line is the initial config — its arrival also proves the
        # subscription is live, so the write below cannot race the connect.
        assert json.loads(lines.get(timeout=15)) == {}

        request = urllib.request.Request(
            live_server + "/api/apps/default/config",
            data=json.dumps({"data": {"live": "yes"}}).encode(),
            method="PUT",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=5):
            pass

        assert json.loads(lines.get(timeout=15)) == {"live": "yes"}
    finally:
        proc.terminate()
        proc.wait(timeout=10)


def test_cli_history_and_rollback_flow(live_server):
    """set twice, inspect history, roll back, and read the restored value."""
    for value in ("one", "two"):
        result = _run(
            "set",
            "release",
            value,
            "--remote",
            live_server,
            "--app-name",
            "default",
        )
        assert result.returncode == 0, result.stderr

    listed = _run(
        "history",
        "list",
        "--format",
        "json",
        "--remote",
        live_server,
        "--app-name",
        "default",
    )
    assert listed.returncode == 0, listed.stderr
    entries = json.loads(listed.stdout)
    assert len(entries) >= 2
    target = entries[1]["revision"]  # the "one" snapshot

    shown = _run(
        "history",
        "show",
        str(target),
        "--format",
        "json",
        "--remote",
        live_server,
        "--app-name",
        "default",
    )
    assert shown.returncode == 0, shown.stderr
    assert json.loads(shown.stdout)["config"] == {"release": "one"}

    rolled = _run(
        "rollback",
        str(target),
        "--remote",
        live_server,
        "--app-name",
        "default",
        "--revision-check",
        str(entries[0]["revision"]),
    )
    assert rolled.returncode == 0, rolled.stderr

    fetched = _run(
        "get",
        "release",
        "--format",
        "json",
        "--remote",
        live_server,
        "--app-name",
        "default",
    )
    assert fetched.returncode == 0, fetched.stderr
    assert json.loads(fetched.stdout) == "one"


def test_config_seed_and_data_dir_keep_revision_monotonic_across_restart(
    make_live_server, tmp_path
):
    """The documented --config + --data-dir combination must never rewind revisions."""
    config = tmp_path / "service.yaml"
    config.write_text("value: one\n")
    data_dir = tmp_path / "durable"
    args = ("--config", str(config), "--app-name", "svc")
    first = make_live_server(data_dir=data_dir, extra_args=args)

    changed = _run(
        "set",
        "value",
        "two",
        "--remote",
        first.url,
        "--app-name",
        "svc",
        "--revision",
        "1",
    )
    assert changed.returncode == 0, changed.stderr
    first.stop()

    second = make_live_server(port=first.port, data_dir=data_dir, extra_args=args)
    shown = _run(
        "get",
        "--show-revision",
        "--remote",
        second.url,
        "--app-name",
        "svc",
    )
    assert shown.returncode == 0, shown.stderr
    body = json.loads(shown.stdout)
    assert body == {"revision": 2, "data": {"value": "two"}}

    history = _run("history", "list", "--remote", second.url, "--app-name", "svc")
    assert [entry["revision"] for entry in json.loads(history.stdout)] == [2, 1]
