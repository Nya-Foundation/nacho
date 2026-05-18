"""Nacho — schema-first dynamic configuration manager."""

from __future__ import annotations

import copy
import logging
import threading
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Union

from .env import EnvOverrideHandler
from .event import (
    Change,
    EventPipeline,
    EventType,
    Transaction,
    detect_changes,
    on_change,
    on_event,
)
from .schema import SchemaValidator
from .storage.base import StorageBackend, StorageError
from .storage.file import FileStorageBackend
from .utils.path import deep_merge, delete_nested_value, get_nested_value, set_nested_value

logger = logging.getLogger(__name__)

_UNCHANGED = object()


class Nacho:
    """Dynamic configuration manager with optional schema enforcement.

    Construction shortcuts::

        Nacho()                            # in-memory only
        Nacho({"key": "value"})            # in-memory with initial data
        Nacho("config.yaml")               # file-backed
        Nacho(storage=FileStorageBackend("config.yaml"))   # explicit backend
        Nacho(storage=RemoteStorageBackend("http://…"))    # remote

    Schema-first (raises ValidationError on invalid writes)::

        Nacho("config.yaml", schema="schema.json")
    """

    def __init__(
        self,
        storage: Optional[Union[StorageBackend, str, Path, Dict[str, Any]]] = None,
        *,
        schema: Optional[Union[str, Path, Dict[str, Any]]] = None,
        env_prefix: Optional[str] = None,
        env_delimiter: str = "_",
        env_include: Optional[List[str]] = None,
        env_exclude: Optional[List[str]] = None,
        read_only: bool = False,
        events: bool = False,
        allow_empty_on_load_error: bool = False,
    ) -> None:
        self._lock = threading.RLock()
        self._read_only = read_only
        self._events_disabled = not events
        self._allow_empty_on_load_error = allow_empty_on_load_error
        self._pipeline = EventPipeline()

        self._validator: Optional[SchemaValidator] = self._init_validator(schema)
        self._env: Optional[EnvOverrideHandler] = self._init_env(
            env_prefix, env_delimiter, env_include, env_exclude
        )

        # _stored_data is the persistable config. _data is the effective view
        # after runtime overlays such as environment variables are applied.
        self._stored_data: Dict[str, Any] = {}
        self._data: Dict[str, Any] = {}
        self._storage: Optional[StorageBackend] = self._init_storage(storage)

        if self._storage is not None:
            self._storage.on_remote_change = self._on_remote_push

        self._load_initial()

    # ------------------------------------------------------------------
    # Construction helpers (private)
    # ------------------------------------------------------------------

    def _init_storage(
        self, raw: Optional[Union[StorageBackend, str, Path, Dict[str, Any]]]
    ) -> Optional[StorageBackend]:
        if raw is None:
            return None
        if isinstance(raw, StorageBackend):
            return raw
        if isinstance(raw, (str, Path)):
            return FileStorageBackend(raw)
        if isinstance(raw, dict):
            self._stored_data = copy.deepcopy(raw)
            return None
        raise TypeError(
            f"storage must be a StorageBackend, file path, or dict — got {type(raw).__name__!r}"
        )

    def _init_validator(
        self, schema: Optional[Union[str, Path, Dict[str, Any]]]
    ) -> Optional[SchemaValidator]:
        if schema is None:
            return None
        return SchemaValidator(schema)

    def _init_env(
        self,
        prefix: Optional[str],
        delimiter: str,
        include: Optional[List[str]],
        exclude: Optional[List[str]],
    ) -> Optional[EnvOverrideHandler]:
        if prefix is None:
            return None
        return EnvOverrideHandler(
            prefix=prefix,
            nested_delimiter=delimiter,
            include_paths=include,
            exclude_paths=exclude,
        )

    def _load_initial(self) -> None:
        if self._storage is None:
            # In-memory seed: still apply env overrides if configured.
            self._data = self._effective_from_stored(self._stored_data)
            self._validate(self._data)
            return
        try:
            raw = self._storage.load()
        except StorageError as exc:
            if not self._allow_empty_on_load_error:
                raise
            logger.error("Failed to load initial config; starting empty: %s", exc)
            raw = {}
        if not isinstance(raw, dict):
            raise StorageError(f"Storage backend returned {type(raw).__name__}, expected dict")
        self._stored_data = copy.deepcopy(raw)
        self._data = self._effective_from_stored(self._stored_data)
        self._validate(self._data)

    def _apply_env(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        if self._env is None:
            return copy.deepcopy(raw)
        return self._env.apply(raw)

    def _effective_from_stored(self, stored: Dict[str, Any]) -> Dict[str, Any]:
        return self._apply_env(stored)

    # ------------------------------------------------------------------
    # Remote push handler
    # ------------------------------------------------------------------

    def _on_remote_push(self, incoming: Dict[str, Any]) -> None:
        """Called by the remote storage backend when the server pushes a change."""
        self._force_replace(incoming)

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    def __enter__(self) -> "Nacho":
        return self

    def __exit__(self, *_: Any) -> None:
        self.cleanup()

    def cleanup(self) -> None:
        if self._storage:
            self._storage.cleanup()

    # ------------------------------------------------------------------
    # Read API
    # ------------------------------------------------------------------

    def get(self, key: Optional[str] = None, default: Any = None) -> Any:
        """Return the value at dot-notation *key*, or *default* if absent."""
        with self._lock:
            if key is None:
                return copy.deepcopy(self._data)
            return copy.deepcopy(get_nested_value(self._data, key, default))

    def get_all(self) -> Dict[str, Any]:
        with self._lock:
            return copy.deepcopy(self._data)

    def get_int(self, key: str, default: Optional[int] = None) -> Optional[int]:
        value = self.get(key, default)
        if value is None:
            return default
        try:
            return int(value)
        except (ValueError, TypeError):
            logger.warning("Cannot coerce %r to int for key %r", value, key)
            return default

    def get_float(self, key: str, default: Optional[float] = None) -> Optional[float]:
        value = self.get(key, default)
        if value is None:
            return default
        try:
            return float(value)
        except (ValueError, TypeError):
            logger.warning("Cannot coerce %r to float for key %r", value, key)
            return default

    def get_bool(self, key: str, default: Optional[bool] = None) -> Optional[bool]:
        value = self.get(key, default)
        if value is None:
            return default
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            if value.lower() in ("true", "yes", "1", "on"):
                return True
            if value.lower() in ("false", "no", "0", "off"):
                return False
        try:
            return bool(int(value))
        except (ValueError, TypeError):
            logger.warning("Cannot coerce %r to bool for key %r", value, key)
            return default

    def get_str(self, key: str, default: Optional[str] = None) -> Optional[str]:
        value = self.get(key, default)
        return str(value) if value is not None else default

    def get_list(self, key: str, default: Optional[List] = None) -> Optional[List]:
        value = self.get(key, default)
        if value is None:
            return default
        if isinstance(value, list):
            return value
        logger.warning("Value for %r is not a list", key)
        return default

    def get_dict(self, key: str, default: Optional[Dict] = None) -> Optional[Dict]:
        value = self.get(key, default)
        if value is None:
            return default
        if isinstance(value, dict):
            return value
        logger.warning("Value for %r is not a dict", key)
        return default

    # ------------------------------------------------------------------
    # Write API
    # ------------------------------------------------------------------

    def set(self, key: str, value: Any) -> bool:
        """Set *key* to *value*.

        Returns True when something actually changed.
        Validates against schema before applying when a schema is configured.
        Raises ValidationError if the resulting config would be invalid.
        Raises PermissionError when the instance is read-only.
        """
        self._check_writable()
        with self._lock:
            candidate_stored = copy.deepcopy(self._stored_data)
            if not set_nested_value(candidate_stored, key, value):
                return False
            candidate = self._effective_from_stored(candidate_stored)
            self._validate(candidate)
            old = copy.deepcopy(self._data)
            self._stored_data = candidate_stored
            self._data = candidate
        self._emit(detect_changes(old, self._data))
        return True

    def delete(self, key: str) -> bool:
        """Remove *key* from the config.  Returns True if the key existed."""
        self._check_writable()
        with self._lock:
            _MISSING = object()
            if get_nested_value(self._stored_data, key, _MISSING) is _MISSING:
                return False
            old = copy.deepcopy(self._data)
            candidate_stored = copy.deepcopy(self._stored_data)
            delete_nested_value(candidate_stored, key)
            candidate = self._effective_from_stored(candidate_stored)
            self._validate(candidate)
            self._stored_data = candidate_stored
            self._data = candidate
        self._emit(detect_changes(old, self._data))
        return True

    def update(self, data: Dict[str, Any]) -> bool:
        """Deep-merge *data* into the current config.

        Returns True when something actually changed.
        """
        self._check_writable()
        if not data:
            return False
        with self._lock:
            candidate_stored = deep_merge(data, self._stored_data)
            candidate = self._effective_from_stored(candidate_stored)
            if candidate_stored == self._stored_data and candidate == self._data:
                return False
            self._validate(candidate)
            old = copy.deepcopy(self._data)
            self._stored_data = candidate_stored
            self._data = candidate
        self._emit(detect_changes(old, self._data))
        return True

    def replace(
        self,
        data: Dict[str, Any],
        *,
        schema: object = _UNCHANGED,
    ) -> bool:
        """Replace the entire config with *data*.

        Returns True when something actually changed.
        Raises PermissionError for read-only instances.
        """
        self._check_writable()
        return self._force_replace(data, schema=schema)

    def _force_replace(self, data: Dict[str, Any], *, schema: object = _UNCHANGED) -> bool:
        """Replace without the read-only check (used by remote push)."""
        if not isinstance(data, dict):
            raise TypeError(f"replace() expects a dict, got {type(data).__name__!r}")
        if schema is _UNCHANGED:
            validator = self._validator
        else:
            validator = self._init_validator(schema)  # type: ignore[arg-type]

        with self._lock:
            candidate_stored = copy.deepcopy(data)
            candidate = self._effective_from_stored(candidate_stored)
            self._validate_with(candidate, validator)
            schema_changed = schema is not _UNCHANGED
            if (
                candidate_stored == self._stored_data
                and candidate == self._data
                and not schema_changed
            ):
                return False
            old = copy.deepcopy(self._data)
            self._validator = validator
            self._stored_data = candidate_stored
            self._data = candidate
        self._emit(detect_changes(old, self._data))
        return True

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def load(self) -> Dict[str, Any]:
        """Reload from storage and apply env overrides.  Emits RELOAD event."""
        if self._storage is None:
            with self._lock:
                return copy.deepcopy(self._data)
        try:
            raw = self._storage.load()
        except StorageError as exc:
            if not self._allow_empty_on_load_error:
                raise
            logger.error("Reload failed; keeping current config: %s", exc)
            with self._lock:
                return copy.deepcopy(self._data)

        with self._lock:
            old = copy.deepcopy(self._data)
            if not isinstance(raw, dict):
                raise StorageError(f"Storage backend returned {type(raw).__name__}, expected dict")
            candidate_stored = copy.deepcopy(raw)
            candidate = self._effective_from_stored(candidate_stored)
            self._validate(candidate)
            self._stored_data = candidate_stored
            self._data = candidate

        changes = detect_changes(old, self._data)
        if not self._events_disabled:
            snapshot = copy.deepcopy(self._data)
            reload_change = Change(EventType.RELOAD, None, old, snapshot)
            self._pipeline.dispatch([reload_change], snapshot)
            if changes:
                self._pipeline.dispatch(changes, snapshot)
        return copy.deepcopy(self._data)

    reload = load  # alias

    def save(self) -> None:
        """Persist current in-memory config to storage.

        Raises PermissionError for read-only instances.
        Raises StorageError on backend failure.
        """
        self._check_writable()
        if self._storage is None:
            return
        with self._lock:
            data = copy.deepcopy(self._stored_data)
        self._storage.save(data)
        logger.debug("Config saved via %s", self._storage)

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

    def validate(self) -> List[str]:
        """Return a list of schema violation strings (empty = valid).

        Does not raise — use this when you want to inspect errors without
        catching an exception.
        """
        if self._validator is None:
            return []
        with self._lock:
            data = copy.deepcopy(self._data)
        return self._validator.check(data)

    # ------------------------------------------------------------------
    # Transactions
    # ------------------------------------------------------------------

    def transaction(self) -> "_TransactionContext":
        """Return a context manager for atomic multi-key updates.

        Example::
            with config.transaction() as txn:
                txn.set("db.host", "localhost")
                txn.set("db.port", 5432)
            config.save()
        """
        return _TransactionContext(self)

    # ------------------------------------------------------------------
    # Event decorators
    # ------------------------------------------------------------------

    def on_change(self, path_pattern: Optional[str] = None, priority: int = 100) -> Callable:
        """Decorator: register a handler for CHANGE events matching *path_pattern*.

        ``path_pattern=None`` (default) — fires for any CHANGE at any path.
        ``path_pattern="@global"``       — fires exactly once per mutation (aggregate event).
        ``path_pattern="*"``             — fires for every per-path CHANGE (not aggregate).
        ``path_pattern="database.*"``    — fires for any key under ``database``.
        """
        return on_change(self._pipeline, path_pattern, priority)

    def on_event(
        self,
        event_type: Union[EventType, List[EventType]],
        path_pattern: Optional[str] = None,
        priority: int = 100,
    ) -> Callable:
        """Decorator: register a handler for specific *event_type*(s)."""
        return on_event(self._pipeline, event_type, path_pattern, priority)

    # ------------------------------------------------------------------
    # Schema helpers
    # ------------------------------------------------------------------

    def check(self, data: Dict[str, Any]) -> List[str]:
        """Return schema violation strings for *data* without applying it."""
        if self._validator is None:
            return []
        return self._validator.check(data)

    # ------------------------------------------------------------------
    # Backward-compat properties (used by server layer)
    # ------------------------------------------------------------------

    @property
    def data(self) -> Dict[str, Any]:
        """Return a defensive copy of the effective configuration.

        ``data`` is kept as a read-only compatibility property. Mutating the
        returned dict never changes the live configuration; use ``set()``,
        ``update()``, ``replace()``, or ``delete()`` for writes.
        """
        return self.get_all()

    @property
    def event_pipeline(self) -> EventPipeline:
        return self._pipeline

    @property
    def event_disabled(self) -> bool:
        return self._events_disabled

    # ------------------------------------------------------------------
    # json helper
    # ------------------------------------------------------------------

    def json(self) -> str:
        import json as _json

        with self._lock:
            return _json.dumps(self._data, indent=2, ensure_ascii=False)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _check_writable(self) -> None:
        if self._read_only:
            raise PermissionError("This Nacho instance is read-only.")

    def _validate(self, data: Dict[str, Any]) -> None:
        self._validate_with(data, self._validator)

    def _validate_with(
        self,
        data: Dict[str, Any],
        validator: Optional[SchemaValidator],
    ) -> None:
        if validator is not None:
            validator.validate(data)  # raises ValidationError

    def _emit(self, changes: List[Change]) -> None:
        if self._events_disabled or not changes:
            return
        with self._lock:
            snapshot = copy.deepcopy(self._data)
        self._pipeline.dispatch(changes, snapshot)


# ---------------------------------------------------------------------------
# Transaction context manager
# ---------------------------------------------------------------------------


class _TransactionContext:
    def __init__(self, config: Nacho) -> None:
        self._config = config

    def __enter__(self) -> Transaction:
        self._config._check_writable()
        self._txn = Transaction(self._config)
        return self._txn

    def __exit__(self, exc_type: Any, *_: Any) -> bool:
        if exc_type is None:
            self._txn.commit()
        return False  # never suppress exceptions
