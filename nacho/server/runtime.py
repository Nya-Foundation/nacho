"""Runtime state for the Nacho API server."""

from __future__ import annotations

import asyncio
import copy
import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, Iterable, List, Optional

from fastapi import WebSocket

from nacho.config import Nacho
from nacho.utils.io import load_file, save_file

from .models import validate_app_name


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class RevisionConflictError(RuntimeError):
    """Raised when a write targets an older app revision."""

    def __init__(self, expected: int, actual: int) -> None:
        self.expected = expected
        self.actual = actual
        super().__init__(f"Revision conflict: expected {expected}, current revision is {actual}")


class WebSocketHub:
    """Tracks WebSocket subscribers for one app."""

    def __init__(self, app_name: str, logger: logging.Logger) -> None:
        self.app_name = app_name
        self.logger = logger
        self._connections: List[WebSocket] = []
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._lock = threading.RLock()

    @property
    def count(self) -> int:
        with self._lock:
            return len(self._connections)

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        with self._lock:
            self._loop = asyncio.get_running_loop()
            self._connections.append(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        with self._lock:
            if websocket in self._connections:
                self._connections.remove(websocket)
            if not self._connections:
                self._loop = None

    async def broadcast(self, message: Dict[str, Any]) -> None:
        stale: List[WebSocket] = []
        with self._lock:
            connections = list(self._connections)

        for websocket in connections:
            try:
                await websocket.send_json(message)
            except Exception as exc:
                self.logger.warning("WebSocket send failed for %s: %s", self.app_name, exc)
                stale.append(websocket)
        for websocket in stale:
            self.disconnect(websocket)

    def schedule(self, callback: Callable[[], Awaitable[None]]) -> None:
        """Schedule async WebSocket work on the connection loop when clients exist."""
        with self._lock:
            loop = self._loop
            has_connections = bool(self._connections)
        if loop is None or not has_connections:
            return
        if loop.is_closed():
            return
        try:
            asyncio.run_coroutine_threadsafe(callback(), loop)
        except RuntimeError as exc:
            self.logger.warning(
                "WebSocket broadcast scheduling failed for %s: %s", self.app_name, exc
            )

    def close_all(self) -> None:
        with self._lock:
            loop = self._loop
            connections = list(self._connections)
            self._connections.clear()
            self._loop = None

        if loop is None or loop.is_closed():
            return
        for websocket in connections:
            try:
                asyncio.run_coroutine_threadsafe(websocket.close(), loop)
            except RuntimeError:
                pass


@dataclass
class ConfigApp:
    """A managed app plus API metadata."""

    name: str
    config: Nacho
    description: Optional[str] = None
    schema: Optional[Dict[str, Any]] = None
    logger: logging.Logger = field(default_factory=lambda: logging.getLogger(__name__))
    revision: int = 1
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        self.hub = WebSocketHub(self.name, self.logger)

    def broadcast_update(self) -> None:
        self.hub.schedule(self._broadcast_update)

    async def _broadcast_update(self) -> None:
        await self.hub.broadcast(
            {
                "type": "update",
                "app": self.name,
                "revision": self.revision,
                "data": self.config.get_all(),
            }
        )

    @property
    def info(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "revision": self.revision,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "config_count": len(self.config.get_all()),
            "connections": self.hub.count,
            "schema": self.schema is not None,
        }

    def touch(self) -> None:
        self.revision += 1
        self.updated_at = utc_now()

    def snapshot(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "revision": self.revision,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "schema": copy.deepcopy(self.schema),
            "config": self.config.get_all(),
        }

    def cleanup(self) -> None:
        self.config.cleanup()
        self.hub.close_all()


class AppStore:
    """Simple durable app store backed by one JSON file per app."""

    def __init__(self, data_dir: Optional[Path]) -> None:
        self.data_dir = Path(data_dir) if data_dir else None
        if self.data_dir:
            self.data_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, name: str) -> Path:
        if self.data_dir is None:
            raise RuntimeError("AppStore has no data directory")
        validate_app_name(name)
        return self.data_dir / f"{name}.json"

    def load(self) -> Iterable[Dict[str, Any]]:
        if self.data_dir is None:
            return []
        apps = []
        for path in sorted(self.data_dir.glob("*.json")):
            data = load_file(path)
            if data:
                apps.append(data)
        return apps

    def save(self, app: ConfigApp) -> None:
        if self.data_dir is None:
            return
        save_file(self._path(app.name), app.snapshot())

    def delete(self, name: str) -> None:
        if self.data_dir is None:
            return
        self._path(name).unlink(missing_ok=True)


class AppManager:
    """Owns managed apps and persistence."""

    def __init__(
        self,
        *,
        data_dir: Optional[Path] = None,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self.logger = logger or logging.getLogger(__name__)
        self.store = AppStore(data_dir)
        self._apps: Dict[str, ConfigApp] = {}
        self._lock = threading.RLock()

    @property
    def apps(self) -> Dict[str, ConfigApp]:
        with self._lock:
            return dict(self._apps)

    def load_persisted(self) -> None:
        for raw in self.store.load():
            name = raw.get("name")
            if not isinstance(name, str):
                continue
            config_data = raw.get("config") or {}
            schema = raw.get("schema")
            app = ConfigApp(
                name=name,
                config=Nacho(config_data, schema=schema, events=True),
                description=raw.get("description"),
                schema=schema,
                logger=self.logger,
                revision=int(raw.get("revision") or 1),
                created_at=raw.get("created_at") or utc_now(),
                updated_at=raw.get("updated_at") or utc_now(),
            )
            self._apps[name] = app

    def create(
        self,
        name: str,
        *,
        config_data: Optional[Dict[str, Any]] = None,
        config: Optional[Nacho] = None,
        description: Optional[str] = None,
        schema: Optional[Dict[str, Any]] = None,
        replace: bool = False,
    ) -> ConfigApp:
        validate_app_name(name)
        with self._lock:
            if name in self._apps and not replace:
                raise ValueError(f"App {name!r} already exists")
            if name in self._apps:
                self._apps[name].cleanup()

            app_config = config or Nacho(config_data or {}, schema=schema, events=True)
            app = ConfigApp(
                name=name,
                config=app_config,
                description=description,
                schema=schema,
                logger=self.logger,
            )
            self._apps[name] = app
            self.store.save(app)
            return app

    def replace(
        self,
        current_name: str,
        *,
        new_name: str,
        config_data: Dict[str, Any],
        description: Optional[str] = None,
        schema: Optional[Dict[str, Any]] = None,
        expected_revision: Optional[int] = None,
    ) -> ConfigApp:
        validate_app_name(new_name)
        with self._lock:
            current = self._require_app(current_name)
            self._check_revision(current, expected_revision)
            if new_name != current_name and new_name in self._apps:
                raise ValueError(f"App {new_name!r} already exists")

            target_schema = schema if schema is not None else current.schema
            config_changed = current.config.replace(config_data, schema=target_schema)
            metadata_changed = (
                new_name != current_name
                or description != current.description
                or target_schema != current.schema
            )

            if new_name != current_name:
                del self._apps[current_name]
                current.name = new_name
                current.hub.app_name = new_name
                self._apps[new_name] = current

            current.description = description
            current.schema = copy.deepcopy(target_schema)
            if config_changed or metadata_changed:
                current.touch()
            self.store.save(current)
            if new_name != current_name:
                self.store.delete(current_name)
            return current

    def get(self, name: str) -> Optional[ConfigApp]:
        with self._lock:
            return self._apps.get(name)

    def list_info(self) -> Dict[str, Dict[str, Any]]:
        with self._lock:
            return {name: app.info for name, app in self._apps.items()}

    def rename(
        self,
        current_name: str,
        *,
        new_name: Optional[str] = None,
        description: Optional[str] = None,
        expected_revision: Optional[int] = None,
    ) -> ConfigApp:
        with self._lock:
            app = self._apps.get(current_name)
            if app is None:
                raise KeyError(current_name)
            self._check_revision(app, expected_revision)
            if description is not None:
                app.description = description

            if new_name and new_name != current_name:
                validate_app_name(new_name)
                if new_name in self._apps:
                    raise ValueError(f"App {new_name!r} already exists")
                del self._apps[current_name]
                self.store.delete(current_name)
                app.name = new_name
                app.hub.app_name = new_name
                self._apps[new_name] = app

            app.touch()
            self.store.save(app)
            return app

    def persist(self, app: ConfigApp, *, changed: bool = True, notify: bool = False) -> None:
        should_notify = False
        with self._lock:
            if changed:
                app.config.save()
                app.touch()
                should_notify = notify
            self.store.save(app)
        if should_notify:
            app.broadcast_update()

    def replace_config(
        self,
        name: str,
        data: Dict[str, Any],
        *,
        expected_revision: Optional[int] = None,
    ) -> ConfigApp:
        with self._lock:
            app = self._require_app(name)
            self._check_revision(app, expected_revision)
            changed = app.config.replace(data)
            self.persist(app, changed=changed, notify=True)
            return app

    def update_schema(
        self,
        name: str,
        schema: Optional[Dict[str, Any]],
        *,
        expected_revision: Optional[int] = None,
    ) -> ConfigApp:
        """Replace an app's schema; *schema* of ``None`` clears it.

        Re-validates the current configuration against the new schema —
        ``replace()`` raises ValidationError if the config would become invalid.
        """
        with self._lock:
            app = self._require_app(name)
            self._check_revision(app, expected_revision)
            app.config.replace(app.config.get_all(), schema=schema)
            app.schema = copy.deepcopy(schema)
            self.persist(app, changed=True, notify=True)
            return app

    def set_config_path(
        self,
        name: str,
        path: str,
        value: Any,
        *,
        expected_revision: Optional[int] = None,
    ) -> bool:
        with self._lock:
            app = self._require_app(name)
            self._check_revision(app, expected_revision)
            changed = app.config.set(path, value)
            self.persist(app, changed=changed, notify=True)
            return changed

    def delete_config_path(
        self,
        name: str,
        path: str,
        *,
        expected_revision: Optional[int] = None,
    ) -> bool:
        with self._lock:
            app = self._require_app(name)
            self._check_revision(app, expected_revision)
            deleted = app.config.delete(path)
            if deleted:
                self.persist(app, changed=True, notify=True)
            return deleted

    def delete(self, name: str) -> bool:
        with self._lock:
            app = self._apps.pop(name, None)
            if app is None:
                return False
            app.cleanup()
            self.store.delete(name)
            return True

    def cleanup(self) -> None:
        with self._lock:
            apps = list(self._apps.values())
            self._apps.clear()
        for app in apps:
            app.cleanup()

    def _require_app(self, name: str) -> ConfigApp:
        app = self._apps.get(name)
        if app is None:
            raise KeyError(name)
        return app

    def _check_revision(self, app: ConfigApp, expected_revision: Optional[int]) -> None:
        if expected_revision is None:
            return
        if expected_revision != app.revision:
            raise RevisionConflictError(expected_revision, app.revision)
