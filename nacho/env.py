"""Environment variable override support.

Maps NACHO_DATABASE_HOST → database.host (or a user-configured prefix/delimiter).
A doubled delimiter nests while a single one stays part of the key, so
NACHO_DB__MAX_CONNECTIONS → db.max_connections.
"""

from __future__ import annotations

import ast
import json
import logging
import os
from typing import Any, Dict, List, Optional

from .utils.path import set_nested_value

logger = logging.getLogger(__name__)

# Shared truthy/falsy string sets (also used by Nacho.get_bool).
TRUTHY_STRINGS = frozenset({"true", "yes", "on"})
FALSY_STRINGS = frozenset({"false", "no", "off"})


def _parse_value(raw: str) -> Any:
    """Best-effort parse of an env var string to a Python type.

    Quoting a value ('8080' or "true") is the escape hatch that forces it
    to stay a string.
    """
    if not raw:
        return ""
    low = raw.lower()
    # "1"/"0" deliberately parse as integers below, not booleans.
    if low in TRUTHY_STRINGS:
        return True
    if low in FALSY_STRINGS:
        return False
    if low in ("null", "none", "~"):
        return None
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in ("'", '"'):
        return raw[1:-1]
    try:
        return int(raw)
    except ValueError:
        pass
    # Floats only when the text round-trips, so "3.10" stays a version string.
    try:
        parsed = float(raw)
        if str(parsed) == raw:
            return parsed
    except ValueError:
        pass
    if raw.startswith(("{", "[", "(")):
        try:
            return ast.literal_eval(raw)
        except (ValueError, SyntaxError):
            pass
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass
    return raw


class EnvOverrideHandler:
    """Applies matching environment variables on top of a config dict."""

    def __init__(
        self,
        prefix: str = "NACHO",
        nested_delimiter: str = "_",
        include_paths: Optional[List[str]] = None,
        exclude_paths: Optional[List[str]] = None,
    ) -> None:
        self.prefix = prefix.rstrip("_") if prefix else ""
        if not self.prefix:
            raise ValueError(
                "EnvOverrideHandler requires a non-empty prefix — scanning the whole "
                "environment would collide with system variables."
            )
        self.delimiter = nested_delimiter
        self.include = list(include_paths or [])
        self.exclude = list(exclude_paths or [])
        self._prefix_with_sep = f"{self.prefix}{self.delimiter}"

    def apply(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Return *data* with matching env vars overlaid (non-destructive copy)."""
        import copy

        result = copy.deepcopy(data)
        applied = 0
        for name, raw in os.environ.items():
            key = self._to_key(name)
            if key is None:
                continue
            if not self._allowed(key):
                continue
            try:
                changed = set_nested_value(result, key, _parse_value(raw))
            except ValueError as exc:
                # An overlay conflict (e.g. the config holds a scalar where
                # the env var implies nesting) must not crash the app.
                logger.warning("Skipping env override %s: %s", name, exc)
                continue
            if changed:
                logger.debug("Env override: %s → %s = %r", name, key, raw)
                applied += 1
        if applied:
            logger.debug("Applied %d env override(s)", applied)
        return result

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _to_key(self, name: str) -> Optional[str]:
        """Convert an env var name to a dot-notation config key, or None to skip."""
        if not name.startswith(self._prefix_with_sep):
            return None
        tail = name[len(self._prefix_with_sep) :]

        if not tail or tail.startswith(self.delimiter) or tail.endswith(self.delimiter):
            return None

        double = self.delimiter * 2
        if double in tail:
            # Doubled delimiter nests, single stays in the key:
            # NACHO_DB__MAX_CONNECTIONS → db.max_connections
            parts = tail.split(double)
            if any(
                not p or p.startswith(self.delimiter) or p.endswith(self.delimiter) for p in parts
            ):
                return None
            return ".".join(parts).lower()

        return tail.replace(self.delimiter, ".").lower()

    def _allowed(self, key: str) -> bool:
        if any(key == p or key.startswith(f"{p}.") for p in self.exclude):
            return False
        if self.include:
            return any(key == p or key.startswith(f"{p}.") for p in self.include)
        return True
