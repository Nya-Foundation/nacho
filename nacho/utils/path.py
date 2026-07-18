"""Path navigation utilities for dot-notation config access."""

from __future__ import annotations

import copy
import re
from typing import Any, Dict, List, MutableMapping, Tuple


def _parse_segment(segment: str) -> List[str]:
    m = re.match(r"^([^[\]]+)\[([^\]]+)\]$", segment)
    if m:
        key, index = m.groups()
        return [key, index]
    return [segment]


def parse_path(path: str) -> List[str]:
    """Split a dot-notation path into a flat list of keys and array indices.

    Examples:
        "database.host"       → ["database", "host"]
        "servers[0].port"     → ["servers", "0", "port"]
    """
    if not path:
        return []
    result = []
    for segment in path.split("."):
        result.extend(_parse_segment(segment))
    return result


def get_nested_value(data: Dict[str, Any], path: str, default: Any = None) -> Any:
    """Retrieve a value by dot-notation path; return *default* when absent."""
    if not path:
        return data
    try:
        current = data
        for key in parse_path(path):
            # Digit segments index sequences; dict keys are always looked up
            # as strings so JSON configs with numeric keys stay reachable.
            if isinstance(current, (list, tuple)) and key.isdigit():
                current = current[int(key)]
            else:
                current = current[key]
        return current
    except (KeyError, IndexError, TypeError):
        return default


def set_nested_value(data: Dict[str, Any], path: str, value: Any) -> bool:
    """Set a value by dot-notation path, creating intermediate dicts as needed.

    Returns True when the value changed, False when the stored value was
    already identical (same value and same type — so replacing the int ``1``
    with ``True`` counts as a change).
    Raises ValueError when the path cannot be written because an
    intermediate segment is not a container.
    """
    if not path:
        raise ValueError("Cannot set an empty path")

    _MISSING = object()
    existing = get_nested_value(data, path, _MISSING)
    if existing is not _MISSING and type(existing) is type(value) and existing == value:
        return False

    keys = parse_path(path)
    current: Any = data
    for index, key in enumerate(keys[:-1]):
        next_key = keys[index + 1]
        if isinstance(current, list):
            if not key.isdigit():
                raise ValueError(
                    f"Cannot set {path!r}: segment {key!r} must be a numeric list index"
                )
            idx = int(key)
            while len(current) <= idx:
                current.append([] if next_key.isdigit() else {})
            current = current[idx]
        elif isinstance(current, MutableMapping):
            if key not in current:
                current[key] = [] if next_key.isdigit() else {}
            elif not isinstance(current[key], (dict, list)):
                raise ValueError(
                    f"Cannot set {path!r}: segment {key!r} holds a "
                    f"{type(current[key]).__name__}, not a container"
                )
            current = current[key]
        else:
            raise ValueError(
                f"Cannot set {path!r}: segment {key!r} is inside a "
                f"{type(current).__name__}, not a container"
            )

    final = keys[-1]
    if isinstance(current, list):
        if not final.isdigit():
            raise ValueError(f"Cannot set {path!r}: segment {final!r} must be a numeric list index")
        idx = int(final)
        while len(current) <= idx:
            current.append(None)
        current[idx] = value
    elif isinstance(current, MutableMapping):
        current[final] = value
    else:
        raise ValueError(
            f"Cannot set {path!r}: segment {final!r} is inside a "
            f"{type(current).__name__}, not a container"
        )
    return True


def delete_nested_value(data: Dict[str, Any], path: str) -> Tuple[bool, Any]:
    """Delete a value by dot-notation path.

    Returns (True, old_value) on success, (False, None) when the key is absent.
    """
    if not path:
        return False, None

    _MISSING = object()
    old_value = get_nested_value(data, path, _MISSING)
    if old_value is _MISSING:
        return False, None

    keys = parse_path(path)
    current = data
    try:
        for key in keys[:-1]:
            if isinstance(current, (list, tuple)) and key.isdigit():
                current = current[int(key)]
            else:
                current = current[key]
    except (KeyError, IndexError, TypeError):
        return False, None

    final = keys[-1]
    try:
        if isinstance(current, list):
            if not final.isdigit():
                return False, None
            del current[int(final)]
        else:
            del current[final]
        return True, old_value
    except (KeyError, IndexError, TypeError):
        return False, None


def deep_merge(source: Dict[str, Any], destination: Dict[str, Any]) -> Dict[str, Any]:
    """Return a new dict that is *destination* deep-merged with *source*.

    Source keys take precedence; nested dicts are merged recursively.
    """
    if not isinstance(destination, dict) or not isinstance(source, dict):
        return copy.deepcopy(source)
    result = copy.deepcopy(destination)
    for key, value in source.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(value, result[key])
        else:
            result[key] = copy.deepcopy(value)
    return result
