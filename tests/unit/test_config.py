"""Tests for the Nacho core class."""

import json

import pytest

from nacho import EventType, Nacho, ValidationError
from nacho.storage.base import StorageBackend, StorageError

# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


class TestConstruction:
    def test_empty(self):
        c = Nacho()
        assert c.get_all() == {}

    def test_dict_seed(self):
        c = Nacho({"a": 1, "b": {"c": 2}})
        assert c.get("a") == 1
        assert c.get("b.c") == 2

    def test_string_path(self, tmp_yaml):
        c = Nacho(str(tmp_yaml))
        assert c.get("database.host") == "localhost"

    def test_path_object(self, tmp_yaml):
        c = Nacho(tmp_yaml)
        assert c.get("database.port") == 5432

    def test_invalid_storage_type_raises(self):
        with pytest.raises(TypeError):
            Nacho(42)

    def test_read_only_flag(self):
        c = Nacho({"x": 1}, read_only=True)
        assert c._read_only is True

    def test_context_manager(self, tmp_yaml):
        with Nacho(tmp_yaml) as c:
            assert c.get("database.host") == "localhost"

    def test_storage_load_error_is_fatal_by_default(self):
        class BrokenStorage(StorageBackend):
            def load(self):
                raise StorageError("boom")

            def save(self, data):
                raise AssertionError("save should not be called")

        with pytest.raises(StorageError, match="boom"):
            Nacho(BrokenStorage())

    def test_storage_load_error_can_explicitly_fallback_to_empty(self):
        class BrokenStorage(StorageBackend):
            def load(self):
                raise StorageError("boom")

            def save(self, data):
                raise AssertionError("save should not be called")

        config = Nacho(BrokenStorage(), allow_empty_on_load_error=True)
        assert config.get_all() == {}


# ---------------------------------------------------------------------------
# Read API
# ---------------------------------------------------------------------------


class TestReadAPI:
    @pytest.fixture
    def config(self):
        return Nacho(
            {
                "debug": True,
                "port": 8080,
                "ratio": 0.5,
                "name": "test",
                "tags": ["a", "b"],
                "db": {"host": "localhost"},
            }
        )

    def test_get_none_key_returns_all(self, config):
        data = config.get(None)
        assert isinstance(data, dict)
        assert "debug" in data

    def test_get_returns_copy(self, config):
        d = config.get()
        d["injected"] = True
        assert "injected" not in config.data

    def test_get_missing_default(self, config):
        assert config.get("nonexistent", "fallback") == "fallback"

    def test_get_int(self, config):
        assert config.get_int("port") == 8080

    def test_get_int_string(self):
        c = Nacho({"port": "9090"})
        assert c.get_int("port") == 9090

    def test_get_int_missing(self, config):
        assert config.get_int("missing", 42) == 42

    def test_get_float(self, config):
        assert config.get_float("ratio") == 0.5

    def test_get_bool_true(self, config):
        assert config.get_bool("debug") is True

    def test_get_bool_from_string(self):
        for s in ("true", "yes", "1", "on", "True", "YES"):
            assert Nacho({"v": s}).get_bool("v") is True
        for s in ("false", "no", "0", "off"):
            assert Nacho({"v": s}).get_bool("v") is False

    def test_get_str(self, config):
        assert config.get_str("name") == "test"
        assert config.get_str("port") == "8080"

    def test_get_list(self, config):
        assert config.get_list("tags") == ["a", "b"]

    def test_get_list_not_list(self, config):
        assert config.get_list("port", ["default"]) == ["default"]

    def test_get_dict(self, config):
        assert config.get_dict("db") == {"host": "localhost"}

    def test_get_all_returns_deep_copy(self, config):
        d = config.get_all()
        d["hack"] = True
        assert "hack" not in config.data

    def test_data_property_is_defensive_and_read_only(self, config):
        data = config.data
        data["debug"] = False

        assert config.get("debug") is True
        with pytest.raises(AttributeError):
            config.data = {}

    def test_get_nested_container_returns_copy(self, config):
        db = config.get("db")
        db["host"] = "mutated"
        assert config.get("db.host") == "localhost"


# ---------------------------------------------------------------------------
# Write API
# ---------------------------------------------------------------------------


class TestWriteAPI:
    def test_set_simple(self):
        c = Nacho({"a": 1})
        changed = c.set("a", 2)
        assert changed is True
        assert c.get("a") == 2

    def test_set_nested_creates(self):
        c = Nacho()
        changed = c.set("db.host", "localhost")
        assert changed is True
        assert c.get("db.host") == "localhost"

    def test_set_no_change_is_noop(self):
        """set() with same value should not mutate data."""
        c = Nacho({"a": 1}, events=True)
        fired = []

        @c.on_change("*")
        def h(**kw):
            fired.append(True)

        changed = c.set("a", 1)
        assert changed is False
        assert fired == []

    def test_set_readonly_raises(self):
        c = Nacho({"a": 1}, read_only=True)
        with pytest.raises(PermissionError):
            c.set("a", 2)

    def test_delete_existing(self):
        c = Nacho({"a": 1, "b": 2})
        assert c.delete("a") is True
        assert c.get("a") is None

    def test_delete_missing(self):
        c = Nacho({"a": 1})
        assert c.delete("missing") is False

    def test_delete_nested(self):
        c = Nacho({"db": {"host": "h", "port": 5432}})
        assert c.delete("db.port") is True
        assert c.get("db.host") == "h"

    def test_delete_readonly_raises(self):
        c = Nacho({"a": 1}, read_only=True)
        with pytest.raises(PermissionError):
            c.delete("a")

    def test_update_merges(self):
        c = Nacho({"a": {"x": 1, "y": 2}})
        c.update({"a": {"x": 99}, "b": 3})
        assert c.get("a.x") == 99
        assert c.get("a.y") == 2
        assert c.get("b") == 3

    def test_update_no_change(self):
        c = Nacho({"a": 1})
        assert c.update({"a": 1}) is False

    def test_replace(self):
        c = Nacho({"a": 1, "b": 2})
        c.replace({"c": 3})
        assert c.get_all() == {"c": 3}

    def test_replace_no_change(self):
        c = Nacho({"a": 1})
        assert c.replace({"a": 1}) is False

    def test_replace_readonly_raises(self):
        c = Nacho({"a": 1}, read_only=True)
        with pytest.raises(PermissionError):
            c.replace({"b": 2})


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------


class TestEvents:
    def test_on_change_fires(self):
        c = Nacho({"db": {"host": "old"}}, events=True)
        fired = []

        @c.on_change("db.*")
        def h(path, new_value, **kw):
            fired.append((path, new_value))

        c.set("db.host", "new")
        assert ("db.host", "new") in fired

    def test_on_event_create(self):
        c = Nacho({}, events=True)
        fired = []

        @c.on_event(EventType.CREATE)
        def h(path, **kw):
            fired.append(path)

        c.set("new_key", "value")
        assert "new_key" in fired

    def test_on_event_delete(self):
        c = Nacho({"x": 1}, events=True)
        fired = []

        @c.on_event(EventType.DELETE)
        def h(path, **kw):
            fired.append(path)

        c.delete("x")
        assert "x" in fired

    def test_aggregate_handler_fires_once(self):
        """@global handler fires exactly once per set(), not once per changed leaf."""
        c = Nacho({"a": 1, "b": 2}, events=True)
        count = []

        @c.on_change("@global")
        def h(**kw):
            count.append(1)

        c.set("a", 99)
        assert len(count) == 1

    def test_events_disabled_by_default(self):
        c = Nacho({"a": 1})  # events=False
        fired = []

        @c.on_change("*")
        def h(**kw):
            fired.append(True)

        c.set("a", 2)
        assert fired == []

    def test_on_change_no_pattern_matches_all_changes(self):
        """path_pattern=None fires for all change events (any path)."""
        c = Nacho({"a": 1}, events=True)
        paths = []

        @c.on_change()  # no pattern = any change
        def h(path, **kw):
            paths.append(path)

        c.set("a", 2)
        # Fires for aggregate (None) AND per-path ("a")
        assert None in paths
        assert "a" in paths


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


class TestPersistence:
    def test_save_and_reload(self, tmp_yaml):
        c = Nacho(tmp_yaml)
        c.set("database.host", "prod-db")
        c.save()

        c2 = Nacho(tmp_yaml)
        assert c2.get("database.host") == "prod-db"

    def test_save_readonly_raises(self, tmp_yaml):
        c = Nacho(tmp_yaml, read_only=True)
        with pytest.raises(PermissionError):
            c.save()

    def test_save_in_memory_is_noop(self):
        c = Nacho({"a": 1})
        c.save()  # should not raise

    def test_load_updates_data(self, tmp_yaml):
        c = Nacho(tmp_yaml)
        # Modify file externally
        import yaml

        data = {"database": {"host": "modified", "port": 9999}}
        tmp_yaml.write_text(yaml.dump(data))
        c.load()
        assert c.get("database.host") == "modified"

    def test_json_serialization(self):
        c = Nacho({"key": "value", "num": 42})
        j = json.loads(c.json())
        assert j["key"] == "value"
        assert j["num"] == 42

    def test_env_overrides_are_not_persisted(self, tmp_path, monkeypatch):
        path = tmp_path / "config.json"
        path.write_text(json.dumps({"secret": "from-file", "feature": False}))
        monkeypatch.setenv("APP_SECRET", "from-env")

        config = Nacho(path, env_prefix="APP")
        assert config.get("secret") == "from-env"

        config.set("feature", True)
        config.save()

        stored = json.loads(path.read_text())
        assert stored == {"secret": "from-file", "feature": True}


# ---------------------------------------------------------------------------
# Transactions
# ---------------------------------------------------------------------------


class TestTransactions:
    def test_commit_applies_all(self):
        c = Nacho({"a": 1, "b": 2})
        with c.transaction() as txn:
            txn.set("a", 99)
            txn.set("c", 3)
        assert c.get("a") == 99
        assert c.get("c") == 3
        assert c.get("b") == 2

    def test_exception_rolls_back(self):
        c = Nacho({"a": 1})
        try:
            with c.transaction() as txn:
                txn.set("a", 999)
                raise ValueError("abort")
        except ValueError:
            pass
        assert c.get("a") == 1

    def test_transaction_events(self):
        c = Nacho({"a": 1, "b": 2}, events=True)
        fired = []

        @c.on_change("*")
        def h(path, **kw):
            fired.append(path)

        with c.transaction() as txn:
            txn.set("a", 10)
            txn.set("b", 20)

        # Both paths fired
        assert "a" in fired
        assert "b" in fired

    def test_txn_delete(self):
        c = Nacho({"a": 1, "b": 2})
        with c.transaction() as txn:
            txn.delete("a")
        assert c.get("a") is None
        assert c.get("b") == 2

    def test_txn_update(self):
        c = Nacho({"db": {"host": "old", "port": 5432}})
        with c.transaction() as txn:
            txn.update({"db": {"host": "new"}})
        assert c.get("db.host") == "new"
        assert c.get("db.port") == 5432

    def test_txn_replace(self):
        c = Nacho({"a": 1})
        with c.transaction() as txn:
            txn.replace({"b": 2})
        assert c.get_all() == {"b": 2}

    def test_transaction_readonly_raises(self):
        c = Nacho({"a": 1}, read_only=True)
        with pytest.raises(PermissionError):
            with c.transaction() as txn:
                txn.set("a", 2)
        assert c.get("a") == 1

    def test_transaction_validates_before_commit(self, tmp_schema):
        c = Nacho(
            {"database": {"host": "localhost", "port": 5432}},
            schema=tmp_schema,
        )
        with pytest.raises(ValidationError):
            with c.transaction() as txn:
                txn.set("database.port", "bad")
        assert c.get("database.port") == 5432


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------


class TestSchemaValidation:
    def test_valid_config_passes(self, tmp_schema):
        c = Nacho(
            {"database": {"host": "localhost", "port": 5432}},
            schema=tmp_schema,
        )
        assert c.validate() == []

    def test_invalid_write_raises(self, tmp_schema):
        c = Nacho(
            {"database": {"host": "localhost", "port": 5432}},
            schema=tmp_schema,
        )
        with pytest.raises(ValidationError):
            c.set("database.port", "not-an-int")

    def test_invalid_initial_data_raises(self, tmp_schema):
        with pytest.raises(ValidationError):
            Nacho({"database": {"host": "localhost", "port": "bad"}}, schema=tmp_schema)

    def test_schema_dict_input(self):
        schema = {
            "type": "object",
            "properties": {"x": {"type": "integer"}},
        }
        c = Nacho({"x": 1}, schema=schema)
        with pytest.raises(ValidationError):
            c.set("x", "not-an-int")

    def test_replace_validates(self, tmp_schema):
        c = Nacho(
            {"database": {"host": "localhost", "port": 5432}},
            schema=tmp_schema,
        )
        with pytest.raises(ValidationError):
            c.replace({"database": {"host": "x", "port": "bad"}})

    def test_delete_validates_and_preserves_old_state(self, tmp_schema):
        c = Nacho(
            {"database": {"host": "localhost", "port": 5432}},
            schema=tmp_schema,
        )
        with pytest.raises(ValidationError):
            c.delete("database.port")
        assert c.get("database.port") == 5432


class TestTypedGetterCoercion:
    """Coercion edge cases for the get_int/float/bool/list/dict helpers."""

    def test_get_int_none_value_returns_default(self):
        assert Nacho({"v": None}).get_int("v", default=7) == 7

    def test_get_int_uncoercible_returns_default(self):
        assert Nacho({"v": "abc"}).get_int("v", default=0) == 0

    def test_get_float_none_value_returns_default(self):
        assert Nacho({"v": None}).get_float("v", default=1.5) == 1.5

    def test_get_float_uncoercible_returns_default(self):
        assert Nacho({"v": "not-a-float"}).get_float("v", default=2.5) == 2.5

    def test_get_bool_none_value_returns_default(self):
        assert Nacho({"v": None}).get_bool("v", default=True) is True

    def test_get_bool_from_numeric_value(self):
        assert Nacho({"v": 5}).get_bool("v") is True
        assert Nacho({"v": 0}).get_bool("v") is False

    def test_get_bool_uncoercible_returns_default(self):
        assert Nacho({"v": [1, 2]}).get_bool("v", default=False) is False

    def test_get_list_none_value_returns_default(self):
        assert Nacho({"v": None}).get_list("v", default=[1]) == [1]

    def test_get_dict_none_value_returns_default(self):
        assert Nacho({"v": None}).get_dict("v", default={"d": 1}) == {"d": 1}

    def test_get_dict_non_dict_returns_default(self):
        assert Nacho({"v": "scalar"}).get_dict("v", default={}) == {}


class _ScriptedStorage(StorageBackend):
    """A storage backend whose load() returns queued values in order."""

    def __init__(self, *results):
        super().__init__()
        self._results = list(results)
        self.saved = None

    def load(self):
        value = self._results.pop(0)
        if isinstance(value, Exception):
            raise value
        return value

    def save(self, data):
        self.saved = data


class TestConfigEdgeCases:
    def test_update_with_empty_dict_is_noop(self):
        assert Nacho({"a": 1}).update({}) is False

    def test_replace_rejects_non_dict(self):
        with pytest.raises(TypeError):
            Nacho({"a": 1}).replace("not-a-dict")

    def test_replace_can_swap_in_a_new_schema(self, tmp_schema):
        c = Nacho({"database": {"host": "h", "port": 1}})
        # replacing with a schema validates the new data against it
        assert c.replace({"database": {"host": "h", "port": 1}}, schema=tmp_schema) is True
        with pytest.raises(ValidationError):
            c.replace({"database": {"host": "h"}}, schema=tmp_schema)

    def test_load_without_storage_returns_current_config(self):
        c = Nacho({"a": 1})
        assert c.load() == {"a": 1}

    def test_load_from_file_storage_reapplies(self, tmp_yaml):
        c = Nacho(str(tmp_yaml))
        assert c.load()["database"]["host"] == "localhost"

    def test_validate_without_schema_returns_empty(self):
        assert Nacho({"a": 1}).validate() == []

    def test_check_without_schema_returns_empty(self):
        assert Nacho({"a": 1}).check({"anything": True}) == []

    def test_event_pipeline_and_disabled_properties(self):
        c = Nacho({"a": 1}, events=True)
        assert c.event_pipeline is not None
        assert isinstance(c.event_disabled, bool)

    def test_remote_push_replaces_config(self):
        c = Nacho({"a": 1})
        c._on_remote_push({"a": 2, "b": 3})
        assert c.get_all() == {"a": 2, "b": 3}

    def test_construction_rejects_non_dict_from_storage(self):
        with pytest.raises(StorageError):
            Nacho(storage=_ScriptedStorage(["not", "a", "dict"]))

    def test_reload_emits_reload_and_change_events(self):
        storage = _ScriptedStorage({"a": 1}, {"a": 2})
        c = Nacho(storage=storage, events=True)
        seen = []

        @c.on_event(EventType.RELOAD)
        def _on_reload(**kwargs):
            seen.append("reload")

        assert c.load() == {"a": 2}
        assert "reload" in seen

    def test_reload_storage_error_keeps_current_when_allowed(self):
        storage = _ScriptedStorage({"a": 1}, StorageError("backend down"))
        c = Nacho(storage=storage, events=True, allow_empty_on_load_error=True)
        assert c.load() == {"a": 1}  # reload failed; previous config retained

    def test_reload_non_dict_payload_raises(self):
        storage = _ScriptedStorage({"a": 1}, ["not", "a", "dict"])
        c = Nacho(storage=storage)
        with pytest.raises(StorageError):
            c.load()

    def test_check_with_schema_reports_violations(self, tmp_schema):
        c = Nacho({"database": {"host": "h", "port": 1}}, schema=tmp_schema)
        assert c.check({"database": {"host": "h", "port": 1}}) == []
        assert c.check({"database": {"host": "h"}})  # missing port -> errors

    def test_reload_storage_error_propagates_by_default(self):
        storage = _ScriptedStorage({"a": 1}, StorageError("backend down"))
        c = Nacho(storage=storage)
        with pytest.raises(StorageError):
            c.load()
