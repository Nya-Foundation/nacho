"""Request models for the Nacho HTTP API."""

from __future__ import annotations

import re
from typing import Any, Dict, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator

SUPPORTED_FORMATS = {"json", "yaml", "toml"}
VALUE_TYPES = {"str", "int", "float", "bool", "list", "dict", "raw"}
APP_NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]*$")


def validate_app_name(name: str) -> str:
    if not APP_NAME_RE.match(name):
        raise ValueError(
            "Name must start with alphanumeric and contain only "
            "alphanumeric, underscore, or hyphen characters"
        )
    return name


def normalize_format(value: str) -> str:
    value = value.lower()
    if value not in SUPPORTED_FORMATS:
        raise ValueError(f"Format must be one of: {', '.join(sorted(SUPPORTED_FORMATS))}")
    return value


class ConfigRequest(BaseModel):
    """Full configuration payload."""

    data: Union[str, Dict[str, Any]] = Field(
        ...,
        description="Configuration data as an object, or as an encoded string",
    )
    format: str = Field(default="json", description="json, yaml, or toml")
    revision: Optional[int] = Field(
        default=None,
        ge=1,
        description="Expected app revision for optimistic concurrency",
    )

    @field_validator("format")
    @classmethod
    def validate_format(cls, value: str) -> str:
        return normalize_format(value)

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {"data": {"feature": True}},
                {"data": '{"feature": true}', "format": "json"},
            ]
        }
    )


class AppReplaceRequest(ConfigRequest):
    """Replace an app's config, schema, and description.

    Renaming is done via PATCH /api/apps/{name}/metadata, not here.
    """

    description: Optional[str] = Field(default=None, max_length=256)
    schema_: Optional[Union[str, Dict[str, Any]]] = Field(
        default=None,
        alias="schema",
        description="Optional JSON Schema as an object, or as an encoded string",
    )
    schema_format: str = Field(default="json", description="json, yaml, or toml")
    model_config = ConfigDict(populate_by_name=True)

    @field_validator("schema_format")
    @classmethod
    def validate_schema_format(cls, value: str) -> str:
        return normalize_format(value)


class AppCreateRequest(AppReplaceRequest):
    """Create an app."""

    name: str = Field(..., min_length=1, max_length=64)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        return validate_app_name(value)


class ConvertRequest(BaseModel):
    """Convert a config or schema payload between json, yaml, and toml."""

    data: Union[str, Dict[str, Any]] = Field(
        ...,
        description="Payload as an object, or as an encoded string in the source format",
    )
    from_: str = Field(default="json", alias="from", description="Source format")
    to: str = Field(default="json", description="Target format")
    model_config = ConfigDict(populate_by_name=True)

    @field_validator("from_", "to")
    @classmethod
    def validate_fmt(cls, value: str) -> str:
        return normalize_format(value)


class SchemaUpdateRequest(BaseModel):
    """Replace (or clear) an app's JSON Schema after creation."""

    schema_: Optional[Union[str, Dict[str, Any]]] = Field(
        default=None,
        alias="schema",
        description="JSON Schema as an object or encoded string; null clears the schema",
    )
    schema_format: str = Field(default="json", description="json, yaml, or toml")
    revision: Optional[int] = Field(
        default=None,
        ge=1,
        description="Expected app revision for optimistic concurrency",
    )
    model_config = ConfigDict(populate_by_name=True)

    @field_validator("schema_format")
    @classmethod
    def validate_schema_format(cls, value: str) -> str:
        return normalize_format(value)


class AppMetadataRequest(BaseModel):
    """Rename an app or change its description."""

    name: Optional[str] = Field(default=None, min_length=1, max_length=64)
    description: Optional[str] = Field(default=None, max_length=256)
    revision: Optional[int] = Field(
        default=None,
        ge=1,
        description="Expected app revision for optimistic concurrency",
    )

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        return validate_app_name(value)


class RollbackRequest(BaseModel):
    """Restore config and schema from a history snapshot (as a new revision)."""

    revision: int = Field(..., ge=1, description="History revision to restore")
    expected_revision: Optional[int] = Field(
        default=None,
        ge=1,
        description="Expected current app revision for optimistic concurrency",
    )


class PathUpdateRequest(BaseModel):
    """Set a single config path."""

    value: Any
    type: str = Field(default="raw", description="raw, str, int, float, bool, list, or dict")
    revision: Optional[int] = Field(
        default=None,
        ge=1,
        description="Expected app revision for optimistic concurrency",
    )

    @field_validator("type")
    @classmethod
    def validate_type(cls, value: str) -> str:
        value = value.lower()
        if value not in VALUE_TYPES:
            raise ValueError(f"Type must be one of: {', '.join(sorted(VALUE_TYPES))}")
        return value
