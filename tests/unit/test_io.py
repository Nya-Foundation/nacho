"""Tests for file I/O utilities."""

import json
from pathlib import Path

import pytest

from nacho.utils.io import dump_string, load_file, load_string, save_file


class TestLoadFile:
    def test_yaml(self, tmp_yaml):
        data = load_file(tmp_yaml)
        assert data["database"]["host"] == "localhost"
        assert data["database"]["port"] == 5432

    def test_json(self, tmp_json):
        data = load_file(tmp_json)
        assert data["app"]["name"] == "test"

    def test_toml(self, tmp_toml):
        data = load_file(tmp_toml)
        assert data["server"]["port"] == 8080

    def test_missing_file_returns_empty(self, tmp_path):
        data = load_file(tmp_path / "nope.yaml")
        assert data == {}

    def test_invalid_yaml_raises(self, tmp_path):
        p = tmp_path / "bad.yaml"
        p.write_text(": : invalid : yaml : :")
        with pytest.raises(ValueError):
            load_file(p)


class TestSaveFile:
    def test_yaml_roundtrip(self, tmp_path):
        p = tmp_path / "out.yaml"
        data = {"key": "value", "nested": {"x": 1}}
        save_file(p, data)
        assert load_file(p) == data

    def test_json_roundtrip(self, tmp_path):
        p = tmp_path / "out.json"
        data = {"list": [1, 2, 3], "bool": True}
        save_file(p, data)
        assert load_file(p) == data

    def test_toml_roundtrip(self, tmp_path):
        p = tmp_path / "out.toml"
        data = {"section": {"value": 42}}
        save_file(p, data)
        assert load_file(p) == data

    def test_creates_parent_dirs(self, tmp_path):
        p = tmp_path / "a" / "b" / "c.json"
        save_file(p, {"x": 1})
        assert p.exists()


    def test_unknown_extension_is_parsed_as_yaml(self, tmp_path):
        p = tmp_path / "config.conf"
        p.write_text("key: value\n")
        assert load_file(p) == {"key": "value"}

    def test_unknown_extension_is_written_as_yaml(self, tmp_path):
        p = tmp_path / "out.conf"
        save_file(p, {"x": 1})
        assert load_file(p) == {"x": 1}

    def test_write_failure_is_wrapped_as_ioerror(self, tmp_path, monkeypatch):
        import os

        def boom(*a, **k):
            raise OSError("replace failed")

        monkeypatch.setattr(os, "replace", boom)
        with pytest.raises(IOError, match="Failed to write"):
            save_file(tmp_path / "out.json", {"x": 1})


class TestCreateFileIfNotExists:
    def test_creates_file_and_parents(self, tmp_path):
        from nacho.utils.io import create_file_if_not_exists

        target = tmp_path / "deep" / "dir" / "touched.yaml"
        create_file_if_not_exists(target)
        assert target.exists()

    def test_is_noop_when_file_exists(self, tmp_path):
        from nacho.utils.io import create_file_if_not_exists

        target = tmp_path / "exists.yaml"
        target.write_text("original")
        create_file_if_not_exists(target)
        assert target.read_text() == "original"


class TestLoadString:
    def test_json(self):
        assert load_string('{"a": 1}', "json") == {"a": 1}

    def test_yaml(self):
        assert load_string("a: 1\nb: 2\n", "yaml") == {"a": 1, "b": 2}

    def test_toml(self):
        assert load_string('x = 1\n', "toml") == {"x": 1}

    def test_empty_returns_empty(self):
        assert load_string("", "json") == {}
        assert load_string("   ", "yaml") == {}


class TestDumpString:
    def test_json(self):
        assert json.loads(dump_string({"a": 1}, "json")) == {"a": 1}

    def test_yaml(self):
        assert "a: 1" in dump_string({"a": 1}, "yaml")

    def test_toml(self):
        assert "x = 1" in dump_string({"x": 1}, "toml")

    def test_toml_rejects_unrepresentable_data(self):
        # TOML has no null type; a None value cannot be serialized.
        with pytest.raises(ValueError):
            dump_string({"x": None}, "toml")
