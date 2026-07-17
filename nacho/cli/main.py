"""
Command-line interface for Nacho.
"""

import argparse
import functools
import ipaddress
import json
import logging
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, List, Optional

from nacho import HAS_REMOTE_DEPS, HAS_SCHEMA_DEPS, HAS_SERVER_DEPS
from nacho._version import __version__
from nacho.config import Nacho
from nacho.env import FALSY_STRINGS, TRUTHY_STRINGS
from nacho.env import _parse_value as parse_value
from nacho.server import NachoOrchestrator
from nacho.storage.base import AuthError, ConflictError, NotFoundError
from nacho.utils.io import dump_string, load_file, save_file
from nacho.utils.path import get_nested_value

if TYPE_CHECKING:  # pragma: no cover - typing only
    from nacho.client import NachoClient

LOGGER = logging.getLogger("nacho.cli")

# Exit codes. EXIT_USAGE is argparse's own code for bad arguments; the rest
# are produced by the @cli_command wrapper from the typed client errors.
EXIT_OK = 0
EXIT_ERROR = 1
EXIT_USAGE = 2
EXIT_NOT_FOUND = 3
EXIT_CONFLICT = 4
EXIT_AUTH = 5

BANNER = r"""
            _   _     _      ____  _   _   ___
           | \ | |   / \    / ___|| | | | / _ \
           |  \| |  / _ \  | |    | |_| || | | |
           | |\  | / ___ \ | |___ |  _  || |_| |
           |_| \_|/_/   \_\ \____||_| |_| \___/
"""


def banner() -> str:
    """Return the ASCII banner with a version tagline."""
    return f"{BANNER}  Lightweight, self-hosted dynamic configuration  ·  v{__version__}\n"


BUILT_IN_TEMPLATES = {
    "empty": {},
    "web-app": {
        "app": {"name": "web-app", "version": "1.0.0", "port": 3000},
        "server": {"host": "localhost", "ssl": False},
        "api": {"baseUrl": "/api/v1", "timeout": 5000},
    },
    "api-service": {
        "service": {"name": "api-service", "version": "1.0.0", "port": 8000},
        "database": {"host": "localhost", "port": 5432, "name": "app_db"},
        "auth": {"jwt_secret": "your-secret-key", "expires_in": "24h"},
    },
    "microservice": {
        "service": {"name": "microservice", "version": "1.0.0", "port": 8080},
        "logging": {"level": "info", "format": "json"},
        "metrics": {"enabled": True, "endpoint": "/metrics"},
        "health": {"endpoint": "/health", "timeout": 30},
    },
    "default": {
        "app": {"name": "default-app", "version": "1.0.0"},
        "settings": {"debug": True, "log_level": "info"},
    },
}

# --type values the server coerces itself; auto/json are parsed client-side.
_SERVER_TYPE_HINTS = ("str", "int", "float", "bool")


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------
def cli_command(func: Callable[[argparse.Namespace], int]) -> Callable[[argparse.Namespace], int]:
    """The single error-handling path shared by every command handler.

    Prints ``Error: <message>`` to stderr and maps the typed client errors to
    dedicated exit codes; anything unexpected is a generic failure (1).
    """

    @functools.wraps(func)
    def wrapper(args: argparse.Namespace) -> int:
        try:
            return func(args)
        except Exception as exc:
            print(f"Error: {exc}", file=sys.stderr)
            if isinstance(exc, AuthError):
                return EXIT_AUTH
            if isinstance(exc, ConflictError):
                return EXIT_CONFLICT
            if isinstance(exc, NotFoundError):
                return EXIT_NOT_FOUND
            return EXIT_ERROR

    return wrapper


def require_remote_deps() -> None:
    """Fail with an actionable message when the [remote] extra is missing."""
    if not HAS_REMOTE_DEPS:
        raise ImportError("Remote features require: pip install nacho-python[remote]")


def build_client(args: argparse.Namespace, app_name: Optional[str] = None) -> "NachoClient":
    """Build the one NachoClient a command uses from --remote/--app-name/--api-key."""
    require_remote_deps()
    from nacho.client import NachoClient

    return NachoClient(
        args.remote,
        app_name=app_name or getattr(args, "app_name", "default"),
        api_key=args.api_key,
    )


def create_config(
    config_path: Optional[str] = None,
    schema: Optional[str] = None,
    read_only: bool = False,
) -> Nacho:
    """Create a Nacho instance for a local config file."""
    return Nacho(
        storage=config_path or "config.yaml",
        schema=Path(schema) if schema else None,
        read_only=read_only,
    )


def render(value: Any, fmt: str) -> str:
    """Serialize *value* for terminal output in the chosen --format."""
    return dump_string(value, fmt).rstrip("\n")


def coerce_value(raw: str, kind: str) -> Any:
    """Coerce a CLI value string according to ``--type``.

    ``auto`` keeps the historical best-effort parsing (ints, floats, bools,
    null, quoted strings); ``str`` forces the value to stay a string; ``json``
    parses the value as a JSON document. Raises ValueError when the value
    cannot be parsed as the requested type.
    """
    if kind == "str":
        return raw
    if kind == "int":
        return int(raw)
    if kind == "float":
        return float(raw)
    if kind == "bool":
        low = raw.lower()
        if low in TRUTHY_STRINGS or low == "1":
            return True
        if low in FALSY_STRINGS or low == "0":
            return False
        raise ValueError(f"Cannot parse {raw!r} as a boolean")
    if kind == "json":
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON value: {exc}") from exc
    return parse_value(raw)  # auto


def is_loopback_host(host: str) -> bool:
    """True for "localhost" and loopback IPs (127.0.0.0/8, ::1)."""
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:  # a hostname — assume it is reachable from outside
        return False


def _validate_remote(client: "NachoClient", data: Any) -> dict:
    """Run server-side validation, tolerating an empty or non-JSON body."""
    try:
        return client.validate(data) or {}
    except ValueError:  # empty response body
        return {}


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------
def create_parser() -> argparse.ArgumentParser:
    """Create the main argument parser.

    The repeated flag groups (remote access, --format, --revision, --debug)
    live in parent parsers so each subcommand declares them once.
    """
    # SUPPRESS keeps a subcommand's parse from clobbering a top-level
    # `nacho --debug <command>` with its own False default.
    debug = argparse.ArgumentParser(add_help=False)
    debug.add_argument(
        "--debug", action="store_true", default=argparse.SUPPRESS, help="Enable debug logging"
    )

    fmt = argparse.ArgumentParser(add_help=False)
    fmt.add_argument(
        "--format", "-f", choices=["json", "yaml", "toml"], default="json", help="Output format"
    )

    revision = argparse.ArgumentParser(add_help=False)
    revision.add_argument(
        "--revision", type=int, help="Expected remote app revision for conflict-safe writes"
    )

    def remote_parent(required: bool = True, app_name: bool = True) -> argparse.ArgumentParser:
        p = argparse.ArgumentParser(add_help=False)
        p.add_argument("--remote", required=required, help="Remote server URL")
        if app_name:
            p.add_argument("--app-name", default="default", help="Application name on the server")
        p.add_argument("--api-key", help="API key for remote server")
        return p

    remote_opt = remote_parent(required=False)
    remote_req = remote_parent()
    remote_req_no_app = remote_parent(app_name=False)

    parser = argparse.ArgumentParser(
        prog="nacho",
        description=banner(),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Server command
    server = subparsers.add_parser("server", parents=[debug], help="Start configuration server")
    server.add_argument(
        "--host", default="127.0.0.1", help="Server host (use 0.0.0.0 to listen on all interfaces)"
    )
    server.add_argument("--port", type=int, default=8000, help="Server port")
    server.add_argument("--config", "-c", help="Configuration file path")
    server.add_argument("--schema", help="Schema file path")
    server.add_argument("--data-dir", help="Directory for API-created app state")
    server.add_argument("--api-key", help="API key for authentication")
    server.add_argument("--app-name", help="Application name for config server")
    server.add_argument(
        "--history-limit",
        type=int,
        default=50,
        help="Revision snapshots to keep per app for rollback (0 disables history)",
    )
    server.add_argument("--read-only", action="store_true", help="Read-only mode")
    server.add_argument("--reload", action="store_true", help="Auto-reload for development")
    server.set_defaults(func=cmd_server)

    # Get command
    get = subparsers.add_parser(
        "get", parents=[debug, remote_opt, fmt], help="Get configuration value"
    )
    get.add_argument("key", nargs="?", help="Configuration key (optional)")
    get.add_argument("--config", "-c", default="config.yaml", help="Configuration file")
    get.add_argument(
        "--show-revision",
        action="store_true",
        help="Include the remote app revision in the output",
    )
    get.set_defaults(func=cmd_get)

    # Set command
    set_parser = subparsers.add_parser(
        "set", parents=[debug, remote_opt, revision], help="Set configuration value"
    )
    set_parser.add_argument("key", help="Configuration key")
    set_parser.add_argument("value", help="Configuration value")
    set_parser.add_argument("--config", "-c", default="config.yaml", help="Configuration file")
    set_parser.add_argument("--schema", help="Schema file for validation")
    set_parser.add_argument(
        "--type",
        choices=["auto", "str", "int", "float", "bool", "json"],
        default="auto",
        help="How to interpret the value (auto = best-effort typing)",
    )
    set_parser.set_defaults(func=cmd_set)

    # Delete command
    delete = subparsers.add_parser(
        "delete", parents=[debug, remote_opt, revision], help="Delete configuration value"
    )
    delete.add_argument("key", help="Configuration key")
    delete.add_argument("--config", "-c", default="config.yaml", help="Configuration file")
    delete.add_argument("--schema", help="Schema file for validation")
    delete.set_defaults(func=cmd_delete)

    # Validate command
    validate = subparsers.add_parser(
        "validate", parents=[debug, remote_opt], help="Validate configuration"
    )
    validate.add_argument("--config", "-c", default="config.yaml", help="Configuration file")
    validate.add_argument(
        "--schema", help="Schema file (optional with --remote: the server's stored schema is used)"
    )
    validate.set_defaults(func=cmd_validate)

    # Init command
    init = subparsers.add_parser("init", parents=[debug], help="Initialize new configuration")
    init.add_argument("config", help="Name of the configuration file to create")
    init.add_argument(
        "--template",
        default="default",
        choices=sorted(BUILT_IN_TEMPLATES),
        help="Built-in template to start from",
    )
    init.set_defaults(func=cmd_init)

    # Apps command group (remote app management)
    apps = subparsers.add_parser("apps", help="Manage apps on a remote server")
    apps_sub = apps.add_subparsers(dest="apps_command", required=True)

    apps_list = apps_sub.add_parser(
        "list", parents=[debug, remote_req_no_app, fmt], help="List apps on the server"
    )
    apps_list.set_defaults(func=cmd_apps_list)

    apps_create = apps_sub.add_parser(
        "create", parents=[debug, remote_req_no_app], help="Create an app on the server"
    )
    apps_create.add_argument("name", help="App name")
    apps_create.add_argument("--description", help="App description")
    apps_create.add_argument("--schema", help="JSON Schema file to attach")
    apps_create.add_argument("--config", "-c", help="Initial configuration file")
    apps_create.set_defaults(func=cmd_apps_create)

    apps_delete = apps_sub.add_parser(
        "delete", parents=[debug, remote_req_no_app], help="Delete an app from the server"
    )
    apps_delete.add_argument("name", help="App name")
    apps_delete.set_defaults(func=cmd_apps_delete)

    apps_show = apps_sub.add_parser(
        "show", parents=[debug, remote_req, fmt], help="Show an app's info (--app-name)"
    )
    apps_show.set_defaults(func=cmd_apps_show)

    apps_rename = apps_sub.add_parser(
        "rename", parents=[debug, remote_req, revision], help="Rename an app (--app-name)"
    )
    apps_rename.add_argument("new_name", help="New app name")
    apps_rename.set_defaults(func=cmd_apps_rename)

    apps_describe = apps_sub.add_parser(
        "describe",
        parents=[debug, remote_req, revision],
        help="Set an app's description (--app-name)",
    )
    apps_describe.add_argument("text", help="New description")
    apps_describe.set_defaults(func=cmd_apps_describe)

    # Schema command group (remote schema management)
    schema = subparsers.add_parser("schema", help="Manage a remote app's schema")
    schema_sub = schema.add_subparsers(dest="schema_command", required=True)

    schema_get = schema_sub.add_parser(
        "get", parents=[debug, remote_req, fmt], help="Print the app's stored schema"
    )
    schema_get.set_defaults(func=cmd_schema_get)

    schema_push = schema_sub.add_parser(
        "push", parents=[debug, remote_req, revision], help="Upload a schema file to the app"
    )
    schema_push.add_argument("schema_file", help="Schema file (json/yaml/toml)")
    schema_push.set_defaults(func=cmd_schema_push)

    # History command group (remote revision history)
    history = subparsers.add_parser("history", help="Inspect a remote app's revision history")
    history_sub = history.add_subparsers(dest="history_command", required=True)

    history_list = history_sub.add_parser(
        "list", parents=[debug, remote_req, fmt], help="List stored revisions"
    )
    history_list.set_defaults(func=cmd_history_list)

    history_show = history_sub.add_parser(
        "show", parents=[debug, remote_req, fmt], help="Print one stored revision snapshot"
    )
    history_show.add_argument("revision", type=int, help="Revision number")
    history_show.set_defaults(func=cmd_history_show)

    # Rollback command
    rollback = subparsers.add_parser(
        "rollback",
        parents=[debug, remote_req],
        help="Restore config and schema from a history revision (creates a new revision)",
    )
    rollback.add_argument("revision", type=int, help="History revision to restore")
    rollback.add_argument(
        "--revision-check",
        type=int,
        dest="expected_revision",
        help="Expected current app revision for conflict-safe rollback",
    )
    rollback.set_defaults(func=cmd_rollback)

    # Watch command (live updates)
    watch = subparsers.add_parser(
        "watch",
        parents=[debug, remote_req],
        help="Stream an app's config over WebSocket (prints the current config, then each update)",
    )
    watch.set_defaults(func=cmd_watch)

    return parser


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------
@cli_command
def cmd_server(args: argparse.Namespace) -> int:
    """Handle server command."""
    if not HAS_SERVER_DEPS:
        raise ImportError("Server features require: pip install nacho-python[server]")

    print(banner())

    if not args.api_key and not is_loopback_host(args.host):
        print(
            "WARNING: serving on a non-loopback interface without --api-key — "
            "anyone who can reach this host has full write access.",
            file=sys.stderr,
        )

    apps = None
    if args.config:
        config = create_config(args.config, schema=args.schema, read_only=args.read_only)
        apps = {args.app_name or "default": config}

    orchestrator = NachoOrchestrator(
        apps=apps,
        api_key=args.api_key,
        read_only=args.read_only,
        data_dir=args.data_dir,
        history_limit=args.history_limit,
        logger=LOGGER,
    )
    orchestrator.run(host=args.host, port=args.port, reload=args.reload)
    return EXIT_OK


@cli_command
def cmd_get(args: argparse.Namespace) -> int:
    """Handle get command."""
    if args.remote:
        client = build_client(args)
        if args.key:
            value, revision = client.get_path(args.key)
        else:
            value, revision = client.get_config()
        if args.show_revision:
            value = {"revision": revision, "data": value}
    else:
        data = create_config(args.config).get_all()
        if args.key:
            missing = object()
            value = get_nested_value(data, args.key, missing)
            if value is missing:
                raise NotFoundError(f"Key {args.key!r} not found")
        else:
            value = data

    print(render(value, args.format))
    return EXIT_OK


@cli_command
def cmd_set(args: argparse.Namespace) -> int:
    """Handle set command."""
    if args.remote:
        client = build_client(args)
        if args.type in _SERVER_TYPE_HINTS:  # let the server coerce
            value, value_type = args.value, args.type
        else:  # auto/json are parsed client-side and stored verbatim
            value, value_type = coerce_value(args.value, args.type), "raw"
        body = client.set_path(args.key, value, revision=args.revision, value_type=value_type)
        note = "" if body.get("changed", True) else ", unchanged"
        print(
            f"Set {args.key} = {body.get('value', value)} (revision {body.get('revision')}{note})"
        )
        return EXIT_OK

    value = coerce_value(args.value, args.type)
    config = create_config(args.config, schema=args.schema)
    config.set(args.key, value)
    config.save()
    print(f"Set {args.key} = {value}")
    return EXIT_OK


@cli_command
def cmd_delete(args: argparse.Namespace) -> int:
    """Handle delete command."""
    if args.remote:
        body = build_client(args).delete_path(args.key, revision=args.revision)
        print(f"Deleted {args.key} (revision {body.get('revision')})")
        return EXIT_OK

    config = create_config(args.config, schema=args.schema)
    if not config.delete(args.key):
        raise NotFoundError(f"Key {args.key!r} not found")
    config.save()
    print(f"Deleted {args.key}")
    return EXIT_OK


@cli_command
def cmd_validate(args: argparse.Namespace) -> int:
    """Validate a local config file — against a local schema file, or against
    the schema the remote server actually enforces (--remote)."""
    if args.remote:
        if not Path(args.config).exists():
            raise FileNotFoundError(f"Configuration file not found: {args.config}")
        body = _validate_remote(build_client(args), load_file(args.config))
        errors = body.get("errors", [])
    else:
        if not args.schema:
            raise ValueError("--schema is required unless --remote is given")
        if not HAS_SCHEMA_DEPS:
            raise ImportError("Schema validation requires: pip install nacho-python[schema]")
        errors = create_config(args.config, schema=args.schema).validate()

    if errors:
        print("Validation failed:")
        for error in errors:
            print(f"  - {error}")
        return EXIT_ERROR
    print("Validation successful")
    return EXIT_OK


@cli_command
def cmd_init(args: argparse.Namespace) -> int:
    """Handle init command."""
    config_path = Path(args.config)
    if config_path.exists():
        raise FileExistsError(f"Configuration file already exists: {config_path}")
    save_file(config_path, BUILT_IN_TEMPLATES[args.template])
    print(f"Created configuration file: {config_path}")
    return EXIT_OK


@cli_command
def cmd_apps_list(args: argparse.Namespace) -> int:
    """List apps on the server."""
    print(render(build_client(args).list_apps(), args.format))
    return EXIT_OK


@cli_command
def cmd_apps_create(args: argparse.Namespace) -> int:
    """Create an app on the server."""
    client = build_client(args, app_name=args.name)
    body = client.create_app(
        data=load_file(args.config) if args.config else {},
        schema=load_file(args.schema) if args.schema else None,
        description=args.description,
    )
    print(f"Created app {args.name!r} (revision {body['app']['revision']})")
    return EXIT_OK


@cli_command
def cmd_apps_delete(args: argparse.Namespace) -> int:
    """Delete an app from the server."""
    build_client(args, app_name=args.name).delete_app()
    print(f"Deleted app {args.name!r}")
    return EXIT_OK


@cli_command
def cmd_apps_show(args: argparse.Namespace) -> int:
    """Show one app's stored metadata."""
    print(render(build_client(args).get_app_info(), args.format))
    return EXIT_OK


@cli_command
def cmd_apps_rename(args: argparse.Namespace) -> int:
    """Rename an app (conflict-safe with --revision)."""
    client = build_client(args)
    body = client.update_metadata(name=args.new_name, revision=args.revision)
    print(
        f"Renamed app {client.app_name!r} to {args.new_name!r} (revision {body['app']['revision']})"
    )
    return EXIT_OK


@cli_command
def cmd_apps_describe(args: argparse.Namespace) -> int:
    """Set an app's description (conflict-safe with --revision)."""
    client = build_client(args)
    body = client.update_metadata(description=args.text, revision=args.revision)
    print(f"Updated description of app {client.app_name!r} (revision {body['app']['revision']})")
    return EXIT_OK


@cli_command
def cmd_schema_get(args: argparse.Namespace) -> int:
    """Print the app's stored schema."""
    print(render(build_client(args).get_schema(), args.format))
    return EXIT_OK


@cli_command
def cmd_schema_push(args: argparse.Namespace) -> int:
    """Upload a schema file to the app."""
    if not Path(args.schema_file).exists():
        raise FileNotFoundError(f"Schema file not found: {args.schema_file}")
    body = build_client(args).put_schema(load_file(args.schema_file), revision=args.revision)
    print(f"Schema updated (revision {body.get('revision')})")
    return EXIT_OK


@cli_command
def cmd_history_list(args: argparse.Namespace) -> int:
    """List a remote app's stored revisions."""
    print(render(build_client(args).list_history(), args.format))
    return EXIT_OK


@cli_command
def cmd_history_show(args: argparse.Namespace) -> int:
    """Print one stored revision snapshot."""
    print(render(build_client(args).get_history_snapshot(args.revision), args.format))
    return EXIT_OK


@cli_command
def cmd_rollback(args: argparse.Namespace) -> int:
    """Restore a remote app's config and schema from a history revision."""
    body = build_client(args).rollback(args.revision, expected_revision=args.expected_revision)
    print(f"{body.get('message')} (now at revision {body.get('revision')})")
    return EXIT_OK


@cli_command
def cmd_watch(args: argparse.Namespace) -> int:
    """Stream config updates for an app: current config first, then each change."""
    require_remote_deps()
    import threading

    from nacho.storage.remote import RemoteStorageBackend

    backend = RemoteStorageBackend(url=args.remote, app_name=args.app_name, api_key=args.api_key)

    def on_change(data: dict) -> None:
        print(json.dumps(data, ensure_ascii=False), flush=True)

    backend.on_remote_change = on_change
    backend.start_watching()
    print(f"Watching {args.app_name!r} on {args.remote} (Ctrl+C to stop)", file=sys.stderr)
    try:
        threading.Event().wait()  # sleep until interrupted
    except KeyboardInterrupt:
        pass
    finally:
        backend.close()
    return EXIT_OK


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main_cli(argv: Optional[List[str]] = None) -> int:
    """Main CLI entry point."""
    parser = create_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.debug else logging.WARNING)

    if args.command is None:
        parser.print_help()
        return EXIT_OK
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main_cli())
