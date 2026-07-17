"""Tests for schema validation."""


import pytest

from nacho.schema import SchemaValidator, ValidationError

SCHEMA = {
    "type": "object",
    "required": ["host", "port"],
    "properties": {
        "host": {"type": "string"},
        "port": {"type": "integer", "minimum": 1, "maximum": 65535},
    },
}


class TestSchemaValidator:
    def test_valid_data_passes(self):
        v = SchemaValidator(SCHEMA)
        v.validate({"host": "localhost", "port": 8080})  # no exception

    def test_wrong_type_raises(self):
        v = SchemaValidator(SCHEMA)
        with pytest.raises(ValidationError) as exc_info:
            v.validate({"host": "localhost", "port": "8080"})
        assert "port" in str(exc_info.value)

    def test_missing_required_raises(self):
        v = SchemaValidator(SCHEMA)
        with pytest.raises(ValidationError):
            v.validate({"host": "localhost"})

    def test_check_returns_empty_on_valid(self):
        v = SchemaValidator(SCHEMA)
        assert v.check({"host": "localhost", "port": 8080}) == []

    def test_check_returns_errors_on_invalid(self):
        v = SchemaValidator(SCHEMA)
        errors = v.check({"host": "localhost"})
        assert len(errors) > 0

    def test_validation_error_has_errors_list(self):
        v = SchemaValidator(SCHEMA)
        try:
            v.validate({"host": 123, "port": "bad"})
        except ValidationError as e:
            assert len(e.errors) >= 2

    def test_load_from_json_file(self, tmp_schema):
        v = SchemaValidator(tmp_schema)
        v.validate({"database": {"host": "localhost", "port": 5432}})

    def test_load_missing_file_raises(self):
        with pytest.raises(FileNotFoundError):
            SchemaValidator("/nonexistent/schema.json")

    def test_dict_schema(self):
        v = SchemaValidator({"type": "object"})
        v.validate({"anything": "goes"})

    def test_invalid_schema_type_raises(self):
        with pytest.raises(TypeError):
            SchemaValidator(42)

    def test_load_from_yaml_file(self, tmp_path):
        p = tmp_path / "schema.yaml"
        p.write_text("type: object\nrequired: [host]\n")
        v = SchemaValidator(p)
        v.validate({"host": "x"})
        with pytest.raises(ValidationError):
            v.validate({})

    def test_load_from_toml_file(self, tmp_path):
        p = tmp_path / "schema.toml"
        p.write_text('type = "object"\n')
        v = SchemaValidator(p)
        v.validate({"anything": True})

    def test_non_object_schema_file_raises(self, tmp_path):
        p = tmp_path / "schema.xml"
        p.write_text("<schema/>")
        with pytest.raises(ValueError, match="did not parse to an object"):
            SchemaValidator(p)

    def test_nested_anyof_errors_include_context(self):
        # anyOf failures surface as context sub-errors.
        schema = {
            "type": "object",
            "properties": {"v": {"anyOf": [{"type": "string"}, {"type": "integer"}]}},
        }
        errors = SchemaValidator(schema).check({"v": 3.5})
        assert any(error.startswith("  ") for error in errors)
