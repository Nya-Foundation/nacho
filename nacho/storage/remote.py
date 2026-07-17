"""Remote storage backend — connects to a Nacho server.

Write path : REST API  (PUT /api/apps/{app}/config)
Read  path : REST API  (GET /api/apps/{app}/config)
Push  path : WebSocket (server → client notifications only; client never writes via WS)

The WebSocket subscription keeps the local snapshot up-to-date in near-real-time.
Writes always go through REST so there is no ambiguity about who owns the state.
"""

from __future__ import annotations

import json
import logging
import threading
from typing import Any, Dict, Optional

import requests
import websocket

from .base import StorageBackend, StorageError

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = 10.0
_WS_RECONNECT_DELAY = 5.0


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
        self._timeout = timeout
        self._reconnect = reconnect

        self._api_url = f"{self._base}/api/apps/{app_name}/config"
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

        if auto_connect:
            self.connect(watch=watch)

    # ------------------------------------------------------------------
    # StorageBackend interface
    # ------------------------------------------------------------------

    def load(self) -> Dict[str, Any]:
        self._ensure_connected()
        resp = self._get(self._api_url)
        data = resp.json()
        if not isinstance(data, dict):
            raise StorageError(f"Remote app {self.app_name!r} returned non-object config")
        return data

    def save(self, data: Dict[str, Any]) -> None:
        """Persist *data* by replacing the app's config on the server."""
        self._ensure_connected()
        payload = {"data": json.dumps(data), "format": "json"}
        resp = self._put(self._api_url, payload)
        if resp.status_code == 404:
            self._create_app(data)
            return
        try:
            resp.raise_for_status()
        except requests.RequestException as exc:
            raise StorageError(f"PUT {self._api_url} failed: {exc}") from exc
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
        self._running = False
        self._stop.set()
        if self._ws:
            self._ws.close()
        if self._ws_thread and self._ws_thread.is_alive():
            self._ws_thread.join(timeout=2.0)

    # ------------------------------------------------------------------
    # Internals — HTTP
    # ------------------------------------------------------------------

    def _headers(self) -> Dict[str, str]:
        h = {"Content-Type": "application/json"}
        if self._api_key:
            h["Authorization"] = f"Bearer {self._api_key}"
        return h

    def _ensure_connected(self) -> None:
        if self._connected:
            return
        self._verify_connection()
        self._connected = True

    def _get(self, url: str) -> requests.Response:
        try:
            resp = requests.get(url, headers=self._headers(), timeout=self._timeout)
            resp.raise_for_status()
            return resp
        except requests.RequestException as exc:
            raise StorageError(f"GET {url} failed: {exc}") from exc

    def _put(self, url: str, payload: Dict[str, Any]) -> requests.Response:
        try:
            return requests.put(
                url,
                json=payload,
                headers=self._headers(),
                timeout=self._timeout,
            )
        except requests.RequestException as exc:
            raise StorageError(f"PUT {url} failed: {exc}") from exc

    def _post(self, url: str, payload: Dict[str, Any]) -> requests.Response:
        try:
            return requests.post(
                url,
                json=payload,
                headers=self._headers(),
                timeout=self._timeout,
            )
        except requests.RequestException as exc:
            raise StorageError(f"POST {url} failed: {exc}") from exc

    def _verify_connection(self) -> None:
        """Confirm the server is reachable and the app exists (or create it).

        Raises StorageError on any connectivity problem so failures surface at
        construction time, not silently later.
        """
        health_url = f"{self._base}/health"
        try:
            resp = requests.get(health_url, headers=self._headers(), timeout=self._timeout)
            resp.raise_for_status()
        except requests.RequestException as exc:
            raise StorageError(f"Cannot reach Nacho server at {self._base}: {exc}") from exc

        # Ensure the target app exists
        info_url = f"{self._base}/api/apps/{self.app_name}"
        resp = requests.get(info_url, headers=self._headers(), timeout=self._timeout)
        if resp.status_code == 404:
            self._create_app({})
        elif not resp.ok:
            raise StorageError(
                f"App {self.app_name!r} check failed: {resp.status_code} {resp.text}"
            )
        logger.info("Connected to Nacho server %s (app: %r)", self._base, self.app_name)

    def _create_app(self, initial_data: Dict[str, Any]) -> None:
        payload = {
            "name": self.app_name,
            "data": json.dumps(initial_data),
            "format": "json",
        }
        resp = self._post(f"{self._base}/api/apps", payload)
        if resp.status_code not in (200, 201):
            raise StorageError(
                f"Failed to create app {self.app_name!r}: {resp.status_code} {resp.text}"
            )
        logger.info("Created remote app %r", self.app_name)

    # ------------------------------------------------------------------
    # Internals — WebSocket (receive-only)
    # ------------------------------------------------------------------

    def _start_ws(self) -> None:
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
        while self._running:
            try:
                self._ws = websocket.WebSocketApp(
                    self._ws_url,
                    header=self._headers(),
                    on_open=self._on_open,
                    on_message=self._on_message,
                    on_error=self._on_error,
                    on_close=self._on_close,
                )
                self._ws.run_forever()
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
            callback = self.on_remote_change
            if callback:
                try:
                    callback(data)
                except Exception:
                    logger.error("on_remote_change raised", exc_info=True)
        elif msg_type in ("update", "initial_config"):
            logger.warning("WS: ignored invalid config payload for %r", self.app_name)

    def _on_error(self, ws: websocket.WebSocketApp, error: Exception) -> None:
        logger.warning("WS error for %r: %s", self.app_name, error)

    def _on_close(
        self,
        ws: websocket.WebSocketApp,
        code: Optional[int],
        reason: Optional[str],
    ) -> None:
        logger.debug("WS closed for %r: %s %s", self.app_name, code, reason)

    def __str__(self) -> str:
        return f"RemoteStorageBackend(url={self._base!r}, app={self.app_name!r})"
