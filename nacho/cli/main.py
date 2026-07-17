"""
Command-line interface for Nacho.
"""

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any, Optional
from urllib.parse import quote

import yaml

from nacho import HAS_REMOTE_DEPS, HAS_SCHEMA_DEPS, HAS_SERVER_DEPS
from nacho._version import __version__
from nacho.config import Nacho
from nacho.env import _parse_value as parse_value
from nacho.server import NachoOrchestrator
from nacho.utils.io import save_file

LOGGER = logging.getLogger("nacho.cli")

BANNER = r"""
            _   _     _      ____  _   _   ___
           | \ | |   / \    / ___|| | | | / _ \
           |  \| |  / _ \  | |    | |_| || | | |
           | |\  | / ___ \ | |___ |  _  || |_| |
           |_| \_|/_/   \_\ \____||_| |_| \___/
"""


def banner() -> str:
    """Return the ASCII banner with a version tagline."""
    return (
        f"{BANNER}"
        f"  Lightweight, self-hosted dynamic configuration  ·  v{__version__}\n"
    )


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


def create_parser() -> argparse.ArgumentParser:
    """
    Create the main argument parser.
    """
    parser = argparse.ArgumentParser(
        prog="nacho",
        description=banner(),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging",
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Server command
    server = subparsers.add_parser("server", help="Start configuration server")
    server.add_argument(
        "--host",
        default="127.0.0.1",
        help="Server host (use 0.0.0.0 to listen on all interfaces)",
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
    server.add_argument(
        "--read-only",
        action="store_true",
        help="Read-only mode",
    )
    server.add_argument(
        "--reload",
        action="store_true",
        help="Auto-reload for development",
    )

    # Get command
    get = subparsers.add_parser("get", help="Get configuration value")
    get.add_argument("key", nargs="?", help="Configuration key (optional)")
    get.add_argument("--config", "-c", default="config.yaml", help="Configuration file")
    get.add_argument("--format", "-f", choices=["json", "yaml", "raw"], default="raw")
    get.add_argument("--remote", help="Remote server URL")
    get.add_argument("--app-name", default="default", help="Application name for remote server")
    get.add_argument("--api-key", help="API key for remote server")
    get.add_argument(
        "--show-revision",
        action="store_true",
        help="Include the remote app revision in JSON/YAML output",
    )

    # Set command
    set_parser = subparsers.add_parser("set", help="Set configuration value")
    set_parser.add_argument("key", help="Configuration key")
    set_parser.add_argument("value", help="Configuration value")
    set_parser.add_argument("--config", "-c", default="config.yaml", help="Configuration file")
    set_parser.add_argument("--schema", help="Schema file for validation")
    set_parser.add_argument("--remote", help="Remote server URL")
    set_parser.add_argument(
        "--app-name", default="default", help="Application name for remote server"
    )
    set_parser.add_argument("--api-key", help="API key for remote server")
    set_parser.add_argument(
        "--revision",
        type=int,
        help="Expected remote app revision for conflict-safe writes",
    )

    # Delete command
    delete = subparsers.add_parser("delete", help="Delete configuration value")
    delete.add_argument("key", help="Configuration key")
    delete.add_argument("--config", "-c", default="config.yaml", help="Configuration file")
    delete.add_argument("--schema", help="Schema file for validation")
    delete.add_argument("--remote", help="Remote server URL")
    delete.add_argument("--app-name", default="default", help="Application name for remote server")
    delete.add_argument("--api-key", help="API key for remote server")
    delete.add_argument(
        "--revision",
        type=int,
        help="Expected remote app revision for conflict-safe deletes",
    )

    # Validate command
    validate = subparsers.add_parser("validate", help="Validate configuration")
    validate.add_argument("--config", "-c", default="config.yaml", help="Configuration file")
    validate.add_argument(
        "--schema",
        help="Schema file (optional with --remote: the server's stored schema is used)",
    )
    validate.add_argument(
        "--remote",
        help="Validate against a remote app's schema instead of a local schema file",
    )
    validate.add_argument(
        "--app-name",
        default="default",
        help="Application name for remote server",
    )
    validate.add_argument("--api-key", help="API key for remote server")

    # Init command
    init = subparsers.add_parser("init", help="Initialize new configuration")
    init.add_argument("config", help="Name of the configuration file to create")
    init.add_argument(
        "--template",
        default="default",
        choices=sorted(BUILT_IN_TEMPLATES),
        help="Built-in template to start from",
    )

    # Apps command group (remote app management)
    apps = subparsers.add_parser("apps", help="Manage apps on a remote server")
    apps_sub = apps.add_subparsers(dest="apps_command", required=True)

    apps_list = apps_sub.add_parser("list", help="List apps on the server")
    _add_remote_args(apps_list, app_name=False)
    apps_list.add_argument("--format", "-f", choices=["json", "yaml", "raw"], default="raw")

    apps_create = apps_sub.add_parser("create", help="Create an app on the server")
    apps_create.add_argument("name", help="App name")
    _add_remote_args(apps_create, app_name=False)
    apps_create.add_argument("--description", help="App description")
    apps_create.add_argument("--schema", help="JSON Schema file to attach")
    apps_create.add_argument("--config", "-c", help="Initial configuration file")

    apps_delete = apps_sub.add_parser("delete", help="Delete an app from the server")
    apps_delete.add_argument("name", help="App name")
    _add_remote_args(apps_delete, app_name=False)

    # Schema command group (remote schema management)
    schema = subparsers.add_parser("schema", help="Manage a remote app's schema")
    schema_sub = schema.add_subparsers(dest="schema_command", required=True)

    schema_get = schema_sub.add_parser("get", help="Print the app's stored schema")
    _add_remote_args(schema_get)
    schema_get.add_argument("--format", "-f", choices=["json", "yaml", "raw"], default="raw")

    schema_push = schema_sub.add_parser("push", help="Upload a schema file to the app")
    schema_push.add_argument("schema_file", help="Schema file (json/yaml/toml)")
    _add_remote_args(schema_push)
    schema_push.add_argument(
        "--revision",
        type=int,
        help="Expected remote app revision for conflict-safe updates",
    )

    # History command group (remote revision history)
    history = subparsers.add_parser("history", help="Inspect a remote app's revision history")
    history_sub = history.add_subparsers(dest="history_command", required=True)

    history_list = history_sub.add_parser("list", help="List stored revisions")
    _add_remote_args(history_list)
    history_list.add_argument("--format", "-f", choices=["json", "yaml", "raw"], default="raw")

    history_show = history_sub.add_parser("show", help="Print one stored revision snapshot")
    history_show.add_argument("revision", type=int, help="Revision number")
    _add_remote_args(history_show)
    history_show.add_argument("--format", "-f", choices=["json", "yaml", "raw"], default="raw")

    # Rollback command
    rollback = subparsers.add_parser(
        "rollback",
        help="Restore config and schema from a history revision (creates a new revision)",
    )
    rollback.add_argument("revision", type=int, help="History revision to restore")
    _add_remote_args(rollback)
    rollback.add_argument(
        "--revision-check",
        type=int,
        dest="expected_revision",
        help="Expected current app revision for conflict-safe rollback",
    )

    # Watch command (live updates)
    watch = subparsers.add_parser(
        "watch",
        help="Stream an app's config over WebSocket (prints the current config, then each update)",
    )
    _add_remote_args(watch)

    return parser


def _add_remote_args(p: argparse.ArgumentParser, app_name: bool = True) -> None:
    p.add_argument("--remote", required=True, help="Remote server URL")
    if app_name:
        p.add_argument("--app-name", default="default", help="Application name")
    p.add_argument("--api-key", help="API key for remote server")


def create_config(
    config_path: Optional[str] = None,
    schema: Optional[str] = None,
    read_only: bool = False,
    remote_url: Optional[str] = None,
    remote_app_name: Optional[str] = None,
    api_key: Optional[str] = None,
) -> Nacho:
    """
    Create a Nacho instance from CLI arguments.
    """
    if remote_url:
        if not HAS_REMOTE_DEPS:
            raise ImportError("Remote features require: pip install nacho-python[remote]")
        from nacho.storage.remote import RemoteStorageBackend

        storage = RemoteStorageBackend(
            url=remote_url,
            app_name=remote_app_name or "default",
            api_key=api_key,
        )
    else:
        storage = config_path or "config.yaml"

    schema_path = Path(schema) if schema else None
    return Nacho(
        storage=storage,
        schema=schema_path,
        read_only=read_only,
    )


def format_output(value: Any, format_type: str) -> str:
    """
    Format output according to specified format.
    """
    if format_type == "json":
        return json.dumps(value, indent=2)
    elif format_type == "yaml":

        return yaml.dump(value, default_flow_style=False)
    else:  # raw
        return str(value) if not isinstance(value, (dict, list)) else json.dumps(value, indent=2)


def remote_headers(api_key: Optional[str]) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


def remote_config_url(remote: str, app_name: str, key: Optional[str] = None) -> str:
    base = remote.rstrip("/")
    app = quote(app_name, safe="")
    if key is None:
        return f"{base}/api/apps/{app}/config"
    return f"{base}/api/apps/{app}/config/{quote(key, safe='.')}"


def remote_request_error(response: Any) -> str:
    try:
        payload = response.json()
    except ValueError:
        payload = response.text
    if isinstance(payload, dict) and "detail" in payload:
        return str(payload["detail"])
    return str(payload)


def remote_json(
    method: str,
    url: str,
    api_key: Optional[str],
    payload: Optional[dict] = None,
    params: Optional[dict] = None,
) -> Any:
    """Perform a remote API request and return the parsed JSON body.

    Raises ImportError without the remote extra, RuntimeError on HTTP errors.
    """
    if not HAS_REMOTE_DEPS:
        raise ImportError("Remote features require: pip install nacho-python[remote]")
    import requests

    response = requests.request(
        method,
        url,
        json=payload,
        params=params,
        headers=remote_headers(api_key),
        timeout=10,
    )
    if response.status_code >= 400:
        raise RuntimeError(remote_request_error(response))
    try:
        return response.json()
    except ValueError:  # empty or non-JSON body
        return None


def remote_get(
    remote: str,
    app_name: str,
    api_key: Optional[str],
    key: Optional[str] = None,
) -> tuple[Any, Optional[int]]:
    if not HAS_REMOTE_DEPS:
        raise ImportError("Remote features require: pip install nacho-python[remote]")
    import requests

    response = requests.get(
        remote_config_url(remote, app_name, key),
        headers=remote_headers(api_key),
        timeout=10,
    )
    if response.status_code >= 400:
        raise RuntimeError(remote_request_error(response))
    revision = response.headers.get("X-Nacho-Revision")
    parsed_revision = int(revision) if revision and revision.isdigit() else None
    payload = response.json()
    if key is not None:
        return payload.get("value"), parsed_revision
    return payload, parsed_revision


def remote_set(
    remote: str,
    app_name: str,
    api_key: Optional[str],
    key: str,
    value: Any,
    revision: Optional[int] = None,
) -> int:
    if not HAS_REMOTE_DEPS:
        print("Remote connection requires: pip install nacho-python[remote]", file=sys.stderr)
        return 1
    import requests

    payload = {"value": value, "type": "raw"}
    if revision is not None:
        payload["revision"] = revision
    response = requests.put(
        remote_config_url(remote, app_name, key),
        json=payload,
        headers=remote_headers(api_key),
        timeout=10,
    )
    if response.status_code >= 400:
        print(f"Error: {remote_request_error(response)}", file=sys.stderr)
        return 1
    body = response.json()
    print(f"Set {key} = {value} (revision {body.get('revision')})")
    return 0


def remote_delete(
    remote: str,
    app_name: str,
    api_key: Optional[str],
    key: str,
    revision: Optional[int] = None,
) -> int:
    if not HAS_REMOTE_DEPS:
        print("Remote connection requires: pip install nacho-python[remote]", file=sys.stderr)
        return 1
    import requests

    params = {"revision": revision} if revision is not None else None
    response = requests.delete(
        remote_config_url(remote, app_name, key),
        params=params,
        headers=remote_headers(api_key),
        timeout=10,
    )
    if response.status_code >= 400:
        print(f"Error: {remote_request_error(response)}", file=sys.stderr)
        return 1
    body = response.json()
    print(f"Deleted {key} (revision {body.get('revision')})")
    return 0


def cmd_server(args: argparse.Namespace) -> int:
    """
    Handle server command.
    """
    if not HAS_SERVER_DEPS:
        print("Server features require: pip install nacho-python[server]", file=sys.stderr)
        return 1

    print(banner())

    apps = None
    config: Optional[Nacho] = None
    app_name = args.app_name or "default"
    if args.host not in ("127.0.0.1", "localhost", "::1") and not args.api_key:
        print(
            "WARNING: serving on a non-loopback interface without --api-key — "
            "anyone who can reach this host has full write access.",
            file=sys.stderr,
        )

    if args.config:
        config = create_config(
            args.config,
            schema=args.schema,
            read_only=args.read_only,
        )
        apps = {app_name: config}

    orchestrator = NachoOrchestrator(
        apps=apps,
        api_key=args.api_key,
        read_only=args.read_only,
        data_dir=args.data_dir,
        history_limit=args.history_limit,
        logger=LOGGER,
    )
    orchestrator.run(host=args.host, port=args.port, reload=args.reload)
    return 0


def cmd_get(args: argparse.Namespace) -> int:
    """
    Handle get command.
    """
    try:
        if args.remote:
            value, revision = remote_get(
                args.remote,
                args.app_name,
                args.api_key,
                args.key,
            )
            if getattr(args, "show_revision", False):
                value = {"revision": revision, "data": value}
            print(format_output(value, args.format))
            return 0

        config = create_config(args.config)
        if args.key:
            value = config.get(args.key)
        else:
            value = config.get_all()
        print(format_output(value, args.format))
        return 0
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def cmd_set(args: argparse.Namespace) -> int:
    """
    Handle set command.
    """
    try:
        parsed_value = parse_value(args.value)
        if args.remote:
            return remote_set(
                args.remote,
                args.app_name,
                args.api_key,
                args.key,
                parsed_value,
                getattr(args, "revision", None),
            )

        config = create_config(args.config, schema=args.schema)
        config.set(args.key, parsed_value)

        config.save()
        print(f"Set {args.key} = {parsed_value}")
        return 0
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def cmd_delete(args: argparse.Namespace) -> int:
    """
    Handle delete command.
    """
    try:
        if args.remote:
            return remote_delete(
                args.remote,
                args.app_name,
                args.api_key,
                args.key,
                getattr(args, "revision", None),
            )

        config = create_config(args.config, schema=args.schema)
        if config.delete(args.key):
            config.save()
            print(f"Deleted {args.key}")
            return 0
        print(f"Key '{args.key}' not found", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def cmd_validate(args: argparse.Namespace) -> int:
    """Validate a local config file — against a local schema file, or against
    the schema the remote server actually enforces (--remote)."""
    try:
        if args.remote:
            from nacho.utils.io import load_file

            if not Path(args.config).exists():
                print(f"Error: configuration file not found: {args.config}", file=sys.stderr)
                return 1
            data = load_file(args.config)
            body = remote_json(
                "POST",
                f"{args.remote.rstrip('/')}/api/apps/{quote(args.app_name, safe='')}/validate",
                args.api_key,
                payload={"data": data},
            )
            errors = body.get("errors", [])
        else:
            if not args.schema:
                print("Error: --schema is required unless --remote is given", file=sys.stderr)
                return 1
            if not HAS_SCHEMA_DEPS:
                print(
                    "Schema validation requires: pip install nacho-python[schema]",
                    file=sys.stderr,
                )
                return 1
            config = create_config(args.config, schema=args.schema)
            errors = config.validate()

        if errors:
            print("Validation failed:")
            for error in errors:
                print(f"  - {error}")
            return 1
        print("Validation successful")
        return 0
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def cmd_init(args: argparse.Namespace) -> int:
    """
    Handle init command.
    """
    try:
        config_path = Path(args.config)

        if config_path.exists():
            print(f"Configuration file already exists: {config_path}", file=sys.stderr)
            return 1

        save_file(config_path, BUILT_IN_TEMPLATES[args.template])
        print(f"Created configuration file: {config_path}")
        return 0
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def _api_url(remote: str, *segments: str) -> str:
    parts = "/".join(quote(seg, safe="") for seg in segments)
    return f"{remote.rstrip('/')}/api/{parts}" if parts else f"{remote.rstrip('/')}/api"


def cmd_apps(args: argparse.Namespace) -> int:
    """Manage apps on a remote server (list / create / delete)."""
    try:
        if args.apps_command == "list":
            body = remote_json("GET", _api_url(args.remote, "apps"), args.api_key)
            apps = body.get("data", {})
            if args.format in ("json", "yaml"):
                print(format_output(apps, args.format))
            elif not apps:
                print("No apps.")
            else:
                for name, info in sorted(apps.items()):
                    schema_note = "schema" if info.get("schema") else "no schema"
                    desc = info.get("description") or ""
                    print(
                        f"{name}  rev {info.get('revision')}  "
                        f"{info.get('config_count', 0)} keys  {schema_note}"
                        + (f"  — {desc}" if desc else "")
                    )
            return 0

        if args.apps_command == "create":
            from nacho.utils.io import load_file

            payload: dict = {"name": args.name, "data": {}}
            if args.description:
                payload["description"] = args.description
            if args.config:
                payload["data"] = load_file(args.config)
            if args.schema:
                payload["schema"] = load_file(args.schema)
            body = remote_json("POST", _api_url(args.remote, "apps"), args.api_key, payload)
            print(f"Created app {args.name!r} (revision {body['app']['revision']})")
            return 0

        if args.apps_command == "delete":
            remote_json("DELETE", _api_url(args.remote, "apps", args.name), args.api_key)
            print(f"Deleted app {args.name!r}")
            return 0

        print(f"Unknown apps command: {args.apps_command}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def cmd_schema(args: argparse.Namespace) -> int:
    """Manage a remote app's schema (get / push)."""
    try:
        if args.schema_command == "get":
            body = remote_json(
                "GET", _api_url(args.remote, "apps", args.app_name, "schema"), args.api_key
            )
            print(format_output(body.get("data"), args.format))
            return 0

        if args.schema_command == "push":
            from nacho.utils.io import load_file

            if not Path(args.schema_file).exists():
                print(f"Error: schema file not found: {args.schema_file}", file=sys.stderr)
                return 1
            payload: dict = {"schema": load_file(args.schema_file)}
            if args.revision is not None:
                payload["revision"] = args.revision
            body = remote_json(
                "PUT", _api_url(args.remote, "apps", args.app_name, "schema"), args.api_key, payload
            )
            print(f"Schema updated (revision {body.get('revision')})")
            return 0

        print(f"Unknown schema command: {args.schema_command}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def cmd_history(args: argparse.Namespace) -> int:
    """Inspect a remote app's revision history (list / show)."""
    try:
        if args.history_command == "list":
            body = remote_json(
                "GET", _api_url(args.remote, "apps", args.app_name, "history"), args.api_key
            )
            entries = body.get("data", [])
            if args.format in ("json", "yaml"):
                print(format_output(entries, args.format))
            elif not entries:
                print("No history.")
            else:
                for entry in entries:
                    schema_note = "schema" if entry.get("schema") else "no schema"
                    print(
                        f"rev {entry['revision']}  {entry.get('updated_at')}  "
                        f"{entry.get('config_count', 0)} keys  {schema_note}"
                    )
            return 0

        if args.history_command == "show":
            body = remote_json(
                "GET",
                _api_url(args.remote, "apps", args.app_name, "history", str(args.revision)),
                args.api_key,
            )
            print(format_output(body.get("data"), args.format))
            return 0

        print(f"Unknown history command: {args.history_command}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def cmd_rollback(args: argparse.Namespace) -> int:
    """Restore a remote app's config and schema from a history revision."""
    try:
        payload: dict = {"revision": args.revision}
        if args.expected_revision is not None:
            payload["expected_revision"] = args.expected_revision
        body = remote_json(
            "POST", _api_url(args.remote, "apps", args.app_name, "rollback"),
            args.api_key, payload,
        )
        print(f"{body.get('message')} (now at revision {body.get('revision')})")
        return 0
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def cmd_watch(args: argparse.Namespace) -> int:
    """Stream config updates for an app: current config first, then each change."""
    if not HAS_REMOTE_DEPS:
        print("Remote connection requires: pip install nacho-python[remote]", file=sys.stderr)
        return 1
    import threading

    from nacho.storage.remote import RemoteStorageBackend

    try:
        backend = RemoteStorageBackend(
            url=args.remote, app_name=args.app_name, api_key=args.api_key
        )
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

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
    return 0


def main_cli() -> int:
    """
    Main CLI entry point.
    """
    parser = create_parser()

    args = parser.parse_args()
    logging.basicConfig(level=logging.DEBUG if args.debug else logging.WARNING)

    if not args.command:
        parser.print_help()
        return 1

    # Command dispatch
    commands = {
        "server": cmd_server,
        "get": cmd_get,
        "set": cmd_set,
        "delete": cmd_delete,
        "validate": cmd_validate,
        "init": cmd_init,
        "apps": cmd_apps,
        "schema": cmd_schema,
        "history": cmd_history,
        "rollback": cmd_rollback,
        "watch": cmd_watch,
    }

    if args.command in commands:
        return commands[args.command](args)
    else:
        print(f"Unknown command: {args.command}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main_cli())
