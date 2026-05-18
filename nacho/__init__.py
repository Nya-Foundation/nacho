"""Nacho — schema-first dynamic configuration service."""

from ._version import __version__
from .config import Nacho
from .event import EventType
from .schema import HAS_SCHEMA_DEPS, ValidationError
from .storage import (
    HAS_REMOTE_DEPS,
    FileStorageBackend,
    StorageBackend,
    StorageError,
)

try:
    from .storage import RemoteStorageBackend
except ImportError:
    pass

try:
    from .server.app import NachoOrchestrator

    HAS_SERVER_DEPS = True
except ImportError:
    HAS_SERVER_DEPS = False

__all__ = [
    "__version__",
    "Nacho",
    "EventType",
    "ValidationError",
    "StorageBackend",
    "StorageError",
    "FileStorageBackend",
    "RemoteStorageBackend",
    "NachoOrchestrator",
    "HAS_SCHEMA_DEPS",
    "HAS_REMOTE_DEPS",
    "HAS_SERVER_DEPS",
]
