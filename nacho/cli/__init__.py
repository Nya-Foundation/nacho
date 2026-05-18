"""Nacho CLI package.

This package provides the command-line interface for Nacho.
"""

def main_cli(*args, **kwargs):
    from .main import main_cli as _main_cli

    return _main_cli(*args, **kwargs)

__all__ = ["main_cli"]
