"""Environment variable override support.

Maps NACHO_DATABASE_HOST → database.host (or a user-configured prefix/delimiter).
"""

from __future__ import annotations

import ast
import json
import logging
import os
from typing import Any, Dict, List, Optional, Tuple

from .utils.path import get_nested_value, set_nested_value

logger = logging.getLogger(__name__)

# System variables to skip when operating prefix-free.
_SYSTEM_VARS = frozenset({"_", "PATH", "HOME", "USER", "SHELL", "TERM", "LANG", "PWD"})


def _parse_value(raw: str) -> Any:
    """Best-effort parse of an env var string to a Python type."""
    if not raw:
        return ""
    low = raw.lower()
    if low in ("true", "yes", "1", "on"):
        return True
    if low in ("false", "no", "0", "off"):
        return False
    if low in ("null", "none", "~"):
        return None
    try:
        return ast.literal_eval(raw)
    except (ValueError, SyntaxError):
        pass
    if raw.startswith(("{", "[")):
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
        create_missing: bool = True,
    ) -> None:
        self.prefix = prefix.rstrip("_") if prefix else ""
        self.delimiter = nested_delimiter
        self.include = list(include_paths or [])
        self.exclude = list(exclude_paths or [])
        self.create_missing = create_missing
        self._prefix_with_sep = f"{self.prefix}{self.delimiter}" if self.prefix else ""

        if not self.prefix:
            logger.warning(
                "EnvOverrideHandler has no prefix — collisions with system variables are possible."
            )

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
            _MISSING = object()
            if not self.create_missing and get_nested_value(result, key, _MISSING) is _MISSING:
                continue
            if set_nested_value(result, key, _parse_value(raw)):
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
        if self.prefix:
            if not name.startswith(self._prefix_with_sep):
                return None
            tail = name[len(self._prefix_with_sep) :]
        else:
            if name in _SYSTEM_VARS or name.upper().startswith(("UV_", "PYTEST_", "PYTHON")):
                return None
            tail = name

        if not tail or tail.startswith(self.delimiter) or tail.endswith(self.delimiter):
            return None
        if self.delimiter * 2 in tail:
            return None

        return tail.replace(self.delimiter, ".").lower()

    def _allowed(self, key: str) -> bool:
        if any(key == p or key.startswith(f"{p}.") for p in self.exclude):
            return False
        if self.include:
            return any(key == p or key.startswith(f"{p}.") for p in self.include)
        return True
