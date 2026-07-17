"""Abstract base for storage backends."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, Optional


class StorageError(Exception):
    """Raised when a storage operation fails."""


class RemoteError(StorageError):
    """A remote Nacho server operation failed.

    Carries the HTTP status and the server's JSON ``detail`` payload when
    available, so callers see the actual reason (schema violations,
    conflict info) instead of a bare status code.
    """

    def __init__(self, message: str, *, status: Optional[int] = None, detail: Any = None) -> None:
        super().__init__(message)
        self.status = status
        self.detail = detail


class AuthError(RemoteError):
    """The server rejected the request's credentials (401/403)."""


class NotFoundError(RemoteError):
    """The requested app, path, or revision does not exist (404)."""


class ConflictError(RemoteError):
    """A revision-checked write lost the race (409)."""

    def __init__(
        self,
        message: str,
        *,
        detail: Any = None,
        expected: Optional[int] = None,
        actual: Optional[int] = None,
    ) -> None:
        super().__init__(message, status=409, detail=detail)
        self.expected = expected
        self.actual = actual


class StorageBackend(ABC):
    """Pluggable persistence layer for Nacho.

    Subclasses implement load() and save(); everything else is optional.
    The on_remote_change callback is set by Nacho to propagate
    externally-triggered changes back into the in-memory config.
    """

    def __init__(self) -> None:
        self.on_remote_change: Optional[Callable[[Dict[str, Any]], None]] = None

    @abstractmethod
    def load(self) -> Dict[str, Any]:
        """Read and return the full config dict."""

    @abstractmethod
    def save(self, data: Dict[str, Any]) -> None:
        """Persist *data*.  Raises StorageError on failure."""

    def cleanup(self) -> None:
        """Release resources (connections, threads, file handles).  Optional."""
