"""Authentication helpers for the Nacho API server."""

from __future__ import annotations

import hmac
import logging
from typing import Any, Optional, Sequence
from urllib.parse import unquote

from fastapi import Request, WebSocket
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

LOGGER = logging.getLogger(__name__)

_AUTH_PREFIX = "Bearer "
_SESSION_COOKIE = "NACHO_api_key"
# /docs, /redoc, and /openapi.json stay public: GET / advertises the docs and
# the API surface is not a secret — only the data behind it is.
_DEFAULT_PUBLIC_PATHS = ("/", "/health", "/favicon.ico", "/ui", "/docs", "/redoc", "/openapi.json")


# Access roles granted by a matching key.
ROLE_ADMIN = "admin"  # full read/write access
ROLE_READ = "read"  # safe HTTP methods and WebSocket subscriptions only


def validate_api_key(name: str, value: Any) -> Optional[str]:
    """Return *value* if it is a usable API key, raising TypeError otherwise.

    Keys are compared as UTF-8 bytes, so a non-str key would only fail when
    someone first presents a *valid* credential — an opaque 500 long after
    the misconfiguration. Worse, a falsy non-str (``[]``, ``0``) would leave
    the server silently unauthenticated. Both are caught here instead.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a str or None, got {type(value).__name__}")
    return value


class AuthGuard:
    """Verifies API keys from headers, cookies, and WebSocket handshakes.

    Two keys can be configured: *api_key* grants full access, and the
    optional *read_only_api_key* grants read access only — the middleware
    rejects unsafe methods presented with it. Handing dashboards and
    pollers the read-only key keeps write credentials out of them.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        read_only_api_key: Optional[str] = None,
    ) -> None:
        self.api_key = validate_api_key("api_key", api_key)
        self.read_only_api_key = validate_api_key("read_only_api_key", read_only_api_key)

    @property
    def enabled(self) -> bool:
        return bool(self.api_key or self.read_only_api_key)

    @staticmethod
    def _matches(token: str, key: str) -> bool:
        # Compare as bytes: compare_digest raises TypeError on non-ASCII str input.
        return hmac.compare_digest(token.encode("utf-8"), key.encode("utf-8"))

    def role_for_token(self, token: Optional[str]) -> Optional[str]:
        """Return the role *token* grants: ROLE_ADMIN, ROLE_READ, or None."""
        if not self.enabled:
            return ROLE_ADMIN
        if not token:
            return None
        token = token.strip()
        if token.startswith(_AUTH_PREFIX):
            token = token[len(_AUTH_PREFIX) :]
        if not token:
            return None
        if self.api_key and self._matches(token, self.api_key):
            return ROLE_ADMIN
        if self.read_only_api_key and self._matches(token, self.read_only_api_key):
            return ROLE_READ
        return None

    def role_for_cookie(self, raw: Optional[str]) -> Optional[str]:
        """Role granted by the session cookie, which the UI writes URL-encoded.

        The raw form is also accepted so a cookie written before encoding
        was introduced keeps working until it is rewritten.
        """
        if not raw:
            return None
        role = self.role_for_token(raw)
        if role is not None:
            return role
        decoded = unquote(raw)
        if decoded != raw:
            return self.role_for_token(decoded)
        return None

    def role_for_request(self, request: Request) -> Optional[str]:
        """Best role granted by the session cookie or Authorization header."""
        roles = {
            self.role_for_cookie(request.cookies.get(_SESSION_COOKIE)),
            self.role_for_token(request.headers.get("Authorization")),
        }
        if ROLE_ADMIN in roles:
            return ROLE_ADMIN
        if ROLE_READ in roles:
            return ROLE_READ
        return None

    # -- boolean convenience wrappers ----------------------------------

    def verify_token(self, token: Optional[str]) -> bool:
        """True when *token* grants full access."""
        return self.role_for_token(token) == ROLE_ADMIN

    def verify_cookie(self, raw: Optional[str]) -> bool:
        """True when the cookie grants any access."""
        return self.role_for_cookie(raw) is not None

    def verify_request(self, request: Request) -> bool:
        """True when the request carries any valid credential (read or admin)."""
        return self.role_for_request(request) is not None

    def verify_websocket(self, websocket: WebSocket) -> bool:
        """Verify WebSocket auth from cookie or Authorization header.

        Subscriptions are read-only by nature, so either key is accepted.
        """
        if not self.enabled:
            return True
        if self.role_for_cookie(websocket.cookies.get(_SESSION_COOKIE)) is not None:
            return True
        return self.role_for_token(websocket.headers.get("Authorization")) is not None


class AuthMiddleware(BaseHTTPMiddleware):
    """Rejects unauthenticated HTTP requests when API-key auth is enabled."""

    def __init__(
        self,
        app,
        auth: AuthGuard,
        logger: Optional[logging.Logger] = None,
        public_paths: Sequence[str] = _DEFAULT_PUBLIC_PATHS,
    ) -> None:
        super().__init__(app)
        self.auth = auth
        self.logger = logger or LOGGER
        self.public_paths = tuple(public_paths)

    _SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

    async def dispatch(self, request: Request, call_next):
        if request.method == "OPTIONS" or self._is_public(request.url.path):
            return await call_next(request)
        role = self.auth.role_for_request(request)
        if role == ROLE_ADMIN or (role == ROLE_READ and request.method in self._SAFE_METHODS):
            return await call_next(request)

        # Same {"detail": ...} envelope FastAPI uses for HTTPException, so
        # clients only ever parse one error shape.
        if role == ROLE_READ:
            self.logger.debug("Rejected read-only-key write to %s", request.url.path)
            return JSONResponse(
                status_code=403,
                content={"detail": "Forbidden: this API key grants read-only access"},
            )
        self.logger.debug("Rejected unauthenticated request to %s", request.url.path)
        return JSONResponse(
            status_code=401,
            content={"detail": "Unauthorized: invalid API key"},
            headers={"WWW-Authenticate": "Bearer"},
        )

    def _is_public(self, path: str) -> bool:
        return any(
            path == public or (public != "/" and path.startswith(f"{public}/"))
            for public in self.public_paths
        )
