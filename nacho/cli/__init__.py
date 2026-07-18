"""Nacho CLI package.

Re-exports the console entry point (pyproject's script points at
``nacho.cli.main:main_cli`` directly).
"""

from .main import main_cli

__all__ = ["main_cli"]
