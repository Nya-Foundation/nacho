"""Tests for the Nacho command-line interface.

Behavior is exercised through ``main_cli([...])`` invocations — the same
surface users hit — plus the pure helpers. Remote calls are routed through
a stubbed ``requests.request`` (the transport NachoClient uses), so the
suite needs no network or running server.
"""

import json

import pytest
import requests
import yaml

from nacho.cli import main as cli
from nacho.cli.main import (
    EXIT_AUTH,
    EXIT_CONFLICT,
    EXIT_ERROR,
    EXIT_NOT_FOUND,
    EXIT_OK,
    banner,
    coerce_value,
    create_parser,
    is_loopback_host,
    main_cli,
    render,
)


class FakeResponse:
    """Minimal stand-in for a ``requests.Response``."""

    def __init__(self, status_code=200, payload=None, headers=None, text=""):
        self.status_code = status_code
        self._payload = payload
        self.headers = headers or {}
        self.text = text
        self.reason = "Fake Reason"

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
        # Match on URL suffix so "/api/apps/svc" does not also
        # capture "/api/apps/svc/config".
        for matcher, response in routes[method.lower()]:
            if url.rstrip("/").endswith(matcher):
                if isinstance(response, Exception):
                    raise response
                return response
        return FakeResponse(200, {})

    monkeypatch.setattr(requests, "request", dispatch)
    return routes


REMOTE = ["--remote", "http://s", "--app-name", "svc"]


def _json_bodies(routes, method):
    return [kw.get("json") for m, _, kw in routes["calls"] if m == method]


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------
def test_banner_includes_version():
    from nacho._version import __version__

    text = banner()
    assert __version__ in text
    assert "NACHO" not in text  # it is ASCII art, not the literal word


def test_render_json_yaml_toml():
    assert json.loads(render({"a": 1}, "json")) == {"a": 1}
    assert yaml.safe_load(render({"a": 1}, "yaml")) == {"a": 1}
    assert "[a]" in render({"a": {"b": 1}}, "toml")
    assert json.loads(render("plain", "json")) == "plain"


def test_coerce_value_auto_keeps_best_effort_typing():
    assert coerce_value("8080", "auto") == 8080
    assert coerce_value("true", "auto") is True
    assert coerce_value("'8080'", "auto") == "8080"  # quoting escape hatch


def test_coerce_value_explicit_types():
    assert coerce_value("8080", "str") == "8080"
    assert coerce_value("42", "int") == 42
    assert coerce_value("1.5", "float") == 1.5
    assert coerce_value("yes", "bool") is True
    assert coerce_value("0", "bool") is False
    assert coerce_value('{"a": [1, 2]}', "json") == {"a": [1, 2]}


@pytest.mark.parametrize(
    "value,kind", [("nope", "int"), ("nope", "float"), ("maybe", "bool"), ("{not json", "json")]
)
def test_coerce_value_rejects_unparseable(value, kind):
    with pytest.raises(ValueError):
        coerce_value(value, kind)


def test_is_loopback_host():
    assert is_loopback_host("127.0.0.1")
    assert is_loopback_host("127.0.0.5")
    assert is_loopback_host("localhost")
    assert is_loopback_host("::1")
    assert not is_loopback_host("0.0.0.0")
    assert not is_loopback_host("192.168.1.5")
    assert not is_loopback_host("example.com")


# ---------------------------------------------------------------------------
# Parser / entry point
# ---------------------------------------------------------------------------
def test_bare_nacho_prints_help_and_exits_ok(capsys):
    assert main_cli([]) == EXIT_OK
    assert "usage: nacho" in capsys.readouterr().out


def test_unknown_command_is_a_usage_error():
    with pytest.raises(SystemExit) as excinfo:
        main_cli(["frobnicate"])
    assert excinfo.value.code == 2


def test_init_rejects_unknown_template_at_parse_time(tmp_path):
    with pytest.raises(SystemExit) as excinfo:
        main_cli(["init", str(tmp_path / "x.yaml"), "--template", "bogus"])
    assert excinfo.value.code == 2


def test_apps_list_requires_remote():
    with pytest.raises(SystemExit) as excinfo:
        main_cli(["apps", "list"])
    assert excinfo.value.code == 2


def test_debug_flag_works_before_and_after_the_subcommand():
    parser = create_parser()
    assert parser.parse_args(["--debug", "get", "k"]).debug is True
    assert parser.parse_args(["get", "k", "--debug"]).debug is True
    assert parser.parse_args(["get", "k"]).debug is False


def test_parser_accepts_new_subcommands():
    parser = create_parser()
    a = parser.parse_args(["apps", "show", *REMOTE])
    assert a.apps_command == "show" and a.app_name == "svc"
    a = parser.parse_args(["apps", "rename", "new", *REMOTE, "--revision", "3"])
    assert a.new_name == "new" and a.revision == 3
    a = parser.parse_args(["apps", "describe", "core service", *REMOTE])
    assert a.text == "core service"
    a = parser.parse_args(["set", "k", "v", "--type", "json"])
    assert a.type == "json"


def test_cli_package_reexports_entry_point(capsys):
    from nacho.cli import main_cli as pkg_main_cli

    assert pkg_main_cli([]) == EXIT_OK
    assert "usage: nacho" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# get / set / delete — local
# ---------------------------------------------------------------------------
def test_get_local_key(tmp_yaml, capsys):
    assert main_cli(["get", "database.host", "--config", str(tmp_yaml)]) == EXIT_OK
    assert json.loads(capsys.readouterr().out) == "localhost"


def test_get_local_full_config_and_yaml_format(tmp_yaml, capsys):
    assert main_cli(["get", "--config", str(tmp_yaml)]) == EXIT_OK
    assert json.loads(capsys.readouterr().out)["database"]["port"] == 5432

    assert main_cli(["get", "--config", str(tmp_yaml), "--format", "yaml"]) == EXIT_OK
    assert yaml.safe_load(capsys.readouterr().out)["database"]["port"] == 5432


def test_get_local_missing_key_exits_not_found(tmp_yaml, capsys):
    assert main_cli(["get", "no.such.key", "--config", str(tmp_yaml)]) == EXIT_NOT_FOUND
    assert "not found" in capsys.readouterr().err


def test_set_local_writes_with_auto_typing(tmp_path):
    path = tmp_path / "c.yaml"
    path.write_text("database:\n  host: localhost\n", encoding="utf-8")
    assert main_cli(["set", "database.port", "5432", "--config", str(path)]) == EXIT_OK
    assert yaml.safe_load(path.read_text())["database"]["port"] == 5432


def test_set_local_type_str_forces_string(tmp_path):
    path = tmp_path / "c.yaml"
    path.write_text("app: {}\n", encoding="utf-8")
    assert main_cli(["set", "app.version", "3.10", "--config", str(path), "--type", "str"]) == 0
    assert yaml.safe_load(path.read_text())["app"]["version"] == "3.10"


def test_set_local_type_json_parses_document(tmp_path):
    path = tmp_path / "c.yaml"
    path.write_text("app: {}\n", encoding="utf-8")
    assert (
        main_cli(["set", "app.flags", '{"beta": true}', "--config", str(path), "--type", "json"])
        == EXIT_OK
    )
    assert yaml.safe_load(path.read_text())["app"]["flags"] == {"beta": True}


def test_set_local_bad_typed_value_is_generic_error(tmp_yaml, capsys):
    assert (
        main_cli(["set", "database.port", "nope", "--config", str(tmp_yaml), "--type", "int"])
        == EXIT_ERROR
    )
    assert "Error:" in capsys.readouterr().err


def test_set_local_schema_violation_returns_error(tmp_path, tmp_schema, capsys):
    path = tmp_path / "c.yaml"
    path.write_text("database:\n  host: localhost\n  port: 5432\n", encoding="utf-8")
    assert (
        main_cli(
            [
                "set",
                "database.port",
                "not-an-int",
                "--config",
                str(path),
                "--schema",
                str(tmp_schema),
            ]
        )
        == EXIT_ERROR
    )
    assert "Error:" in capsys.readouterr().err


def test_delete_local_found_and_missing(tmp_yaml, capsys):
    assert main_cli(["delete", "database.host", "--config", str(tmp_yaml)]) == EXIT_OK
    assert "Deleted" in capsys.readouterr().out

    assert main_cli(["delete", "nope.gone", "--config", str(tmp_yaml)]) == EXIT_NOT_FOUND
    assert "not found" in capsys.readouterr().err


def test_local_backend_failure_is_generic_error(monkeypatch, capsys):
    def boom(*a, **k):
        raise RuntimeError("backend down")

    monkeypatch.setattr(cli, "create_config", boom)
    assert main_cli(["delete", "k", "--config", "c.yaml"]) == EXIT_ERROR
    assert "Error: backend down" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# get / set / delete — remote
# ---------------------------------------------------------------------------
def test_get_remote_full_config_with_revision(http, capsys):
    http["get"].append(("/config", FakeResponse(200, {"x": 1}, headers={"X-Nacho-Revision": "7"})))
    assert main_cli(["get", *REMOTE, "--show-revision"]) == EXIT_OK
    assert json.loads(capsys.readouterr().out) == {"revision": 7, "data": {"x": 1}}


def test_get_remote_single_key(http, capsys):
    http["get"].append(("/config/answer", FakeResponse(200, {"path": "answer", "value": 42})))
    assert main_cli(["get", "answer", *REMOTE]) == EXIT_OK
    assert json.loads(capsys.readouterr().out) == 42


def test_get_remote_missing_key_exits_not_found(http, capsys):
    http["get"].append(
        ("/config/nope", FakeResponse(404, {"detail": "Configuration path 'nope' not found"}))
    )
    assert main_cli(["get", "nope", *REMOTE]) == EXIT_NOT_FOUND
    assert "not found" in capsys.readouterr().err


def test_get_remote_unauthorized_exits_auth(http, capsys):
    http["get"].append(("/config", FakeResponse(401, {"detail": "Unauthorized"})))
    assert main_cli(["get", *REMOTE]) == EXIT_AUTH
    assert "Unauthorized" in capsys.readouterr().err


def test_get_remote_server_error_is_generic(http, capsys):
    http["get"].append(("/config", FakeResponse(500, {"detail": "kaboom"})))
    assert main_cli(["get", *REMOTE]) == EXIT_ERROR
    assert "kaboom" in capsys.readouterr().err


def test_set_remote_sends_parsed_value_and_revision(http, capsys):
    http["put"].append(
        (
            "/config/feature.enabled",
            FakeResponse(200, {"value": True, "revision": 8, "changed": True}),
        )
    )
    assert main_cli(["set", "feature.enabled", "true", *REMOTE, "--revision", "7"]) == EXIT_OK
    assert _json_bodies(http, "put")[0] == {"value": True, "type": "raw", "revision": 7}
    assert "revision 8" in capsys.readouterr().out


def test_set_remote_type_hint_defers_coercion_to_server(http, capsys):
    http["put"].append(
        (
            "/config/database.port",
            FakeResponse(200, {"value": 5432, "revision": 2, "changed": True}),
        )
    )
    assert main_cli(["set", "database.port", "5432", *REMOTE, "--type", "int"]) == EXIT_OK
    assert _json_bodies(http, "put")[0] == {"value": "5432", "type": "int"}
    assert "5432" in capsys.readouterr().out


def test_set_remote_reports_unchanged_writes(http, capsys):
    http["put"].append(
        ("/config/k", FakeResponse(200, {"value": 1, "revision": 3, "changed": False}))
    )
    assert main_cli(["set", "k", "1", *REMOTE]) == EXIT_OK
    assert "unchanged" in capsys.readouterr().out


def test_set_remote_conflict_exits_conflict(http, capsys):
    http["put"].append(
        (
            "/config/k",
            FakeResponse(
                409, {"detail": {"error": "revision_conflict", "expected": 7, "actual": 9}}
            ),
        )
    )
    assert main_cli(["set", "k", "1", *REMOTE, "--revision", "7"]) == EXIT_CONFLICT
    assert "Revision conflict" in capsys.readouterr().err


def test_set_remote_schema_rejection_is_generic(http, capsys):
    http["put"].append(("/config/port", FakeResponse(400, {"detail": "port: not an integer"})))
    assert main_cli(["set", "port", "x", *REMOTE]) == EXIT_ERROR
    assert "port" in capsys.readouterr().err


def test_delete_remote_success_and_revision_param(http, capsys):
    http["delete"].append(("/config/old", FakeResponse(200, {"revision": 4})))
    assert main_cli(["delete", "old", *REMOTE, "--revision", "3"]) == EXIT_OK
    assert "Deleted old" in capsys.readouterr().out
    delete_calls = [kw for m, _, kw in http["calls"] if m == "delete"]
    assert delete_calls[0]["params"] == {"revision": 3}


def test_delete_remote_conflict_and_missing(http, capsys):
    http["delete"].append(
        (
            "/config/a",
            FakeResponse(
                409, {"detail": {"error": "revision_conflict", "expected": 2, "actual": 5}}
            ),
        )
    )
    http["delete"].append(("/config/b", FakeResponse(404, {"detail": "path 'b' not found"})))
    assert main_cli(["delete", "a", *REMOTE, "--revision", "2"]) == EXIT_CONFLICT
    assert "Revision conflict" in capsys.readouterr().err
    assert main_cli(["delete", "b", *REMOTE]) == EXIT_NOT_FOUND
    assert "not found" in capsys.readouterr().err


def test_remote_without_deps_is_generic_error(monkeypatch, capsys):
    monkeypatch.setattr(cli, "HAS_REMOTE_DEPS", False)
    assert main_cli(["set", "k", "1", *REMOTE]) == EXIT_ERROR
    assert "Remote features require" in capsys.readouterr().err
    assert main_cli(["get", *REMOTE]) == EXIT_ERROR


# ---------------------------------------------------------------------------
# validate
# ---------------------------------------------------------------------------
def test_validate_local_success(tmp_yaml, tmp_schema, capsys):
    assert main_cli(["validate", "--config", str(tmp_yaml), "--schema", str(tmp_schema)]) == EXIT_OK
    assert "successful" in capsys.readouterr().out


def test_validate_local_rejects_invalid_config(tmp_path, tmp_schema, capsys):
    bad = tmp_path / "bad.yaml"
    bad.write_text("database:\n  host: localhost\n", encoding="utf-8")  # missing port
    assert main_cli(["validate", "--config", str(bad), "--schema", str(tmp_schema)]) == EXIT_ERROR
    assert "Error:" in capsys.readouterr().err


def test_validate_lists_validation_errors(monkeypatch, capsys):
    class FakeConfig:
        def validate(self):
            return ["database.port: out of range", "app.name: too short"]

    monkeypatch.setattr(cli, "create_config", lambda *a, **k: FakeConfig())
    assert main_cli(["validate", "--config", "c.yaml", "--schema", "s.json"]) == EXIT_ERROR
    out = capsys.readouterr().out
    assert "Validation failed" in out and "out of range" in out


def test_validate_without_schema_deps(monkeypatch, capsys):
    monkeypatch.setattr(cli, "HAS_SCHEMA_DEPS", False)
    assert main_cli(["validate", "--config", "c.yaml", "--schema", "s.json"]) == EXIT_ERROR
    assert "Schema validation requires" in capsys.readouterr().err


def test_validate_requires_schema_without_remote(capsys):
    assert main_cli(["validate", "--config", "c.yaml"]) == EXIT_ERROR
    assert "--schema is required" in capsys.readouterr().err


def test_validate_remote_uses_server_schema(http, tmp_yaml, capsys):
    http["post"].append(("/validate", FakeResponse(200, {"valid": True, "errors": []})))
    assert main_cli(["validate", "--config", str(tmp_yaml), *REMOTE]) == EXIT_OK
    assert "successful" in capsys.readouterr().out
    assert _json_bodies(http, "post")[0]["data"]["database"]["host"] == "localhost"


def test_validate_remote_reports_errors(http, tmp_yaml, capsys):
    http["post"].append(("/validate", FakeResponse(200, {"valid": False, "errors": ["port: bad"]})))
    assert main_cli(["validate", "--config", str(tmp_yaml), *REMOTE]) == EXIT_ERROR
    assert "port: bad" in capsys.readouterr().out


def test_validate_remote_tolerates_empty_body(http, tmp_yaml, capsys):
    http["post"].append(("/validate", FakeResponse(200, payload=None)))  # no JSON body
    assert main_cli(["validate", "--config", str(tmp_yaml), *REMOTE]) == EXIT_OK
    assert "successful" in capsys.readouterr().out


def test_validate_remote_missing_config_file(http, capsys):
    assert main_cli(["validate", "--config", "/nope/c.yaml", *REMOTE]) == EXIT_ERROR
    assert "not found" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# init
# ---------------------------------------------------------------------------
def test_init_creates_from_template(tmp_path):
    target = tmp_path / "new.yaml"
    assert main_cli(["init", str(target), "--template", "web-app"]) == EXIT_OK
    assert "app" in yaml.safe_load(target.read_text())


def test_init_refuses_existing_file(tmp_yaml, capsys):
    assert main_cli(["init", str(tmp_yaml)]) == EXIT_ERROR
    assert "already exists" in capsys.readouterr().err


def test_init_handles_write_error(tmp_path, monkeypatch, capsys):
    def boom(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(cli, "save_file", boom)
    assert main_cli(["init", str(tmp_path / "y.yaml")]) == EXIT_ERROR
    assert "Error:" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# server
# ---------------------------------------------------------------------------
class FakeOrchestrator:
    last = None

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.ran_with = None
        FakeOrchestrator.last = self

    def run(self, **kwargs):
        self.ran_with = kwargs


def test_server_runs_without_a_config(monkeypatch):
    monkeypatch.setattr(cli, "NachoOrchestrator", FakeOrchestrator)
    assert main_cli(["server"]) == EXIT_OK
    assert FakeOrchestrator.last.ran_with == {"host": "127.0.0.1", "port": 8000, "reload": False}


def test_server_loads_config_into_an_app(monkeypatch, tmp_yaml):
    monkeypatch.setattr(cli, "NachoOrchestrator", FakeOrchestrator)
    assert main_cli(["server", "--config", str(tmp_yaml), "--app-name", "svc"]) == EXIT_OK
    assert "svc" in FakeOrchestrator.last.kwargs["apps"]


def test_server_warns_on_non_loopback_host_without_key(monkeypatch, capsys):
    monkeypatch.setattr(cli, "NachoOrchestrator", FakeOrchestrator)
    assert main_cli(["server", "--host", "0.0.0.0"]) == EXIT_OK
    assert "WARNING" in capsys.readouterr().err


def test_server_no_warning_on_loopback_or_with_key(monkeypatch, capsys):
    monkeypatch.setattr(cli, "NachoOrchestrator", FakeOrchestrator)
    assert main_cli(["server", "--host", "::1"]) == EXIT_OK
    assert "WARNING" not in capsys.readouterr().err
    assert main_cli(["server", "--host", "0.0.0.0", "--api-key", "k"]) == EXIT_OK
    assert "WARNING" not in capsys.readouterr().err


def test_server_without_server_deps(monkeypatch, capsys):
    monkeypatch.setattr(cli, "HAS_SERVER_DEPS", False)
    assert main_cli(["server"]) == EXIT_ERROR
    assert "Server features require" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# apps
# ---------------------------------------------------------------------------
def test_apps_list_renders_json(http, capsys):
    http["get"].append(
        (
            "/api/apps",
            FakeResponse(
                200,
                {
                    "data": {
                        "svc": {
                            "revision": 3,
                            "config_count": 2,
                            "schema": True,
                            "description": "core",
                        },
                    }
                },
            ),
        )
    )
    assert main_cli(["apps", "list", "--remote", "http://s"]) == EXIT_OK
    assert json.loads(capsys.readouterr().out)["svc"]["revision"] == 3


def test_apps_list_auth_error(http, capsys):
    http["get"].append(("/api/apps", FakeResponse(401, {"detail": "Unauthorized"})))
    assert main_cli(["apps", "list", "--remote", "http://s"]) == EXIT_AUTH
    assert "Unauthorized" in capsys.readouterr().err


def test_apps_create_sends_schema_and_config(http, tmp_path, capsys):
    schema_file = tmp_path / "s.json"
    schema_file.write_text('{"type": "object"}')
    config_file = tmp_path / "c.json"
    config_file.write_text('{"x": 1}')
    http["post"].append(("/api/apps", FakeResponse(201, {"app": {"revision": 1}})))
    assert (
        main_cli(
            [
                "apps",
                "create",
                "svc",
                "--remote",
                "http://s",
                "--description",
                "desc",
                "--schema",
                str(schema_file),
                "--config",
                str(config_file),
            ]
        )
        == EXIT_OK
    )
    assert "Created app 'svc'" in capsys.readouterr().out
    body = _json_bodies(http, "post")[0]
    assert body["name"] == "svc"
    assert body["schema"] == {"type": "object"} and body["data"] == {"x": 1}
    assert body["description"] == "desc"


def test_apps_delete(http, capsys):
    http["delete"].append(("/api/apps/svc", FakeResponse(200, {"message": "gone"})))
    assert main_cli(["apps", "delete", "svc", "--remote", "http://s"]) == EXIT_OK
    assert "Deleted app 'svc'" in capsys.readouterr().out


def test_apps_show_prints_info(http, capsys):
    http["get"].append(
        (
            "/api/apps/svc",
            FakeResponse(200, {"data": {"name": "svc", "revision": 3, "schema": True}}),
        )
    )
    assert main_cli(["apps", "show", *REMOTE]) == EXIT_OK
    assert json.loads(capsys.readouterr().out)["revision"] == 3


def test_apps_rename_patches_metadata(http, capsys):
    http["patch"].append(("/metadata", FakeResponse(200, {"app": {"revision": 4}})))
    assert main_cli(["apps", "rename", "core", *REMOTE, "--revision", "3"]) == EXIT_OK
    assert _json_bodies(http, "patch")[0] == {"name": "core", "revision": 3}
    assert "Renamed app 'svc' to 'core'" in capsys.readouterr().out


def test_apps_describe_patches_metadata(http, capsys):
    http["patch"].append(("/metadata", FakeResponse(200, {"app": {"revision": 2}})))
    assert main_cli(["apps", "describe", "the core service", *REMOTE]) == EXIT_OK
    assert _json_bodies(http, "patch")[0] == {"description": "the core service"}
    assert "revision 2" in capsys.readouterr().out


def test_apps_rename_conflict_exits_conflict(http, capsys):
    http["patch"].append(
        (
            "/metadata",
            FakeResponse(
                409, {"detail": {"error": "revision_conflict", "expected": 3, "actual": 4}}
            ),
        )
    )
    assert main_cli(["apps", "rename", "core", *REMOTE, "--revision", "3"]) == EXIT_CONFLICT
    assert "Revision conflict" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# schema
# ---------------------------------------------------------------------------
def test_schema_get_prints_schema(http, capsys):
    http["get"].append(("/api/apps/svc/schema", FakeResponse(200, {"data": {"type": "object"}})))
    assert main_cli(["schema", "get", *REMOTE]) == EXIT_OK
    assert json.loads(capsys.readouterr().out) == {"type": "object"}


def test_schema_push_uploads_file(http, tmp_path, capsys):
    schema_file = tmp_path / "s.json"
    schema_file.write_text('{"type": "object"}')
    http["put"].append(("/api/apps/svc/schema", FakeResponse(200, {"revision": 5})))
    assert main_cli(["schema", "push", str(schema_file), *REMOTE, "--revision", "4"]) == EXIT_OK
    assert "revision 5" in capsys.readouterr().out
    body = _json_bodies(http, "put")[0]
    assert body["schema"] == {"type": "object"} and body["revision"] == 4


def test_schema_push_missing_file(http, capsys):
    assert main_cli(["schema", "push", "/nope/s.json", *REMOTE]) == EXIT_ERROR
    assert "not found" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# history / rollback
# ---------------------------------------------------------------------------
def test_history_list_renders_entries(http, capsys):
    http["get"].append(
        (
            "/api/apps/svc/history",
            FakeResponse(
                200,
                {
                    "data": [
                        {
                            "revision": 2,
                            "updated_at": "2026-07-17T01:00:00",
                            "config_count": 3,
                            "schema": True,
                        },
                        {
                            "revision": 1,
                            "updated_at": "2026-07-17T00:00:00",
                            "config_count": 1,
                            "schema": False,
                        },
                    ]
                },
            ),
        )
    )
    assert main_cli(["history", "list", *REMOTE]) == EXIT_OK
    entries = json.loads(capsys.readouterr().out)
    assert [e["revision"] for e in entries] == [2, 1]


def test_history_show_prints_snapshot(http, capsys):
    http["get"].append(
        (
            "/api/apps/svc/history/1",
            FakeResponse(200, {"data": {"revision": 1, "config": {"x": 1}, "schema": None}}),
        )
    )
    assert main_cli(["history", "show", "1", *REMOTE]) == EXIT_OK
    assert json.loads(capsys.readouterr().out)["config"] == {"x": 1}


def test_history_show_missing_revision_exits_not_found(http, capsys):
    http["get"].append(
        (
            "/api/apps/svc/history/9",
            FakeResponse(404, {"detail": "Revision 9 of app 'svc' is not in history"}),
        )
    )
    assert main_cli(["history", "show", "9", *REMOTE]) == EXIT_NOT_FOUND
    assert "not in history" in capsys.readouterr().err


def test_rollback_posts_revision_and_check(http, capsys):
    http["post"].append(
        (
            "/api/apps/svc/rollback",
            FakeResponse(200, {"message": "Rolled back to revision 1", "revision": 4}),
        )
    )
    assert main_cli(["rollback", "1", *REMOTE, "--revision-check", "3"]) == EXIT_OK
    assert _json_bodies(http, "post")[0] == {"revision": 1, "expected_revision": 3}
    assert "revision 4" in capsys.readouterr().out


def test_rollback_conflict_exits_conflict(http, capsys):
    http["post"].append(
        (
            "/api/apps/svc/rollback",
            FakeResponse(
                409, {"detail": {"error": "revision_conflict", "expected": 3, "actual": 4}}
            ),
        )
    )
    assert main_cli(["rollback", "1", *REMOTE, "--revision-check", "3"]) == EXIT_CONFLICT
    assert "Revision conflict" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# watch
# ---------------------------------------------------------------------------
def test_watch_streams_updates(monkeypatch, capsys):
    class FakeBackend:
        def __init__(self, url, app_name, api_key):
            self.on_remote_change = None

        def start_watching(self):
            self.on_remote_change({"x": 1})

        def close(self):
            pass

    monkeypatch.setattr("nacho.storage.remote.RemoteStorageBackend", FakeBackend)
    monkeypatch.setattr(
        "threading.Event.wait",
        lambda self, timeout=None: (_ for _ in ()).throw(KeyboardInterrupt()),
    )
    assert main_cli(["watch", *REMOTE]) == EXIT_OK
    captured = capsys.readouterr()
    assert json.loads(captured.out.strip()) == {"x": 1}
    assert "Watching" in captured.err


def test_watch_connect_failure(monkeypatch, capsys):
    def boom(**kwargs):
        raise RuntimeError("refused")

    monkeypatch.setattr("nacho.storage.remote.RemoteStorageBackend", boom)
    assert main_cli(["watch", *REMOTE]) == EXIT_ERROR
    assert "refused" in capsys.readouterr().err
