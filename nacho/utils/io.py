"""File I/O utilities supporting YAML, JSON, and TOML formats."""

from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, Union

import yaml

try:
    import tomllib  # Python ≥ 3.11
except ImportError:  # pragma: no cover - Python < 3.11 fallback
    import tomli as tomllib  # type: ignore[no-redef]

try:
    import tomli_w
except ImportError:  # pragma: no cover - optional TOML-write dependency
    tomli_w = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)


def _suffix(path: Path) -> str:
    return path.suffix.lower()


def load_file(path: Union[str, Path]) -> Dict[str, Any]:
    """Load a YAML / JSON / TOML file and return a dict.

    Returns an empty dict when the file is missing or empty.
    Raises ValueError on parse errors so callers can decide how to handle.
    """
    path = Path(path)
    if not path.exists():
        return {}

    try:
        suffix = _suffix(path)
        if suffix in (".yaml", ".yml"):
            with open(path, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        if suffix == ".json":
            text = path.read_text(encoding="utf-8")
            return json.loads(text) if text.strip() else {}
        if suffix == ".toml":
            with open(path, "rb") as f:
                return tomllib.load(f) or {}
        # Unknown extension → try YAML
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except (json.JSONDecodeError, yaml.YAMLError, tomllib.TOMLDecodeError) as exc:
        raise ValueError(f"Failed to parse {path}: {exc}") from exc


_SUFFIX_FORMATS = {".yaml": "yaml", ".yml": "yaml", ".json": "json", ".toml": "toml"}


def save_file(path: Union[str, Path], data: Dict[str, Any]) -> None:
    """Persist *data* atomically to a YAML / JSON / TOML file.

    Raises IOError on write failures, ValueError when the data cannot be
    represented in the target format — serialization happens before the
    file is touched, so a bad payload never corrupts the existing file.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    fmt = _SUFFIX_FORMATS.get(_suffix(path), "yaml")
    text = dump_string(data, fmt)

    tmp_name = ""
    try:
        fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        # mkstemp creates 0600 files; keep the target's existing mode (or a
        # conventional default) instead of silently tightening permissions.
        os.chmod(tmp_name, path.stat().st_mode & 0o777 if path.exists() else 0o644)
        os.replace(tmp_name, path)
    except OSError as exc:
        raise IOError(f"Failed to write {path}: {exc}") from exc
    finally:
        if tmp_name:
            try:
                Path(tmp_name).unlink(missing_ok=True)
            except OSError:
                logger.warning("Failed to clean temporary file %s", tmp_name)


def load_string(text: str, fmt: str = "json") -> Dict[str, Any]:
    """Parse a config string in the given format ('json', 'yaml', 'toml').

    Returns an empty dict for blank input.
    """
    if not text or not text.strip():
        return {}
    if fmt == "yaml":
        return yaml.safe_load(text) or {}
    if fmt == "toml":
        return tomllib.loads(text) or {}
    return json.loads(text)


def dump_string(data: Dict[str, Any], fmt: str = "json") -> str:
    """Serialize a config dict to a string in the given format.

    Raises ValueError for unsupported formats or data the format cannot
    represent (e.g. ``null`` values in TOML).
    """
    if fmt == "yaml":
        try:
            # safe_dump refuses arbitrary Python objects, so unserializable
            # data fails here instead of writing a file safe_load can't read.
            return yaml.safe_dump(
                data, default_flow_style=False, sort_keys=False, indent=2, allow_unicode=True
            )
        except yaml.YAMLError as exc:
            raise ValueError(f"Data cannot be represented as YAML: {exc}") from exc
    if fmt == "toml":
        if tomli_w is None:
            raise ValueError(
                "TOML write support requires 'tomli_w'. Install with: pip install tomli-w"
            )
        try:
            return tomli_w.dumps(data)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Data cannot be represented as TOML: {exc}") from exc
    try:
        return json.dumps(data, indent=2, ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Data cannot be represented as JSON: {exc}") from exc
