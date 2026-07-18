"""Typed REST client for the Nacho server API.

Shared by :class:`RemoteStorageBackend` and the CLI so there is exactly one
implementation of auth headers, URL building, and error mapping. HTTP
failures raise the typed errors from :mod:`nacho.storage.base`
(:class:`AuthError`, :class:`NotFoundError`, :class:`ConflictError`,
:class:`RemoteError`), each carrying the server's ``detail`` payload.

Requires the ``remote`` extra (``pip install nacho-python[remote]``).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

import requests

from .storage.base import AuthError, ConflictError, NotFoundError, RemoteError

_DEFAULT_TIMEOUT = 10.0


class NachoClient:
    """Thin, typed wrapper over the Nacho server's REST endpoints.

    All app-scoped methods target *app_name*. Methods return the parsed
    response body (unwrapped from the ``{"data": ...}`` envelope where the
    API uses one); config reads also return the revision from the
    ``X-Nacho-Revision`` header.
    """

    def __init__(
        self,
        url: str,
        app_name: str = "default",
        api_key: Optional[str] = None,
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> None:
        self.base = url.rstrip("/")
        self.app_name = app_name
        self.api_key = api_key
        self.timeout = timeout
        self.last_generation: Optional[str] = None

    # ------------------------------------------------------------------
    # Low-level request plumbing
    # ------------------------------------------------------------------

    def headers(self) -> Dict[str, str]:
        if self.api_key:
            return {"Authorization": f"Bearer {self.api_key}"}
        return {}

    def request(
        self,
        method: str,
        path: str,
        *,
        json_body: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
        allowed: Tuple[int, ...] = (),
    ) -> requests.Response:
        """Perform a request; raise a typed error for any non-2xx status
        not listed in *allowed*."""
        url = f"{self.base}{path}"
        try:
            resp = requests.request(
                method,
                url,
                json=json_body,
                params=params,
                headers=self.headers(),
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise RemoteError(f"{method} {url} failed: {exc}") from exc
        if resp.status_code >= 400 and resp.status_code not in allowed:
            self._raise(method, url, resp)
        return resp

    def _raise(self, method: str, url: str, resp: requests.Response) -> None:
        detail: Any = None
        try:
            body = resp.json()
            if isinstance(body, dict):
                detail = body.get("detail", body.get("error"))
        except ValueError:
            pass

        status_code = resp.status_code
        if status_code == 409 and isinstance(detail, dict):
            expected, actual = detail.get("expected"), detail.get("actual")
            raise ConflictError(
                f"Revision conflict: expected {expected}, current revision is {actual}. "
                "Reload the latest config and retry.",
                detail=detail,
                expected=expected,
                actual=actual,
            )

        message = detail if isinstance(detail, str) else None
        if message is None:
            message = f"{method} {url} failed: {status_code} {resp.reason}"
        if status_code in (401, 403):
            raise AuthError(message, status=status_code, detail=detail)
        if status_code == 404:
            raise NotFoundError(message, status=status_code, detail=detail)
        if status_code == 409:
            raise ConflictError(message, detail=detail)
        raise RemoteError(message, status=status_code, detail=detail)

    def _app(self, suffix: str = "") -> str:
        return f"/api/apps/{quote(self.app_name, safe='')}{suffix}"

    def _record_generation(self, resp: requests.Response) -> None:
        generation = resp.headers.get("X-Nacho-Generation")
        if generation:
            self.last_generation = generation

    @staticmethod
    def _revision_from(resp: requests.Response) -> Optional[int]:
        raw = resp.headers.get("X-Nacho-Revision")
        return int(raw) if raw and raw.isdigit() else None

    # ------------------------------------------------------------------
    # System
    # ------------------------------------------------------------------

    def health(self) -> Dict[str, Any]:
        return self.request("GET", "/health").json()

    def convert(self, data: Any, *, from_fmt: str, to_fmt: str) -> Dict[str, Any]:
        payload = {"data": data, "from": from_fmt, "to": to_fmt}
        return self.request("POST", "/api/convert", json_body=payload).json()

    # ------------------------------------------------------------------
    # Apps
    # ------------------------------------------------------------------

    def list_apps(self) -> Dict[str, Dict[str, Any]]:
        return self.request("GET", "/api/apps").json()["data"]

    def create_app(
        self,
        *,
        data: Optional[Any] = None,
        fmt: str = "json",
        schema: Optional[Any] = None,
        schema_format: str = "json",
        description: Optional[str] = None,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "name": self.app_name,
            "data": data if data is not None else {},
            "format": fmt,
        }
        if schema is not None:
            payload["schema"] = schema
            payload["schema_format"] = schema_format
        if description is not None:
            payload["description"] = description
        return self.request("POST", "/api/apps", json_body=payload).json()

    def get_app_info(self) -> Dict[str, Any]:
        return self.request("GET", self._app()).json()["data"]

    def delete_app(self) -> Dict[str, Any]:
        return self.request("DELETE", self._app()).json()

    def update_metadata(
        self,
        *,
        name: Optional[str] = None,
        description: Optional[str] = None,
        revision: Optional[int] = None,
    ) -> Dict[str, Any]:
        payload = {
            k: v
            for k, v in (("name", name), ("description", description), ("revision", revision))
            if v is not None
        }
        return self.request("PATCH", self._app("/metadata"), json_body=payload).json()

    # ------------------------------------------------------------------
    # Config
    # ------------------------------------------------------------------

    def get_config(self) -> Tuple[Dict[str, Any], Optional[int]]:
        resp = self.request("GET", self._app("/config"))
        self._record_generation(resp)
        return resp.json(), self._revision_from(resp)

    def put_config(
        self, data: Any, *, fmt: str = "json", revision: Optional[int] = None
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"data": data, "format": fmt}
        if revision is not None:
            payload["revision"] = revision
        return self.request("PUT", self._app("/config"), json_body=payload).json()

    def get_path(self, path: str) -> Tuple[Any, Optional[int]]:
        resp = self.request("GET", self._app(f"/config/{quote(path, safe='')}"))
        self._record_generation(resp)
        return resp.json()["value"], self._revision_from(resp)

    def set_path(
        self,
        path: str,
        value: Any,
        *,
        revision: Optional[int] = None,
        value_type: str = "raw",
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"value": value, "type": value_type}
        if revision is not None:
            payload["revision"] = revision
        return self.request(
            "PUT", self._app(f"/config/{quote(path, safe='')}"), json_body=payload
        ).json()

    def delete_path(self, path: str, *, revision: Optional[int] = None) -> Dict[str, Any]:
        params = {"revision": revision} if revision is not None else None
        return self.request(
            "DELETE", self._app(f"/config/{quote(path, safe='')}"), params=params
        ).json()

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

    def get_schema(self) -> Optional[Dict[str, Any]]:
        return self.request("GET", self._app("/schema")).json()["data"]

    def put_schema(
        self,
        schema: Optional[Any],
        *,
        fmt: str = "json",
        revision: Optional[int] = None,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"schema": schema, "schema_format": fmt}
        if revision is not None:
            payload["revision"] = revision
        return self.request("PUT", self._app("/schema"), json_body=payload).json()

    def validate(self, data: Any, *, fmt: str = "json") -> Dict[str, Any]:
        payload = {"data": data, "format": fmt}
        return self.request("POST", self._app("/validate"), json_body=payload).json()

    # ------------------------------------------------------------------
    # History
    # ------------------------------------------------------------------

    def list_history(self) -> List[Dict[str, Any]]:
        return self.request("GET", self._app("/history")).json()["data"]

    def get_history_snapshot(self, revision: int) -> Dict[str, Any]:
        return self.request("GET", self._app(f"/history/{revision}")).json()["data"]

    def rollback(self, revision: int, *, expected_revision: Optional[int] = None) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"revision": revision}
        if expected_revision is not None:
            payload["expected_revision"] = expected_revision
        return self.request("POST", self._app("/rollback"), json_body=payload).json()
