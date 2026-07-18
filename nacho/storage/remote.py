"""Remote storage backend — connects to a Nacho server.

Write path : REST API  (PUT /api/apps/{app}/config)
Read  path : REST API  (GET /api/apps/{app}/config)
Push  path : WebSocket (server → client notifications only; client never writes via WS)

The WebSocket subscription keeps the local snapshot up-to-date in near-real-time.
Writes always go through REST so there is no ambiguity about who owns the state.

The backend tracks the server's revision counter: every load and push records
the revision it saw, and save() sends it back so a concurrent remote write
surfaces as a ConflictError instead of silently winning last-writer-takes-all.
"""

from __future__ import annotations

import copy
import json
import logging
import threading
from typing import Any, Dict, Optional

import websocket

from ..client import NachoClient
from .base import AuthError, ConflictError, NotFoundError, RemoteError, StorageBackend, StorageError

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = 10.0
_WS_RECONNECT_DELAY = 5.0
# Client-side pings detect half-open connections (NAT/idle timeouts) that
# would otherwise leave the watcher silently stale forever.
_WS_PING_INTERVAL = 30.0
_WS_PING_TIMEOUT = 10.0
# Close codes / handshake statuses that will not succeed on retry.
_WS_PERMANENT_CLOSE_CODES = (1008, 4004)  # unauthorized, app not found
_WS_PERMANENT_HTTP_STATUSES = (401, 403, 404)


class RemoteStorageBackend(StorageBackend):
    """Storage backend that mirrors a remote Nacho app via REST + WebSocket.

    Args:
        url:        Base URL of the remote Nacho server (e.g. "http://host:8000")
        app_name:   Name of the app to connect to (default: "default")
        api_key:    Bearer token for authentication
        timeout:    HTTP request timeout in seconds
        reconnect:  Number of WS reconnection attempts (0 = unlimited)
        auto_connect: Verify the server/app during construction
        watch:      Start the WebSocket watcher during construction
    """

    def __init__(
        self,
        url: str,
        app_name: str = "default",
        api_key: Optional[str] = None,
        timeout: float = _DEFAULT_TIMEOUT,
        reconnect: int = 0,
        auto_connect: bool = True,
        watch: bool = False,
    ) -> None:
        super().__init__()
        self._base = url.rstrip("/")
        self.app_name = app_name
        self._api_key = api_key
        self._reconnect = reconnect
        self._client = NachoClient(url, app_name=app_name, api_key=api_key, timeout=timeout)

        self._ws_url = (
            self._base.replace("https://", "wss://").replace("http://", "ws://") + f"/ws/{app_name}"
        )

        self._ws: Optional[websocket.WebSocketApp] = None
        self._ws_thread: Optional[threading.Thread] = None
        self._ws_attempts = 0
        self._stop = threading.Event()
        self._running = False
        self._connected = False
        self._watch_requested = watch
        self._ws_lock = threading.Lock()

        # Last revision seen from the server (REST or WS) and the latest
        # pushed snapshot, used to keep applies monotonic.
        self._rev_lock = threading.Lock()
        self._revision: Optional[int] = None
        self._last_push: Optional[Dict[str, Any]] = None

        if auto_connect:
            self.connect(watch=watch)

    @property
    def revision(self) -> Optional[int]:
        """The last server revision this backend has seen (None before any read)."""
        with self._rev_lock:
            return self._revision

    # ------------------------------------------------------------------
    # StorageBackend interface
    # ------------------------------------------------------------------

    def load(self) -> Dict[str, Any]:
        self._ensure_connected()
        try:
            data, revision = self._client.get_config()
        except NotFoundError as exc:
            raise StorageError(
                f"Remote app {self.app_name!r} does not exist on {self._base}. "
                "Create it first (server UI/API) or write to it with save()."
            ) from exc
        if not isinstance(data, dict):
            raise StorageError(f"Remote app {self.app_name!r} returned non-object config")
        with self._rev_lock:
            if revision is not None:
                if self._revision is not None and revision < self._revision:
                    # The watcher already applied a newer push; don't let a
                    # slower REST read roll the local snapshot backwards.
                    if self._last_push is not None:
                        return copy.deepcopy(self._last_push)
                else:
                    self._revision = revision
        return data

    def save(self, data: Dict[str, Any]) -> None:
        """Persist *data* by replacing the app's config on the server.

        Sends the last revision this backend saw, so a concurrent remote
        write raises ConflictError instead of being silently overwritten —
        call load() to pick up the latest state, then save again.
        The first save to a nonexistent app creates it.
        """
        self._ensure_connected()
        with self._rev_lock:
            revision = self._revision
        try:
            body = self._client.put_config(data, revision=revision)
            new_revision = body.get("revision")
        except NotFoundError:
            body = self._client.create_app(data=data)
            app_info = body.get("app") or {}
            new_revision = app_info.get("revision")
            logger.info("Created remote app %r", self.app_name)
        except ConflictError as exc:
            raise ConflictError(
                f"save() for app {self.app_name!r} lost a revision race: {exc} "
                "Call load() to refresh, reapply the change, and save again.",
                detail=exc.detail,
                expected=exc.expected,
                actual=exc.actual,
            ) from exc
        with self._rev_lock:
            if isinstance(new_revision, int) and (
                self._revision is None or new_revision > self._revision
            ):
                self._revision = new_revision
        logger.debug("Saved config to remote app %r", self.app_name)

    def cleanup(self) -> None:
        self.close()

    def connect(self, *, watch: Optional[bool] = None) -> None:
        """Verify the remote app and optionally start receiving push updates."""
        self._ensure_connected()
        should_watch = self._watch_requested if watch is None else watch
        if should_watch:
            self.start_watching()

    def start_watching(self) -> None:
        """Start the WebSocket watcher if it is not already running."""
        self._ensure_connected()
        self._start_ws()

    def close(self) -> None:
        with self._ws_lock:
            self._running = False
            self._stop.set()
            ws = self._ws
        if ws:
            try:
                ws.close()
            except Exception:  # pragma: no cover - depends on socket state
                pass
        thread = self._ws_thread
        if thread and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=2.0)

    # ------------------------------------------------------------------
    # Internals — HTTP
    # ------------------------------------------------------------------

    def _ensure_connected(self) -> None:
        if self._connected:
            return
        self._verify_connection()
        self._connected = True

    def _verify_connection(self) -> None:
        """Confirm the server is reachable and the credentials are accepted.

        Raises AuthError for rejected credentials and StorageError for
        connectivity problems, so failures surface at construction time,
        not silently later. A missing app is NOT an error here — readers
        get a loud 404 from load(), and save() creates the app on the
        first write. Connecting must never mutate the server.
        """
        try:
            self._client.request("GET", f"/api/apps/{self.app_name}", allowed=(404,))
        except AuthError:
            raise
        except RemoteError as exc:
            raise StorageError(f"Cannot reach Nacho server at {self._base}: {exc}") from exc
        logger.info("Connected to Nacho server %s (app: %r)", self._base, self.app_name)

    # ------------------------------------------------------------------
    # Internals — WebSocket (receive-only)
    # ------------------------------------------------------------------

    def _ws_headers(self) -> Optional[Dict[str, str]]:
        if self._api_key:
            return {"Authorization": f"Bearer {self._api_key}"}
        return None

    def _start_ws(self) -> None:
        with self._ws_lock:
            if self._running:
                return
            self._running = True
            self._ws_attempts = 0
            self._stop.clear()
            self._ws_thread = threading.Thread(
                target=self._ws_loop,
                daemon=True,
                name=f"NACHO-ws-{self.app_name}",
            )
            self._ws_thread.start()

    def _ws_loop(self) -> None:
        while True:
            with self._ws_lock:
                if not self._running or self._stop.is_set():
                    break
                self._ws = websocket.WebSocketApp(
                    self._ws_url,
                    header=self._ws_headers(),
                    on_open=self._on_open,
                    on_message=self._on_message,
                    on_error=self._on_error,
                    on_close=self._on_close,
                )
                ws = self._ws
            try:
                ws.run_forever(ping_interval=_WS_PING_INTERVAL, ping_timeout=_WS_PING_TIMEOUT)
            except Exception:
                logger.error("WS error for %r", self.app_name, exc_info=True)

            if not self._running:
                break

            self._ws_attempts += 1
            if self._reconnect and self._ws_attempts > self._reconnect:
                logger.error(
                    "WS: max consecutive reconnect attempts (%d) reached for %r — giving up",
                    self._reconnect,
                    self.app_name,
                )
                break
            logger.debug(
                "WS: reconnecting to %r in %.1fs (attempt %d)",
                self.app_name,
                _WS_RECONNECT_DELAY,
                self._ws_attempts,
            )
            # Event.wait so close() interrupts the backoff instead of blocking join().
            if self._stop.wait(_WS_RECONNECT_DELAY):
                break

    def _on_open(self, ws: websocket.WebSocketApp) -> None:
        # A successful connection resets the counter so `reconnect` bounds
        # consecutive failures, not total disconnects over the process lifetime.
        self._ws_attempts = 0
        if self._stop.is_set():
            # close() ran between this connection being created and opening.
            ws.close()
            return
        logger.debug("WS connected for app %r", self.app_name)

    def _on_message(self, ws: websocket.WebSocketApp, raw: str) -> None:
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("WS: malformed message for %r: %r", self.app_name, raw)
            return

        if not isinstance(msg, dict):
            logger.warning("WS: ignored non-object message for %r", self.app_name)
            return

        msg_type = msg.get("type")
        data = msg.get("data")
        if msg_type in ("update", "initial_config") and isinstance(data, dict):
            revision = msg.get("revision")
            with self._rev_lock:
                if isinstance(revision, int):
                    if self._revision is not None and revision <= self._revision:
                        # Out-of-order broadcast or the echo of our own save.
                        logger.debug(
                            "WS: ignoring stale revision %s for %r", revision, self.app_name
                        )
                        return
                    self._revision = revision
                self._last_push = copy.deepcopy(data)
            callback = self.on_remote_change
            if callback:
                try:
                    callback(data)
                except Exception:
                    logger.error("on_remote_change raised", exc_info=True)
        elif msg_type in ("update", "initial_config"):
            logger.warning("WS: ignored invalid config payload for %r", self.app_name)

    def _on_error(self, ws: websocket.WebSocketApp, error: Exception) -> None:
        status_code = getattr(error, "status_code", None)
        if status_code in _WS_PERMANENT_HTTP_STATUSES:
            logger.error(
                "WS: handshake rejected for %r (HTTP %s) — check the API key / app name; "
                "not retrying",
                self.app_name,
                status_code,
            )
            self._running = False
            return
        logger.warning("WS error for %r: %s", self.app_name, error)

    def _on_close(
        self,
        ws: websocket.WebSocketApp,
        code: Optional[int],
        reason: Optional[str],
    ) -> None:
        if code in _WS_PERMANENT_CLOSE_CODES:
            logger.error(
                "WS: server rejected the subscription for %r (%s: %s) — not retrying",
                self.app_name,
                code,
                reason or ("unauthorized" if code == 1008 else "app not found"),
            )
            self._running = False
            return
        logger.debug("WS closed for %r: %s %s", self.app_name, code, reason)

    def __str__(self) -> str:
        return f"RemoteStorageBackend(url={self._base!r}, app={self.app_name!r})"
