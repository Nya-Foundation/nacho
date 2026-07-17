"""Authentication helpers for the Nacho API server."""

from __future__ import annotations

import hmac
import logging
from typing import Optional, Sequence
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


class AuthGuard:
    """Verifies API keys from headers, cookies, and WebSocket handshakes."""

    def __init__(self, api_key: Optional[str] = None) -> None:
        self.api_key = api_key

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    def verify_token(self, token: Optional[str]) -> bool:
        """Return True when *token* matches the configured API key."""
        if not self.api_key:
            return True
        if not token:
            return False
        token = token.strip()
        if token.startswith(_AUTH_PREFIX):
            token = token[len(_AUTH_PREFIX) :]
        # Compare as bytes: compare_digest raises TypeError on non-ASCII str input.
        return bool(token) and hmac.compare_digest(
            token.encode("utf-8"), self.api_key.encode("utf-8")
        )

    def verify_cookie(self, raw: Optional[str]) -> bool:
        """Verify the session cookie, which the UI writes URL-encoded.

        The raw form is also accepted so a cookie written before encoding
        was introduced keeps working until it is rewritten.
        """
        if not raw:
            return False
        if self.verify_token(raw):
            return True
        decoded = unquote(raw)
        return decoded != raw and self.verify_token(decoded)

    def verify_request(self, request: Request) -> bool:
        """Verify HTTP auth from the session cookie or Authorization header."""
        if not self.enabled:
            return True
        if self.verify_cookie(request.cookies.get(_SESSION_COOKIE)):
            return True
        return self.verify_token(request.headers.get("Authorization"))

    def verify_websocket(self, websocket: WebSocket) -> bool:
        """Verify WebSocket auth from cookie or Authorization header."""
        if not self.enabled:
            return True
        if self.verify_cookie(websocket.cookies.get(_SESSION_COOKIE)):
            return True
        return self.verify_token(websocket.headers.get("Authorization"))


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

    async def dispatch(self, request: Request, call_next):
        if request.method == "OPTIONS" or self._is_public(request.url.path):
            return await call_next(request)
        if self.auth.verify_request(request):
            return await call_next(request)

        self.logger.debug("Rejected unauthenticated request to %s", request.url.path)
        # Same {"detail": ...} envelope FastAPI uses for HTTPException, so
        # clients only ever parse one error shape.
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
