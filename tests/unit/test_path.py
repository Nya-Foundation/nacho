"""Tests for path utilities."""


import pytest

from nacho.utils.path import (
    deep_merge,
    delete_nested_value,
    get_nested_value,
    parse_path,
    set_nested_value,
)


class TestParsePath:
    def test_simple(self):
        assert parse_path("host") == ["host"]

    def test_nested(self):
        assert parse_path("database.host") == ["database", "host"]

    def test_array(self):
        assert parse_path("servers[0].host") == ["servers", "0", "host"]

    def test_empty(self):
        assert parse_path("") == []

    def test_deep(self):
        assert parse_path("a.b.c.d") == ["a", "b", "c", "d"]


class TestGetNestedValue:
    DATA = {"db": {"host": "localhost", "port": 5432}, "debug": True}

    def test_top_level(self):
        assert get_nested_value(self.DATA, "debug") is True

    def test_nested(self):
        assert get_nested_value(self.DATA, "db.host") == "localhost"

    def test_missing_returns_default(self):
        assert get_nested_value(self.DATA, "db.name", "mydb") == "mydb"

    def test_missing_returns_none_by_default(self):
        assert get_nested_value(self.DATA, "nonexistent") is None

    def test_no_path_returns_data(self):
        assert get_nested_value(self.DATA, "") is self.DATA

    def test_array_index(self):
        data = {"servers": [{"host": "a"}, {"host": "b"}]}
        assert get_nested_value(data, "servers[0].host") == "a"
        assert get_nested_value(data, "servers[1].host") == "b"


class TestSetNestedValue:
    def test_update_existing(self):
        data = {"db": {"host": "old"}}
        assert set_nested_value(data, "db.host", "new") is True
        assert data["db"]["host"] == "new"

    def test_create_nested(self):
        data = {}
        set_nested_value(data, "a.b.c", 42)
        assert data["a"]["b"]["c"] == 42

    def test_create_nested_through_scalar_raises(self):
        data = {"a": "scalar"}
        with pytest.raises(ValueError, match="not a container"):
            set_nested_value(data, "a.b", 42)
        assert data == {"a": "scalar"}

    def test_create_list_path(self):
        data = {}
        assert set_nested_value(data, "servers[0].host", "localhost") is True
        assert data == {"servers": [{"host": "localhost"}]}

    def test_no_change_returns_false(self):
        data = {"x": 1}
        assert set_nested_value(data, "x", 1) is False

    def test_empty_path_raises(self):
        with pytest.raises(ValueError, match="empty path"):
            set_nested_value({}, "", "v")

    def test_type_changing_write_with_equal_value_is_a_change(self):
        data = {"debug": 1}
        assert set_nested_value(data, "debug", True) is True
        assert data["debug"] is True


class TestDeleteNestedValue:
    def test_delete_existing(self):
        data = {"a": {"b": 1, "c": 2}}
        ok, old = delete_nested_value(data, "a.b")
        assert ok is True
        assert old == 1
        assert "b" not in data["a"]

    def test_delete_missing(self):
        data = {"a": 1}
        ok, old = delete_nested_value(data, "b")
        assert ok is False
        assert old is None

    def test_empty_path(self):
        ok, old = delete_nested_value({}, "")
        assert ok is False


class TestDeepMerge:
    def test_basic_merge(self):
        result = deep_merge({"b": 2}, {"a": 1})
        assert result == {"a": 1, "b": 2}

    def test_source_wins(self):
        result = deep_merge({"a": 99}, {"a": 1, "b": 2})
        assert result["a"] == 99
        assert result["b"] == 2

    def test_recursive(self):
        src = {"db": {"port": 9999}}
        dst = {"db": {"host": "localhost", "port": 5432}}
        result = deep_merge(src, dst)
        assert result["db"]["host"] == "localhost"
        assert result["db"]["port"] == 9999

    def test_does_not_mutate_inputs(self):
        src = {"a": 1}
        dst = {"b": 2}
        assert deep_merge(src, dst) == {"a": 1, "b": 2}
        assert "a" not in dst
        assert "b" not in src

    def test_non_dict_source_replaces_destination(self):
        assert deep_merge("scalar", {"a": 1}) == "scalar"


class TestPathEdgeCases:
    def test_set_digit_segment_on_a_dict_uses_string_key(self):
        data = {"a": {}}
        assert set_nested_value(data, "a.0.x", 1) is True
        assert data == {"a": {"0": {"x": 1}}}
        assert get_nested_value(data, "a.0.x") == 1

    def test_set_key_into_non_mapping_raises(self):
        with pytest.raises(ValueError, match="numeric list index"):
            set_nested_value({"a": [1, 2]}, "a.b.c", 1)

    def test_set_index_extends_list_with_padding(self):
        data = {"s": []}
        assert set_nested_value(data, "s[2]", "v") is True
        assert data["s"] == [None, None, "v"]

    def test_set_string_key_on_a_list_raises(self):
        with pytest.raises(ValueError, match="numeric list index"):
            set_nested_value({"s": []}, "s.key", "v")

    def test_delete_list_element_by_index(self):
        data = {"s": [1, 2, 3]}
        ok, old = delete_nested_value(data, "s[1]")
        assert ok is True and old == 2
        assert data["s"] == [1, 3]

    def test_delete_missing_nested_key(self):
        ok, old = delete_nested_value({"a": {"b": 1}}, "a.c")
        assert ok is False and old is None
