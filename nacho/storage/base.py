"""Abstract base for storage backends."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, Optional


class StorageError(Exception):
    """Raised when a storage operation fails."""


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
