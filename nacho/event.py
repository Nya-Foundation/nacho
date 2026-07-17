"""Event system for Nacho.

Single file replacing six tightly-coupled modules.  The design follows three rules:
  1. Detect changes as a pure function (no side effects).
  2. Dispatch events through a simple priority queue of handlers.
  3. Async handlers are supported: they are scheduled on the running loop when
     called from an async context, or run on a shared background loop otherwise.
"""

from __future__ import annotations

import asyncio
import copy
import inspect
import logging
import threading
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set, Union

from .utils.path import (
    deep_merge,
    delete_nested_value,
    get_nested_value,
    parse_path,
    set_nested_value,
)

logger = logging.getLogger(__name__)


def _log_task_result(task: asyncio.Task) -> None:
    try:
        task.result()
    except asyncio.CancelledError:
        pass
    except Exception:
        logger.error("Async event handler raised", exc_info=True)


class _AsyncEventRunner:
    """Runs async handlers for synchronous callers on one background loop."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._ready: Optional[threading.Event] = None

    def run(self, coro: Any) -> None:
        loop = self._ensure_loop()
        future = asyncio.run_coroutine_threadsafe(coro, loop)
        future.result()

    def _ensure_loop(self) -> asyncio.AbstractEventLoop:
        with self._lock:
            if self._loop is not None and self._loop.is_running():
                return self._loop

            if self._ready is not None and self._thread is not None and self._thread.is_alive():
                ready = self._ready
            else:
                ready = threading.Event()
                self._ready = ready

                def run_loop() -> None:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    with self._lock:
                        self._loop = loop
                    ready.set()
                    loop.run_forever()

                self._thread = threading.Thread(
                    target=run_loop,
                    name="nacho-events",
                    daemon=True,
                )
                self._thread.start()

        ready.wait()
        with self._lock:
            return self._loop  # type: ignore[return-value]


_async_runner = _AsyncEventRunner()


# ---------------------------------------------------------------------------
# Event types
# ---------------------------------------------------------------------------


class EventType(Enum):
    CHANGE = "change"  # always emitted alongside CREATE / UPDATE / DELETE
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
    RELOAD = "reload"  # full config reload from storage


# ---------------------------------------------------------------------------
# Change detection
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Change:
    type: EventType
    path: Optional[str]  # None → global (aggregate) event
    old_value: Any
    new_value: Any


def detect_changes(old: Dict[str, Any], new: Dict[str, Any]) -> List[Change]:
    """Return a flat list of Changes between two config snapshots.

    Always starts with one aggregate CHANGE (path=None) so that listeners
    can react to *any* mutation without enumerating every leaf.
    """
    if old == new:
        return []

    changes: List[Change] = [Change(EventType.CHANGE, None, old, new)]
    _walk(old, new, "", changes)
    return changes


def _walk(
    old: Any,
    new: Any,
    prefix: str,
    out: List[Change],
) -> None:
    old_keys: Set[str] = set(old) if isinstance(old, dict) else set()
    new_keys: Set[str] = set(new) if isinstance(new, dict) else set()

    for key in old_keys - new_keys:
        path = f"{prefix}.{key}" if prefix else key
        out.append(Change(EventType.DELETE, path, old[key], None))
        out.append(Change(EventType.CHANGE, path, old[key], None))

    for key in new_keys - old_keys:
        path = f"{prefix}.{key}" if prefix else key
        out.append(Change(EventType.CREATE, path, None, new[key]))
        out.append(Change(EventType.CHANGE, path, None, new[key]))

    for key in old_keys & new_keys:
        path = f"{prefix}.{key}" if prefix else key
        ov, nv = old[key], new[key]
        if ov == nv:
            continue
        if isinstance(ov, dict) and isinstance(nv, dict):
            _walk(ov, nv, path, out)
        else:
            out.append(Change(EventType.UPDATE, path, ov, nv))
            out.append(Change(EventType.CHANGE, path, ov, nv))


# ---------------------------------------------------------------------------
# Path matching
# ---------------------------------------------------------------------------


def _match_path(pattern: Optional[str], path: Optional[str]) -> bool:
    """Return True when *path* matches *pattern*.

    Patterns:
      None            → match any event regardless of path (no filter)
      "@global"       → match only the aggregate event (path=None), fires once per operation
      "*"             → match every per-path event (not the aggregate)
      "database.*"    → match any path whose first segment is "database"
      "database.host" → exact match only
    """
    if pattern is None:
        return True  # no filter — match everything
    if pattern == "@global":
        return path is None
    if path is None:
        return False  # path-specific patterns never match aggregate events
    if pattern == "*":
        return True
    if pattern == path:
        return True

    p_segs = parse_path(pattern)
    r_segs = parse_path(path)

    if pattern.endswith(".*"):
        prefix = p_segs[:-1]
        # Must have MORE segments than the prefix — "db.*" matches "db.host" not "db"
        return len(r_segs) > len(prefix) and _segs_match(prefix, r_segs[: len(prefix)])

    if len(p_segs) != len(r_segs):
        return False
    return _segs_match(p_segs, r_segs)


def _segs_match(pattern_segs: List[str], path_segs: List[str]) -> bool:
    return all(ps == "*" or ps == rs for ps, rs in zip(pattern_segs, path_segs))


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------


class EventHandler:
    """Wraps a user callback with its matching criteria."""

    def __init__(
        self,
        callback: Callable,
        event_types: Set[EventType],
        path_pattern: Optional[str],
        priority: int,
    ) -> None:
        if not callable(callback):
            raise TypeError(f"callback must be callable, got {type(callback).__name__!r}")
        self.callback = callback
        self.event_types = event_types
        self.path_pattern = path_pattern
        self.priority = priority
        self.is_async = inspect.iscoroutinefunction(callback) or (
            hasattr(callback, "__call__") and inspect.iscoroutinefunction(callback.__call__)
        )

    def matches(self, change: Change) -> bool:
        if change.type not in self.event_types:
            return False
        return _match_path(self.path_pattern, change.path)

    def invoke(self, change: Change, config_data: Dict[str, Any]) -> None:
        kwargs = {
            "event_type": change.type,
            "path": change.path,
            "old_value": copy.deepcopy(change.old_value),
            "new_value": copy.deepcopy(change.new_value),
            "config_data": copy.deepcopy(config_data),
        }
        try:
            if self.is_async:
                coro = self.callback(**kwargs)
                try:
                    loop = asyncio.get_running_loop()
                    task = loop.create_task(coro)
                    task.add_done_callback(_log_task_result)
                except RuntimeError:
                    _async_runner.run(coro)
            else:
                self.callback(**kwargs)
        except Exception:
            # getattr: functools.partial and callable objects have no __name__.
            logger.error(
                "Handler %r raised",
                getattr(self.callback, "__name__", repr(self.callback)),
                exc_info=True,
            )


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


class EventPipeline:
    """Ordered collection of EventHandlers with priority-based dispatch."""

    def __init__(self) -> None:
        self._handlers: List[EventHandler] = []
        self._lock = threading.RLock()

    def register(
        self,
        callback: Callable,
        event_types: Union[EventType, List[EventType]],
        path_pattern: Optional[str] = None,
        priority: int = 100,
    ) -> EventHandler:
        if isinstance(event_types, EventType):
            event_types = {event_types}
        else:
            event_types = set(event_types)

        handler = EventHandler(callback, event_types, path_pattern, priority)
        with self._lock:
            self._handlers.append(handler)
            self._handlers.sort(key=lambda h: h.priority)
        logger.debug(
            "Registered handler %r for %s%s",
            getattr(callback, "__name__", repr(callback)),
            [e.value for e in event_types],
            f" on {path_pattern!r}" if path_pattern is not None else "",
        )
        return handler

    # Kept for backward compat with server code that calls register_handler
    def register_handler(
        self,
        callback: Callable,
        event_types: Union[EventType, List[EventType]],
        path_pattern: Optional[str] = None,
        priority: int = 100,
    ) -> EventHandler:
        return self.register(callback, event_types, path_pattern, priority)

    def unregister(self, handler: EventHandler) -> bool:
        with self._lock:
            try:
                self._handlers.remove(handler)
                return True
            except ValueError:
                return False

    def dispatch(self, changes: List[Change], config_data: Dict[str, Any]) -> None:
        """Invoke matching handlers for each change in *changes*."""
        with self._lock:
            handlers = list(self._handlers)
        for change in changes:
            for handler in handlers:
                if handler.matches(change):
                    handler.invoke(change, config_data)

    # Kept for backward compat with server code that calls pipeline.emit()
    def emit(
        self,
        event_type: EventType,
        path: Optional[str] = None,
        old_value: Any = None,
        new_value: Any = None,
        config_data: Optional[Dict[str, Any]] = None,
        ignore: bool = False,
    ) -> int:
        if ignore:
            return 0
        change = Change(event_type, path, old_value, new_value)
        count = 0
        with self._lock:
            handlers = list(self._handlers)
        for handler in handlers:
            if handler.matches(change):
                handler.invoke(change, config_data or {})
                count += 1
        return count


# ---------------------------------------------------------------------------
# Decorator helpers
# ---------------------------------------------------------------------------


def on_event(
    pipeline: EventPipeline,
    event_type: Union[EventType, List[EventType]],
    path_pattern: Optional[str] = None,
    priority: int = 100,
) -> Callable:
    def decorator(func: Callable) -> Callable:
        pipeline.register(func, event_type, path_pattern, priority)
        return func

    return decorator


def on_change(
    pipeline: EventPipeline,
    path_pattern: Optional[str] = None,
    priority: int = 100,
) -> Callable:
    return on_event(pipeline, EventType.CHANGE, path_pattern, priority)


# ---------------------------------------------------------------------------
# Transaction
# ---------------------------------------------------------------------------


class Transaction:
    """Accumulates mutations in a scratch copy; commits atomically."""

    def __init__(self, config: "Any") -> None:
        self._config = config
        self._data: Dict[str, Any] = copy.deepcopy(config._stored_data)

    def get(self, key: Optional[str] = None, default: Any = None) -> Any:
        if key is None:
            return self._data
        return get_nested_value(self._data, key, default)

    def set(self, key: str, value: Any) -> None:
        set_nested_value(self._data, key, value)

    def delete(self, key: str) -> bool:
        ok, _ = delete_nested_value(self._data, key)
        return ok

    def update(self, data: Dict[str, Any]) -> None:
        self._data = deep_merge(data, self._data)

    def replace(self, data: Dict[str, Any]) -> None:
        self._data = copy.deepcopy(data)

    def commit(self) -> List[Change]:
        with self._config._lock:
            old = copy.deepcopy(self._config._data)
            candidate_stored = copy.deepcopy(self._data)
            candidate = self._config._effective_from_stored(candidate_stored)
            self._config._validate(candidate)
            changes = detect_changes(old, candidate)
            self._config._stored_data = candidate_stored
            self._config._data = candidate
        if not self._config._events_disabled and changes:
            self._config._pipeline.dispatch(changes, copy.deepcopy(self._config._data))
        return changes
