"""Schema validation for Nacho.

Optional dependency: install with `pip install nacho[schema]`.
SchemaValidator raises ValidationError on invalid data so the caller never
has to check a return value — invalid writes are refused immediately.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Union

logger = logging.getLogger(__name__)

try:
    import jsonschema
    from jsonschema import validators as _jv

    HAS_SCHEMA_DEPS = True
except ImportError:
    HAS_SCHEMA_DEPS = False


class ValidationError(Exception):
    """Raised when config data fails schema validation."""

    def __init__(self, errors: List[str]) -> None:
        self.errors = errors
        super().__init__("\n".join(errors))


class SchemaValidator:
    """Validates configuration dicts against a JSON Schema.

    Raises ImportError at construction time when jsonschema is absent so
    the error surfaces early, not on the first validate() call.
    """

    def __init__(self, schema: Union[Dict[str, Any], str, Path]) -> None:
        if not HAS_SCHEMA_DEPS:
            raise ImportError(
                "Schema validation requires 'jsonschema'. "
                "Install with: pip install nacho[schema]"
            )
        if isinstance(schema, (str, Path)):
            self._schema = self._load(Path(schema))
        elif isinstance(schema, dict):
            self._schema = schema
        else:
            raise TypeError(f"schema must be a dict, str, or Path — got {type(schema).__name__!r}")

        # Build validator once; reused on every validate() call.
        validator_cls = _jv.validator_for(self._schema)
        validator_cls.check_schema(self._schema)
        self._validator = validator_cls(
            self._schema,
            format_checker=jsonschema.FormatChecker(),
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def validate(self, data: Dict[str, Any]) -> None:
        """Validate *data* against the schema.

        Raises ValidationError listing every violation found.
        Does nothing when data is valid.
        """
        errors = self._collect_errors(data)
        if errors:
            raise ValidationError(errors)

    def check(self, data: Dict[str, Any]) -> List[str]:
        """Return a list of error strings (empty when data is valid).

        Use this when you want errors without an exception.
        """
        return self._collect_errors(data)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _collect_errors(self, data: Dict[str, Any]) -> List[str]:
        errors: List[str] = []
        for error in self._validator.iter_errors(data):
            path = ".".join(str(p) for p in error.path) or "root"
            errors.append(f"{path}: {error.message}")
            for sub in getattr(error, "context", []):
                sub_path = ".".join(str(p) for p in sub.path) or "root"
                errors.append(f"  {sub_path}: {sub.message}")
        return errors

    @staticmethod
    def _load(path: Path) -> Dict[str, Any]:
        if not path.exists():
            raise FileNotFoundError(f"Schema file not found: {path}")

        suffix = path.suffix.lower()
        if suffix == ".json":
            return json.loads(path.read_text(encoding="utf-8"))

        if suffix in (".yaml", ".yml"):
            try:
                import yaml

                return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            except ImportError:
                raise ImportError("YAML schema files require 'pyyaml'.")

        if suffix == ".toml":
            try:
                import tomllib  # type: ignore
            except ImportError:
                import tomli as tomllib  # type: ignore
            return tomllib.loads(path.read_text(encoding="utf-8")) or {}

        raise ValueError(f"Unsupported schema file format: {suffix!r}")
