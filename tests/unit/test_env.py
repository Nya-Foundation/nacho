"""Tests for environment variable override support."""

import pytest

from nacho.env import EnvOverrideHandler


class TestEnvOverrideHandler:
    def test_basic_override(self, monkeypatch):
        monkeypatch.setenv("NACHO_HOST", "prod-host")
        handler = EnvOverrideHandler(prefix="NACHO")
        data = handler.apply({"host": "localhost"})
        assert data["host"] == "prod-host"

    def test_nested_override(self, monkeypatch):
        monkeypatch.setenv("NACHO_DATABASE_HOST", "db-prod")
        handler = EnvOverrideHandler(prefix="NACHO")
        data = handler.apply({"database": {"host": "old", "port": 5432}})
        assert data["database"]["host"] == "db-prod"
        assert data["database"]["port"] == 5432  # unchanged

    def test_type_coercion_int(self, monkeypatch):
        monkeypatch.setenv("APP_PORT", "9090")
        handler = EnvOverrideHandler(prefix="APP")
        data = handler.apply({"port": 8080})
        assert data["port"] == 9090
        assert isinstance(data["port"], int)

    def test_type_coercion_bool(self, monkeypatch):
        monkeypatch.setenv("APP_DEBUG", "true")
        handler = EnvOverrideHandler(prefix="APP")
        data = handler.apply({"debug": False})
        assert data["debug"] is True

    def test_does_not_mutate_input(self, monkeypatch):
        monkeypatch.setenv("NEKO_X", "99")
        handler = EnvOverrideHandler(prefix="NEKO")
        original = {"x": 1}
        result = handler.apply(original)
        assert original["x"] == 1
        assert result["x"] == 99

    def test_exclude_paths(self, monkeypatch):
        monkeypatch.setenv("APP_SECRET", "leaked")
        handler = EnvOverrideHandler(prefix="APP", exclude_paths=["secret"])
        data = handler.apply({"secret": "safe"})
        assert data["secret"] == "safe"

    def test_include_paths(self, monkeypatch):
        monkeypatch.setenv("APP_DB_HOST", "new")
        monkeypatch.setenv("APP_OTHER", "ignored")
        handler = EnvOverrideHandler(prefix="APP", include_paths=["db"])
        data = handler.apply({"db": {"host": "old"}, "other": "original"})
        assert data["db"]["host"] == "new"
        assert data["other"] == "original"

    def test_empty_prefix_is_rejected(self):
        with pytest.raises(ValueError, match="prefix"):
            EnvOverrideHandler(prefix="")

    def test_numeric_strings_stay_numeric(self, monkeypatch):
        monkeypatch.setenv("APP_PORT", "1")
        handler = EnvOverrideHandler(prefix="APP")
        data = handler.apply({"port": 8080})
        assert data["port"] == 1 and not isinstance(data["port"], bool)

    def test_integration_with_nacho(self, monkeypatch):
        monkeypatch.setenv("NACHO_DATABASE_PORT", "9999")
        from nacho import Nacho

        c = Nacho(
            {"database": {"host": "localhost", "port": 5432}},
            env_prefix="NACHO",
        )
        assert c.get_int("database.port") == 9999


class TestParsePredictability:
    def test_version_like_string_stays_a_string(self, monkeypatch):
        monkeypatch.setenv("APP_VERSION", "3.10")
        handler = EnvOverrideHandler(prefix="APP")
        assert handler.apply({"version": "old"})["version"] == "3.10"

    def test_float_round_trip_is_parsed(self, monkeypatch):
        monkeypatch.setenv("APP_RATIO", "3.14")
        handler = EnvOverrideHandler(prefix="APP")
        assert handler.apply({"ratio": 0.0})["ratio"] == 3.14

    def test_quoted_value_forces_string(self, monkeypatch):
        monkeypatch.setenv("APP_PORT", '"8080"')
        handler = EnvOverrideHandler(prefix="APP")
        assert handler.apply({"port": 1})["port"] == "8080"

    def test_double_delimiter_nests_and_single_stays_in_key(self, monkeypatch):
        monkeypatch.setenv("APP_DB__MAX_CONNECTIONS", "50")
        handler = EnvOverrideHandler(prefix="APP")
        data = handler.apply({"db": {"max_connections": 10}})
        assert data["db"]["max_connections"] == 50

    def test_conflicting_override_is_skipped_not_fatal(self, monkeypatch):
        monkeypatch.setenv("APP_DB_HOST", "x")
        handler = EnvOverrideHandler(prefix="APP")
        data = handler.apply({"db": "just-a-string"})
        assert data == {"db": "just-a-string"}
