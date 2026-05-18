"""Tests for the public CLI command handlers."""

from argparse import Namespace

import yaml

from nacho.cli.main import cmd_delete, cmd_get, cmd_set, create_config


class FakeResponse:
    def __init__(self, status_code=200, payload=None, headers=None, text=""):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.headers = headers or {}
        self.text = text

    def json(self):
        return self._payload


def test_create_config_uses_current_nacho_api(tmp_yaml):
    config = create_config(str(tmp_yaml))
    assert config.get("database.host") == "localhost"


def test_cmd_get_reads_local_config(tmp_yaml, capsys):
    args = Namespace(
        config=str(tmp_yaml),
        key="database.host",
        format="raw",
        remote=None,
        app_name="default",
        api_key=None,
    )

    assert cmd_get(args) == 0
    assert capsys.readouterr().out.strip() == "localhost"


def test_cmd_set_writes_local_config(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text("database:\n  host: localhost\n", encoding="utf-8")

    args = Namespace(
        config=str(config_path),
        schema=None,
        key="database.port",
        value="5432",
        remote=None,
        app_name="default",
        api_key=None,
    )

    assert cmd_set(args) == 0
    assert yaml.safe_load(config_path.read_text(encoding="utf-8"))["database"]["port"] == 5432


def test_cmd_get_remote_can_show_revision(monkeypatch, capsys):
    def fake_get(url, headers, timeout):
        assert url == "http://server/api/apps/svc/config"
        assert headers["Authorization"] == "Bearer secret"
        assert timeout == 10
        return FakeResponse(payload={"x": 1}, headers={"X-Nacho-Revision": "7"})

    import requests

    monkeypatch.setattr(requests, "get", fake_get)
    args = Namespace(
        config="config.yaml",
        key=None,
        format="json",
        remote="http://server",
        app_name="svc",
        api_key="secret",
        show_revision=True,
    )

    assert cmd_get(args) == 0
    assert '"revision": 7' in capsys.readouterr().out


def test_cmd_set_remote_sends_revision(monkeypatch, capsys):
    captured = {}

    def fake_put(url, json, headers, timeout):
        captured.update({"url": url, "json": json, "headers": headers, "timeout": timeout})
        return FakeResponse(payload={"revision": 8})

    import requests

    monkeypatch.setattr(requests, "put", fake_put)
    args = Namespace(
        config="config.yaml",
        schema=None,
        key="feature.enabled",
        value="true",
        remote="http://server",
        app_name="svc",
        api_key="secret",
        revision=7,
    )

    assert cmd_set(args) == 0
    assert captured["url"] == "http://server/api/apps/svc/config/feature.enabled"
    assert captured["json"] == {"value": True, "type": "raw", "revision": 7}
    assert "revision 8" in capsys.readouterr().out


def test_cmd_delete_remote_reports_conflict(monkeypatch, capsys):
    def fake_delete(url, params, headers, timeout):
        assert params == {"revision": 2}
        return FakeResponse(
            status_code=409,
            payload={"detail": {"error": "revision_conflict", "expected": 2, "actual": 3}},
        )

    import requests

    monkeypatch.setattr(requests, "delete", fake_delete)
    args = Namespace(
        config="config.yaml",
        schema=None,
        key="old.setting",
        remote="http://server",
        app_name="svc",
        api_key="secret",
        revision=2,
    )

    assert cmd_delete(args) == 1
    assert "revision_conflict" in capsys.readouterr().out
