"""Tests for the Nacho command-line interface.

Covers the pure helpers, every ``cmd_*`` handler (local and remote paths),
the remote HTTP helpers, and ``main_cli`` dispatch. Remote calls are stubbed
so the suite needs no network or running server.
"""

import json
from argparse import Namespace

import pytest
import yaml

from nacho.cli import main as cli
from nacho.cli.main import (
    banner,
    cmd_delete,
    cmd_get,
    cmd_init,
    cmd_server,
    cmd_set,
    cmd_validate,
    create_config,
    create_parser,
    format_output,
    main_cli,
    remote_config_url,
    remote_headers,
    remote_request_error,
)


class FakeResponse:
    """Minimal stand-in for a ``requests.Response``."""

    def __init__(self, status_code=200, payload=None, headers=None, text=""):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.headers = headers or {}
        self.text = text

    def json(self):
        if self._payload is _NO_JSON:
            raise ValueError("no json")
        return self._payload


_NO_JSON = object()


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------
def test_banner_includes_version():
    from nacho._version import __version__

    text = banner()
    assert __version__ in text
    assert "NACHO" not in text  # it is ASCII art, not the literal word


def test_format_output_json_and_yaml_and_raw():
    assert json.loads(format_output({"a": 1}, "json")) == {"a": 1}
    assert yaml.safe_load(format_output({"a": 1}, "yaml")) == {"a": 1}
    assert format_output("plain", "raw") == "plain"
    # raw on a container falls back to indented JSON
    assert json.loads(format_output({"a": 1}, "raw")) == {"a": 1}


def test_remote_headers_with_and_without_key():
    assert "Authorization" not in remote_headers(None)
    assert remote_headers("k")["Authorization"] == "Bearer k"


def test_remote_config_url_builds_paths():
    assert remote_config_url("http://h:8000/", "app") == "http://h:8000/api/apps/app/config"
    assert (
        remote_config_url("http://h:8000", "app", "a.b")
        == "http://h:8000/api/apps/app/config/a.b"
    )
    # app names are percent-encoded
    assert "my%2Fsvc" in remote_config_url("http://h", "my/svc")


def test_remote_request_error_variants():
    assert remote_request_error(FakeResponse(payload={"detail": "boom"})) == "boom"
    assert "x" in remote_request_error(FakeResponse(payload={"x": 1}))
    assert remote_request_error(FakeResponse(payload=_NO_JSON, text="raw text")) == "raw text"


# ---------------------------------------------------------------------------
# create_parser
# ---------------------------------------------------------------------------
def test_create_parser_exposes_all_subcommands():
    parser = create_parser()
    assert parser.prog == "nacho"
    args = parser.parse_args(["get", "some.key", "--config", "c.yaml"])
    assert args.command == "get" and args.key == "some.key"


# ---------------------------------------------------------------------------
# create_config
# ---------------------------------------------------------------------------
def test_create_config_uses_current_nacho_api(tmp_yaml):
    config = create_config(str(tmp_yaml))
    assert config.get("database.host") == "localhost"


def test_create_config_remote_builds_remote_backend(monkeypatch):
    captured = {}

    def fake_backend(url, app_name, api_key):
        captured.update(url=url, app_name=app_name, api_key=api_key)
        return {"remote": True}  # Nacho accepts a dict storage

    monkeypatch.setattr("nacho.storage.remote.RemoteStorageBackend", fake_backend)
    config = create_config(remote_url="http://h:8000", remote_app_name="svc", api_key="k")
    assert config.get("remote") is True
    assert captured == {"url": "http://h:8000", "app_name": "svc", "api_key": "k"}


# ---------------------------------------------------------------------------
# cmd_get / cmd_set / cmd_delete — local
# ---------------------------------------------------------------------------
def test_cmd_get_reads_local_key(tmp_yaml, capsys):
    args = Namespace(config=str(tmp_yaml), key="database.host", format="raw",
                     remote=None, app_name="default", api_key=None)
    assert cmd_get(args) == 0
    assert capsys.readouterr().out.strip() == "localhost"


def test_cmd_get_reads_full_local_config(tmp_yaml, capsys):
    args = Namespace(config=str(tmp_yaml), key=None, format="json",
                     remote=None, app_name="default", api_key=None)
    assert cmd_get(args) == 0
    assert json.loads(capsys.readouterr().out)["database"]["port"] == 5432


def test_cmd_set_writes_local_config(tmp_path):
    path = tmp_path / "c.yaml"
    path.write_text("database:\n  host: localhost\n", encoding="utf-8")
    args = Namespace(config=str(path), schema=None, key="database.port", value="5432",
                     remote=None, app_name="default", api_key=None)
    assert cmd_set(args) == 0
    assert yaml.safe_load(path.read_text())["database"]["port"] == 5432


def test_cmd_set_local_schema_violation_returns_error(tmp_path, tmp_schema, capsys):
    path = tmp_path / "c.yaml"
    path.write_text("database:\n  host: localhost\n  port: 5432\n", encoding="utf-8")
    args = Namespace(config=str(path), schema=str(tmp_schema), key="database.port",
                     value="not-an-int", remote=None, app_name="default", api_key=None)
    assert cmd_set(args) == 1
    assert "Error:" in capsys.readouterr().err


def test_cmd_delete_local_found_and_missing(tmp_yaml, capsys):
    found = Namespace(config=str(tmp_yaml), schema=None, key="database.host",
                      remote=None, app_name="default", api_key=None)
    assert cmd_delete(found) == 0
    assert "Deleted" in capsys.readouterr().out

    missing = Namespace(config=str(tmp_yaml), schema=None, key="nope.gone",
                        remote=None, app_name="default", api_key=None)
    assert cmd_delete(missing) == 1
    assert "not found" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# cmd_get / cmd_set / cmd_delete — remote
# ---------------------------------------------------------------------------
def test_cmd_get_remote_shows_revision(monkeypatch, capsys):
    import requests

    monkeypatch.setattr(requests, "get", lambda *a, **k: FakeResponse(
        payload={"x": 1}, headers={"X-Nacho-Revision": "7"}))
    args = Namespace(config="c.yaml", key=None, format="json", remote="http://s",
                     app_name="svc", api_key="secret", show_revision=True)
    assert cmd_get(args) == 0
    assert '"revision": 7' in capsys.readouterr().out


def test_cmd_get_remote_error_status_returns_1(monkeypatch, capsys):
    import requests

    monkeypatch.setattr(requests, "get", lambda *a, **k: FakeResponse(
        status_code=500, payload={"detail": "kaboom"}))
    args = Namespace(config="c.yaml", key="k", format="raw", remote="http://s",
                     app_name="svc", api_key=None, show_revision=False)
    assert cmd_get(args) == 1
    assert "kaboom" in capsys.readouterr().err


def test_cmd_set_remote_sends_revision(monkeypatch, capsys):
    captured = {}
    import requests

    def fake_put(url, json, headers, timeout):
        captured.update(url=url, json=json)
        return FakeResponse(payload={"revision": 8})

    monkeypatch.setattr(requests, "put", fake_put)
    args = Namespace(config="c.yaml", schema=None, key="feature.enabled", value="true",
                     remote="http://s", app_name="svc", api_key="secret", revision=7)
    assert cmd_set(args) == 0
    assert captured["json"] == {"value": True, "type": "raw", "revision": 7}
    assert "revision 8" in capsys.readouterr().out


def test_cmd_set_remote_error_returns_1(monkeypatch, capsys):
    import requests

    monkeypatch.setattr(requests, "put", lambda *a, **k: FakeResponse(
        status_code=400, payload={"detail": "bad"}))
    args = Namespace(config="c.yaml", schema=None, key="k", value="1", remote="http://s",
                     app_name="svc", api_key=None, revision=None)
    assert cmd_set(args) == 1
    assert "bad" in capsys.readouterr().err


def test_cmd_get_remote_single_key(monkeypatch, capsys):
    import requests

    monkeypatch.setattr(requests, "get", lambda *a, **k: FakeResponse(payload={"value": 42}))
    args = Namespace(config="c.yaml", key="answer", format="raw", remote="http://s",
                     app_name="svc", api_key=None, show_revision=False)
    assert cmd_get(args) == 0
    assert capsys.readouterr().out.strip() == "42"


def test_cmd_set_remote_without_deps(monkeypatch, capsys):
    monkeypatch.setattr(cli, "HAS_REMOTE_DEPS", False)
    args = Namespace(config="c.yaml", schema=None, key="k", value="1", remote="http://s",
                     app_name="svc", api_key=None, revision=None)
    assert cmd_set(args) == 1
    assert "Remote connection requires" in capsys.readouterr().err


def test_cmd_delete_remote_without_deps(monkeypatch, capsys):
    monkeypatch.setattr(cli, "HAS_REMOTE_DEPS", False)
    args = Namespace(config="c.yaml", schema=None, key="k", remote="http://s",
                     app_name="svc", api_key=None, revision=None)
    assert cmd_delete(args) == 1
    assert "Remote connection requires" in capsys.readouterr().err


def test_cmd_delete_local_handles_exception(monkeypatch, capsys):
    def boom(*a, **k):
        raise RuntimeError("backend down")

    monkeypatch.setattr(cli, "create_config", boom)
    args = Namespace(config="c.yaml", schema=None, key="k", remote=None,
                     app_name="default", api_key=None)
    assert cmd_delete(args) == 1
    assert "Error: backend down" in capsys.readouterr().err


def test_cmd_delete_remote_success(monkeypatch, capsys):
    import requests

    monkeypatch.setattr(requests, "delete", lambda *a, **k: FakeResponse(
        payload={"revision": 4}))
    args = Namespace(config="c.yaml", schema=None, key="old", remote="http://s",
                     app_name="svc", api_key=None, revision=None)
    assert cmd_delete(args) == 0
    assert "Deleted old" in capsys.readouterr().out


def test_cmd_delete_remote_reports_conflict(monkeypatch, capsys):
    import requests

    def fake_delete(url, params, headers, timeout):
        assert params == {"revision": 2}
        return FakeResponse(status_code=409,
                            payload={"detail": {"error": "revision_conflict"}})

    monkeypatch.setattr(requests, "delete", fake_delete)
    args = Namespace(config="c.yaml", schema=None, key="old", remote="http://s",
                     app_name="svc", api_key="secret", revision=2)
    assert cmd_delete(args) == 1
    assert "revision_conflict" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# cmd_validate
# ---------------------------------------------------------------------------
def test_cmd_validate_success(tmp_yaml, tmp_schema, capsys):
    args = Namespace(config=str(tmp_yaml), schema=str(tmp_schema),
                     remote=None, app_name="default", api_key=None)
    assert cmd_validate(args) == 0
    assert "successful" in capsys.readouterr().out


def test_cmd_validate_rejects_invalid_config(tmp_path, tmp_schema, capsys):
    bad = tmp_path / "bad.yaml"
    bad.write_text("database:\n  host: localhost\n", encoding="utf-8")  # missing port
    args = Namespace(config=str(bad), schema=str(tmp_schema),
                     remote=None, app_name="default", api_key=None)
    assert cmd_validate(args) == 1
    assert "Error:" in capsys.readouterr().err


def test_cmd_validate_lists_validation_errors(monkeypatch, capsys):
    class FakeConfig:
        def validate(self):
            return ["database.port: out of range", "app.name: too short"]

    monkeypatch.setattr(cli, "create_config", lambda *a, **k: FakeConfig())
    args = Namespace(config="c.yaml", schema="s.json", remote=None,
                     app_name="default", api_key=None)
    assert cmd_validate(args) == 1
    out = capsys.readouterr().out
    assert "Validation failed" in out and "out of range" in out


def test_cmd_validate_without_schema_deps(monkeypatch, capsys):
    monkeypatch.setattr(cli, "HAS_SCHEMA_DEPS", False)
    args = Namespace(config="c.yaml", schema="s.json", remote=None,
                     app_name="default", api_key=None)
    assert cmd_validate(args) == 1
    assert "Schema validation requires" in capsys.readouterr().err


def test_cmd_validate_requires_schema_without_remote(capsys):
    args = Namespace(config="c.yaml", schema=None, remote=None,
                     app_name="default", api_key=None)
    assert cmd_validate(args) == 1
    assert "--schema is required" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# cmd_init
# ---------------------------------------------------------------------------
def test_cmd_init_creates_from_template(tmp_path, capsys):
    target = tmp_path / "new.yaml"
    assert cmd_init(Namespace(config=str(target), template="web-app")) == 0
    assert target.exists()
    assert "app" in yaml.safe_load(target.read_text())


def test_cmd_init_refuses_existing_file(tmp_yaml, capsys):
    assert cmd_init(Namespace(config=str(tmp_yaml), template="default")) == 1
    assert "already exists" in capsys.readouterr().err


def test_init_rejects_unknown_template_at_parse_time(tmp_path):
    parser = create_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["init", str(tmp_path / "x.yaml"), "--template", "bogus"])


def test_cmd_init_handles_write_error(tmp_path, monkeypatch, capsys):
    def boom(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(cli, "save_file", boom)
    assert cmd_init(Namespace(config=str(tmp_path / "y.yaml"), template="default")) == 1
    assert "Error:" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# cmd_server
# ---------------------------------------------------------------------------
class FakeOrchestrator:
    last = None

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.ran_with = None
        FakeOrchestrator.last = self

    def run(self, **kwargs):
        self.ran_with = kwargs


def _server_args(**overrides):
    base = dict(host="127.0.0.1", port=8000, config=None, schema=None, data_dir=None,
                api_key=None, app_name=None, read_only=False, reload=False)
    base.update(overrides)
    return Namespace(**base)


def test_cmd_server_runs_without_a_config(monkeypatch):
    monkeypatch.setattr(cli, "NachoOrchestrator", FakeOrchestrator)
    assert cmd_server(_server_args()) == 0
    assert FakeOrchestrator.last.ran_with["port"] == 8000


def test_cmd_server_loads_config_into_an_app(monkeypatch, tmp_yaml):
    monkeypatch.setattr(cli, "NachoOrchestrator", FakeOrchestrator)
    assert cmd_server(_server_args(config=str(tmp_yaml), app_name="svc")) == 0
    assert "svc" in FakeOrchestrator.last.kwargs["apps"]


def test_cmd_server_without_server_deps(monkeypatch, capsys):
    monkeypatch.setattr(cli, "HAS_SERVER_DEPS", False)
    assert cmd_server(_server_args()) == 1
    assert "Server features require" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# main_cli dispatch
# ---------------------------------------------------------------------------
def test_main_cli_no_command_prints_help(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["nacho"])
    assert main_cli() == 1
    assert "usage: nacho" in capsys.readouterr().out


def test_main_cli_dispatches_to_handler(monkeypatch, tmp_yaml, capsys):
    monkeypatch.setattr("sys.argv", ["nacho", "get", "database.host", "--config", str(tmp_yaml)])
    assert main_cli() == 0
    assert capsys.readouterr().out.strip() == "localhost"


def test_main_cli_init_via_argv(monkeypatch, tmp_path):
    target = tmp_path / "cfg.yaml"
    monkeypatch.setattr("sys.argv", ["nacho", "init", str(target), "--template", "empty"])
    assert main_cli() == 0
    assert target.exists()


def test_cli_package_entrypoint(monkeypatch):
    """The lazy wrapper in nacho.cli forwards to the real main_cli."""
    from nacho.cli import main_cli as pkg_main_cli

    monkeypatch.setattr("sys.argv", ["nacho"])
    assert pkg_main_cli() == 1


# ---------------------------------------------------------------------------
# cmd_apps / cmd_schema / cmd_watch
# ---------------------------------------------------------------------------
from nacho.cli.main import cmd_apps, cmd_schema, cmd_watch  # noqa: E402


def _fake_request(monkeypatch, responses):
    """Route requests.request(method, url, ...) to canned FakeResponses."""
    import requests

    calls = []

    def fake(method, url, json=None, params=None, headers=None, timeout=None):
        calls.append({"method": method, "url": url, "json": json, "params": params})
        for matcher, resp in responses:
            if url.rstrip("/").endswith(matcher):
                return resp
        return FakeResponse(200, {})

    monkeypatch.setattr(requests, "request", fake)
    return calls


def test_apps_list_human_output(monkeypatch, capsys):
    _fake_request(monkeypatch, [("/api/apps", FakeResponse(200, {"data": {
        "svc": {"revision": 3, "config_count": 2, "schema": True, "description": "core"},
        "empty": {"revision": 1, "config_count": 0, "schema": False},
    }}))])
    args = Namespace(apps_command="list", remote="http://s", api_key=None, format="raw")
    assert cmd_apps(args) == 0
    out = capsys.readouterr().out
    assert "svc" in out and "rev 3" in out and "schema" in out and "core" in out


def test_apps_list_json_output(monkeypatch, capsys):
    _fake_request(monkeypatch, [("/api/apps", FakeResponse(200, {"data": {"svc": {"revision": 1}}}))])
    args = Namespace(apps_command="list", remote="http://s", api_key=None, format="json")
    assert cmd_apps(args) == 0
    assert json.loads(capsys.readouterr().out)["svc"]["revision"] == 1


def test_apps_create_sends_schema_and_config(monkeypatch, tmp_path, capsys):
    schema_file = tmp_path / "s.json"
    schema_file.write_text('{"type": "object"}')
    config_file = tmp_path / "c.json"
    config_file.write_text('{"x": 1}')
    calls = _fake_request(monkeypatch, [("/api/apps", FakeResponse(201, {"app": {"revision": 1}}))])
    args = Namespace(apps_command="create", name="svc", remote="http://s", api_key=None,
                     description="desc", schema=str(schema_file), config=str(config_file))
    assert cmd_apps(args) == 0
    assert "Created app 'svc'" in capsys.readouterr().out
    body = calls[0]["json"]
    assert body["schema"] == {"type": "object"} and body["data"] == {"x": 1}


def test_apps_delete(monkeypatch, capsys):
    _fake_request(monkeypatch, [("/api/apps/svc", FakeResponse(200, {"message": "gone"}))])
    args = Namespace(apps_command="delete", name="svc", remote="http://s", api_key=None)
    assert cmd_apps(args) == 0
    assert "Deleted app 'svc'" in capsys.readouterr().out


def test_apps_error_goes_to_stderr(monkeypatch, capsys):
    _fake_request(monkeypatch, [("/api/apps", FakeResponse(401, {"detail": "Unauthorized"}))])
    args = Namespace(apps_command="list", remote="http://s", api_key=None, format="raw")
    assert cmd_apps(args) == 1
    assert "Unauthorized" in capsys.readouterr().err


def test_schema_get_prints_schema(monkeypatch, capsys):
    _fake_request(monkeypatch, [("/api/apps/svc/schema",
                                 FakeResponse(200, {"data": {"type": "object"}}))])
    args = Namespace(schema_command="get", remote="http://s", app_name="svc",
                     api_key=None, format="json")
    assert cmd_schema(args) == 0
    assert json.loads(capsys.readouterr().out) == {"type": "object"}


def test_schema_push_uploads_file(monkeypatch, tmp_path, capsys):
    schema_file = tmp_path / "s.json"
    schema_file.write_text('{"type": "object"}')
    calls = _fake_request(monkeypatch, [("/api/apps/svc/schema",
                                         FakeResponse(200, {"revision": 5}))])
    args = Namespace(schema_command="push", schema_file=str(schema_file), remote="http://s",
                     app_name="svc", api_key=None, revision=4)
    assert cmd_schema(args) == 0
    assert "revision 5" in capsys.readouterr().out
    assert calls[0]["json"] == {"schema": {"type": "object"}, "revision": 4}


def test_schema_push_missing_file(capsys):
    args = Namespace(schema_command="push", schema_file="/nope/s.json", remote="http://s",
                     app_name="svc", api_key=None, revision=None)
    assert cmd_schema(args) == 1
    assert "not found" in capsys.readouterr().err


def test_cmd_watch_streams_updates(monkeypatch, capsys):
    class FakeBackend:
        def __init__(self, url, app_name, api_key):
            self.on_remote_change = None

        def start_watching(self):
            self.on_remote_change({"x": 1})

        def close(self):
            pass

    monkeypatch.setattr("nacho.storage.remote.RemoteStorageBackend", FakeBackend)
    monkeypatch.setattr("threading.Event.wait",
                        lambda self, timeout=None: (_ for _ in ()).throw(KeyboardInterrupt()))
    args = Namespace(remote="http://s", app_name="svc", api_key=None)
    assert cmd_watch(args) == 0
    captured = capsys.readouterr()
    assert json.loads(captured.out.strip()) == {"x": 1}
    assert "Watching" in captured.err


def test_cmd_watch_connect_failure(monkeypatch, capsys):
    def boom(**kwargs):
        raise RuntimeError("refused")

    monkeypatch.setattr("nacho.storage.remote.RemoteStorageBackend", boom)
    args = Namespace(remote="http://s", app_name="svc", api_key=None)
    assert cmd_watch(args) == 1
    assert "refused" in capsys.readouterr().err


def test_parser_accepts_new_subcommands():
    parser = create_parser()
    a = parser.parse_args(["apps", "list", "--remote", "http://s"])
    assert a.command == "apps" and a.apps_command == "list"
    a = parser.parse_args(["schema", "push", "s.json", "--remote", "http://s"])
    assert a.command == "schema" and a.schema_file == "s.json"
    a = parser.parse_args(["watch", "--remote", "http://s", "--app-name", "svc"])
    assert a.command == "watch" and a.app_name == "svc"


def test_validate_remote_uses_server_schema(monkeypatch, tmp_yaml, capsys):
    calls = _fake_request(monkeypatch, [("/api/apps/svc/validate",
                                         FakeResponse(200, {"valid": True, "errors": []}))])
    args = Namespace(config=str(tmp_yaml), schema=None, remote="http://s",
                     app_name="svc", api_key=None)
    assert cmd_validate(args) == 0
    assert "successful" in capsys.readouterr().out
    assert calls[0]["json"]["data"]["database"]["host"] == "localhost"


def test_validate_remote_reports_errors(monkeypatch, tmp_yaml, capsys):
    _fake_request(monkeypatch, [("/api/apps/svc/validate",
                                 FakeResponse(200, {"valid": False, "errors": ["port: bad"]}))])
    args = Namespace(config=str(tmp_yaml), schema=None, remote="http://s",
                     app_name="svc", api_key=None)
    assert cmd_validate(args) == 1
    assert "port: bad" in capsys.readouterr().out
