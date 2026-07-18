"""Nacho — schema-first dynamic configuration service."""

from ._version import __version__
from .config import Nacho
from .event import EventType
from .schema import HAS_SCHEMA_DEPS, ValidationError
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

try:
    from .server.app import NachoOrchestrator

    HAS_SERVER_DEPS = True
except ImportError:  # pragma: no cover - optional 'server' extra not installed
    HAS_SERVER_DEPS = False

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
if not HAS_SERVER_DEPS:
    # Keep __all__ truthful so `from nacho import *` never hits an undefined name.
    __all__.remove("NachoOrchestrator")
