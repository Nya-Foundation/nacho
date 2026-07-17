"""Smoke tests: cheap import / startup / health checks.

These run on every default ``pytest`` invocation and should finish in well
under a second. They catch gross breakage (bad imports, a server that won't
construct) without needing any external service.
"""

import subprocess
import sys

import pytest


def test_package_imports():
    """The top-level package and its version import cleanly."""
    from nacho._version import __version__

    assert isinstance(__version__, str) and __version__


def test_version_matches_metadata():
    """The hard-coded __version__ matches the installed distribution metadata."""
    from importlib.metadata import PackageNotFoundError, version

    from nacho._version import __version__

    # The import package is "nacho"; the distribution may be published under
    # either name, so try both before giving up.
    for dist_name in ("nacho-python", "nacho"):
        try:
            assert version(dist_name) == __version__
            return
        except PackageNotFoundError:
            continue
    pytest.skip("nacho is not installed as a distribution (running from source)")


def test_cli_help_runs():
    """``nacho`` prints usage via the module entry point."""
    result = subprocess.run(
        [sys.executable, "-m", "nacho.cli.main"],
        capture_output=True,
        text=True,
    )
    # No subcommand prints help and returns 1; that is expected smoke behaviour.
    output = result.stdout + result.stderr
    assert "usage: nacho" in output
    assert "server" in output


def test_server_app_constructs_and_health_ok():
    """The FastAPI app builds and answers /health without a network server."""
    from fastapi.testclient import TestClient

    from nacho.server import NachoOrchestrator

    orchestrator = NachoOrchestrator()
    with TestClient(orchestrator.app) as client:
        resp = client.get("/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert "version" in body


def test_ui_is_bundled_and_served():
    """The management UI ships inside the package and is served at /ui."""
    from fastapi.testclient import TestClient

    from nacho.server import NachoOrchestrator

    with TestClient(NachoOrchestrator().app) as client:
        resp = client.get("/ui")
        assert resp.status_code == 200
        assert "Nacho" in resp.text
