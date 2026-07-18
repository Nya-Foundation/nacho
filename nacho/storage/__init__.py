from .base import (
    AuthError,
    ConflictError,
    NotFoundError,
    RemoteError,
    StorageBackend,
    StorageError,
)
from .file import FileStorageBackend

try:
    import requests  # noqa: F401
    import websocket  # noqa: F401
except ModuleNotFoundError:  # pragma: no cover - optional 'remote' extra not installed
    HAS_REMOTE_DEPS = False

    class RemoteStorageBackend:  # type: ignore[no-redef]
        def __init__(self, *args, **kwargs):
            raise ImportError(
                "RemoteStorageBackend requires extra dependencies. "
                "Install with: pip install nacho-python[remote]"
            )
else:
    HAS_REMOTE_DEPS = True
    # Keep this outside the dependency probe: an ImportError inside our own
    # implementation is a real defect and must not be hidden as a missing extra.
    from .remote import RemoteStorageBackend


__all__ = [
    "StorageBackend",
    "StorageError",
    "RemoteError",
    "AuthError",
    "NotFoundError",
    "ConflictError",
    "FileStorageBackend",
    "RemoteStorageBackend",
    "HAS_REMOTE_DEPS",
]
