"""File-based storage backend (YAML / JSON / TOML)."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, Union

from ..utils.io import create_file_if_not_exists, load_file, save_file
from .base import StorageBackend, StorageError

logger = logging.getLogger(__name__)


class FileStorageBackend(StorageBackend):
    """Persist configuration to a local file.

    The file is created (empty) on first use if it does not already exist.
    """

    def __init__(self, path: Union[str, Path]) -> None:
        super().__init__()
        self.path = Path(path)
        create_file_if_not_exists(self.path)

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
