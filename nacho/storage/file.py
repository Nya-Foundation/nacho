"""File-based storage backend (YAML / JSON / TOML)."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, Union

from ..utils.io import load_file, save_file
from .base import StorageBackend, StorageError

logger = logging.getLogger(__name__)


class FileStorageBackend(StorageBackend):
    """Persist configuration to a local file.

    A missing file loads as an empty config and is created on first save,
    so constructing a backend (e.g. for a read-only instance) never writes
    to the filesystem.
    """

    def __init__(self, path: Union[str, Path]) -> None:
        super().__init__()
        self.path = Path(path)

    def __str__(self) -> str:
        return f"FileStorageBackend({self.path})"

    def load(self) -> Dict[str, Any]:
        try:
            return load_file(self.path)
        except (ValueError, IOError) as exc:
            raise StorageError(f"Cannot load {self.path}: {exc}") from exc

    def save(self, data: Dict[str, Any]) -> None:
        try:
            save_file(self.path, data)
            logger.debug("Saved config to %s", self.path)
        except (ValueError, IOError) as exc:
            raise StorageError(f"Cannot save {self.path}: {exc}") from exc
