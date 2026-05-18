"""Tests for the Nacho API request models and their field validators."""

import pytest
from pydantic import ValidationError

from nacho.server.models import (
    AppCreateRequest,
    AppMetadataRequest,
    ConfigRequest,
    ConvertRequest,
    PathUpdateRequest,
    SchemaUpdateRequest,
    validate_app_name,
)


class TestAppName:
    def test_accepts_valid_names(self):
        assert validate_app_name("my-svc_1") == "my-svc_1"

    @pytest.mark.parametrize("bad", ["-leading", "has space", "with/slash", ""])
    def test_rejects_invalid_names(self, bad):
        with pytest.raises(ValueError):
            validate_app_name(bad)


class TestConfigRequest:
    def test_defaults_to_json(self):
        assert ConfigRequest(data={}).format == "json"

    def test_rejects_unknown_format(self):
        with pytest.raises(ValidationError):
            ConfigRequest(data={}, format="xml")

    def test_normalizes_format_case(self):
        assert ConfigRequest(data={}, format="YAML").format == "yaml"


class TestAppCreateRequest:
    def test_valid_payload(self):
        req = AppCreateRequest(name="svc", data={}, schema_format="YAML")
        assert req.name == "svc" and req.schema_format == "yaml"

    def test_rejects_bad_name(self):
        with pytest.raises(ValidationError):
            AppCreateRequest(name="bad name", data={})

    def test_rejects_bad_schema_format(self):
        with pytest.raises(ValidationError):
            AppCreateRequest(name="svc", data={}, schema_format="xml")

    def test_schema_alias_is_accepted(self):
        req = AppCreateRequest(name="svc", data={}, schema={"type": "object"})
        assert req.schema_ == {"type": "object"}


class TestConvertRequest:
    def test_from_alias_and_defaults(self):
        req = ConvertRequest(data={}, **{"from": "yaml"}, to="toml")
        assert req.from_ == "yaml" and req.to == "toml"

    def test_rejects_unknown_format(self):
        with pytest.raises(ValidationError):
            ConvertRequest(data={}, to="xml")


class TestSchemaUpdateRequest:
    def test_null_schema_is_allowed(self):
        assert SchemaUpdateRequest(schema=None).schema_ is None

    def test_normalizes_schema_format(self):
        assert SchemaUpdateRequest(schema={}, schema_format="TOML").schema_format == "toml"

    def test_rejects_bad_schema_format(self):
        with pytest.raises(ValidationError):
            SchemaUpdateRequest(schema={}, schema_format="xml")


class TestAppMetadataRequest:
    def test_name_is_optional(self):
        assert AppMetadataRequest(description="just a description").name is None

    def test_accepts_a_valid_name(self):
        assert AppMetadataRequest(name="renamed-svc").name == "renamed-svc"

    def test_rejects_bad_name(self):
        with pytest.raises(ValidationError):
            AppMetadataRequest(name="bad name")


class TestPathUpdateRequest:
    def test_default_type_is_raw(self):
        assert PathUpdateRequest(value=1).type == "raw"

    def test_accepts_explicit_valid_type(self):
        assert PathUpdateRequest(value=1, type="INT").type == "int"

    def test_rejects_unknown_type(self):
        with pytest.raises(ValidationError):
            PathUpdateRequest(value=1, type="complex")
