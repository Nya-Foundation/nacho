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


class HistoryStore:
    """Ring buffer of per-app revision snapshots.

    Disk-backed when a data directory is configured (one JSON file per
    revision under ``data_dir/history/{app}/``), in-memory otherwise.
    A ``limit`` of 0 disables history entirely.
    """

    def __init__(self, data_dir: Optional[Path], limit: int = 50) -> None:
        self.limit = limit
        self.dir = Path(data_dir) / "history" if data_dir else None
        self._mem: Dict[str, Dict[int, Dict[str, Any]]] = {}

    @property
    def enabled(self) -> bool:
        return self.limit > 0

    def _app_dir(self, name: str) -> Path:
        validate_app_name(name)
        return self.dir / name  # type: ignore[operator]

    def record(self, snapshot: Dict[str, Any]) -> None:
        """Store *snapshot* under its revision and prune beyond the limit."""
        if not self.enabled:
            return
        name = snapshot["name"]
        revision = int(snapshot["revision"])
        if self.dir is None:
            revisions = self._mem.setdefault(name, {})
            revisions[revision] = copy.deepcopy(snapshot)
            for old in sorted(revisions)[: -self.limit]:
                del revisions[old]
            return
        app_dir = self._app_dir(name)
        save_file(app_dir / f"{revision:08d}.json", snapshot)
        files = sorted(app_dir.glob("*.json"))
        for stale in files[: -self.limit]:
            stale.unlink(missing_ok=True)

    def list(self, name: str) -> List[Dict[str, Any]]:
        """Return snapshot metadata, newest first (no config payloads)."""
        entries = []
        for snapshot in self._iter_snapshots(name):
            entries.append(
                {
                    "revision": snapshot["revision"],
                    "updated_at": snapshot.get("updated_at"),
                    "config_count": len(snapshot.get("config") or {}),
                    "schema": snapshot.get("schema") is not None,
                }
            )
        return sorted(entries, key=lambda e: e["revision"], reverse=True)

    def get(self, name: str, revision: int) -> Optional[Dict[str, Any]]:
        if self.dir is None:
            snapshot = self._mem.get(name, {}).get(revision)
            return copy.deepcopy(snapshot) if snapshot else None
        path = self._app_dir(name) / f"{revision:08d}.json"
        if not path.exists():
            return None
        return load_file(path) or None

    def delete(self, name: str) -> None:
        self._mem.pop(name, None)
        if self.dir is None:
            return
        app_dir = self._app_dir(name)
        if app_dir.is_dir():
            for path in app_dir.glob("*.json"):
                path.unlink(missing_ok=True)
            try:
                app_dir.rmdir()
            except OSError:
                pass

    def rename(self, old: str, new: str) -> None:
        if old in self._mem:
            self._mem[new] = self._mem.pop(old)
        if self.dir is None:
            return
        old_dir = self._app_dir(old)
        if old_dir.is_dir():
            old_dir.rename(self._app_dir(new))

    def _iter_snapshots(self, name: str):
        if self.dir is None:
            yield from self._mem.get(name, {}).values()
            return
        app_dir = self._app_dir(name)
        if not app_dir.is_dir():
            return
        for path in sorted(app_dir.glob("*.json")):
            data = load_file(path)
            if data:
                yield data


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
            try:
                data = load_file(path)
            except (OSError, ValueError) as exc:
                # One corrupt file must not take the whole service down.
                logging.getLogger(__name__).error("Skipping unreadable app file %s: %s", path, exc)
                continue
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
        history_limit: int = 50,
    ) -> None:
        self.logger = logger or logging.getLogger(__name__)
        self.store = AppStore(data_dir)
        self.history = HistoryStore(data_dir, limit=history_limit)
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
            try:
                app = ConfigApp(
                    name=name,
                    config=Nacho(config_data, schema=schema),
                    description=raw.get("description"),
                    schema=schema,
                    logger=self.logger,
                    revision=int(raw.get("revision") or 1),
                    created_at=raw.get("created_at") or utc_now(),
                    updated_at=raw.get("updated_at") or utc_now(),
                )
            except Exception as exc:
                # An app whose persisted config no longer satisfies its
                # schema (or is otherwise broken) is skipped with a loud
                # log — a config service must not refuse to start over one
                # bad app and take every other app down with it.
                self.logger.error("Skipping unloadable app %r: %s", name, exc)
                continue
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

            app_config = config or Nacho(config_data or {}, schema=schema)
            app = ConfigApp(
                name=name,
                config=app_config,
                description=description,
                schema=schema,
                logger=self.logger,
            )
            self._apps[name] = app
            self.store.save(app)
            self.history.record(app.snapshot())
            return app

    def replace(
        self,
        name: str,
        *,
        config_data: Dict[str, Any],
        description: Optional[str] = None,
        schema: Optional[Dict[str, Any]] = None,
        expected_revision: Optional[int] = None,
    ) -> ConfigApp:
        """Replace an app's config/schema/description. Renaming is rename()'s job.

        PUT semantics: an omitted description clears the stored one.
        Identical payloads are no-ops — the revision does not bump, so a
        reconciliation loop re-PUTting the same config cannot flush the
        history ring.
        """
        with self._lock:
            current = self._require_app(name)
            self._check_revision(current, expected_revision)

            target_schema = schema if schema is not None else current.schema
            schema_changed = target_schema != current.schema
            if schema_changed:
                config_changed = current.config.replace(config_data, schema=target_schema)
            else:
                config_changed = current.config.replace(config_data)
            metadata_changed = description != current.description or schema_changed

            current.description = description
            current.schema = copy.deepcopy(target_schema)
            self.persist(current, changed=config_changed or metadata_changed, notify=True)
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
            changed = False
            if description is not None and description != app.description:
                app.description = description
                changed = True

            renamed = bool(new_name and new_name != current_name)
            if renamed:
                validate_app_name(new_name)
                if new_name in self._apps:
                    raise ValueError(f"App {new_name!r} already exists")
                del self._apps[current_name]
                self.store.delete(current_name)
                self.history.rename(current_name, new_name)
                app.name = new_name
                app.hub.app_name = new_name
                self._apps[new_name] = app
                changed = True

            self.persist(app, changed=changed, notify=changed)
            if renamed:
                # Disconnect subscribers of the old name: their /ws/{old}
                # endpoint is dead, and a reconnect surfaces a clear
                # "app not found" instead of silently mirroring the renamed
                # app while REST writes target the old name.
                app.hub.close_all()
            return app

    def persist(self, app: ConfigApp, *, changed: bool = True, notify: bool = False) -> None:
        should_notify = False
        with self._lock:
            if changed:
                app.config.save()
                app.touch()
                self.history.record(app.snapshot())
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
            schema_changed = schema != app.schema
            if schema_changed:
                app.config.replace(app.config.get_all(), schema=schema)
                app.schema = copy.deepcopy(schema)
            self.persist(app, changed=schema_changed, notify=schema_changed)
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

    def list_history(self, name: str) -> List[Dict[str, Any]]:
        with self._lock:
            self._require_app(name)
            return self.history.list(name)

    def get_history_snapshot(self, name: str, revision: int) -> Optional[Dict[str, Any]]:
        with self._lock:
            self._require_app(name)
            return self.history.get(name, revision)

    def rollback(
        self,
        name: str,
        revision: int,
        *,
        expected_revision: Optional[int] = None,
    ) -> ConfigApp:
        """Restore config and schema from a history snapshot as a NEW revision.

        History is never rewritten: rolling back to revision 41 creates a
        revision whose content equals snapshot 41, so the counter stays
        monotonic and the rollback itself is undoable.
        """
        with self._lock:
            app = self._require_app(name)
            self._check_revision(app, expected_revision)
            snapshot = self.history.get(name, revision)
            if snapshot is None:
                raise LookupError(f"Revision {revision} of app {name!r} is not in history")
            target_config = snapshot.get("config") or {}
            target_schema = snapshot.get("schema")
            if target_config == app.config.get_all() and target_schema == app.schema:
                return app  # already identical — no new revision
            app.config.replace(target_config, schema=target_schema)
            app.schema = copy.deepcopy(target_schema)
            self.persist(app, changed=True, notify=True)
            return app

    def delete(self, name: str) -> bool:
        with self._lock:
            app = self._apps.pop(name, None)
            if app is None:
                return False
            app.cleanup()
            self.store.delete(name)
            self.history.delete(name)
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
