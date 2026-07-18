"""Nacho — schema-first dynamic configuration service."""

from ._version import __version__
from .config import Nacho
from .event import EventType
from .schema import HAS_SCHEMA_DEPS, ValidationError
from .server import HAS_SERVER_DEPS, NachoOrchestrator
from .storage import (
    HAS_REMOTE_DEPS,
    AuthError,
    ConflictError,
    FileStorageBackend,
    NotFoundError,
    RemoteError,
    RemoteStorageBackend,
    StorageBackend,
    StorageError,
)

__all__ = [
    "__version__",
    "Nacho",
    "EventType",
    "ValidationError",
    "StorageBackend",
    "StorageError",
    "RemoteError",
    "AuthError",
    "NotFoundError",
    "ConflictError",
    "FileStorageBackend",
    "RemoteStorageBackend",
    "NachoOrchestrator",
    "HAS_SCHEMA_DEPS",
    "HAS_REMOTE_DEPS",
    "HAS_SERVER_DEPS",
]
