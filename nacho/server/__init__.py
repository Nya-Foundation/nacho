"""REST API server module for Nacho configuration management.

This module provides the FastAPI application used by the Nacho server.
Install with: pip install nacho[server]
"""

# Check for server dependencies
try:
    import fastapi
    import uvicorn

    HAS_SERVER_DEPS = True
except ImportError:  # pragma: no cover - optional 'server' extra not installed
    HAS_SERVER_DEPS = False

# Only import if dependencies are available
if HAS_SERVER_DEPS:
    from .app import NachoOrchestrator
else:  # pragma: no cover - optional 'server' extra not installed
    # Define a placeholder class that raises ImportError when instantiated
    class NachoOrchestrator:
        """Placeholder class for NachoOrchestrator.

        This raises an informative error when server features are used without
        server dependencies installed.
        """

        def __init__(self, *args, **kwargs):
            raise ImportError(
                "Web server features require additional dependencies. "
                "Install them with: pip install nacho[server]"
            )


__all__ = ["NachoOrchestrator", "HAS_SERVER_DEPS"]
