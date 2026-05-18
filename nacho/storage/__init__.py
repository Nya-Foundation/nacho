from .base import StorageBackend, StorageError
from .file import FileStorageBackend

try:
    import requests
    import websocket  # noqa: F401

    HAS_REMOTE_DEPS = True
    from .remote import RemoteStorageBackend
except ImportError:
    HAS_REMOTE_DEPS = False

    class RemoteStorageBackend:  # type: ignore[no-redef]
        def __init__(self, *args, **kwargs):
            raise ImportError(
                "RemoteStorageBackend requires extra dependencies. "
                "Install with: pip install nacho[remote]"
            )


__all__ = [
    "StorageBackend",
    "StorageError",
    "FileStorageBackend",
    "RemoteStorageBackend",
    "HAS_REMOTE_DEPS",
]
