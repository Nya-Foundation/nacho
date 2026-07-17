# Nacho

<div align="center">

<pre>
 _   _     _      ____  _   _   ___
| \ | |   / \    / ___|| | | | / _ \
|  \| |  / _ \  | |    | |_| || | | |
| |\  | / ___ \ | |___ |  _  || |_| |
|_| \_|/_/   \_\ \____||_| |_| \___/
</pre>

  <h3>Lightweight, self-hosted dynamic configuration service for Python</h3>

  <p>
    <a href="README.md">English</a> |
    <a href="README_zh.md">中文</a> |
    <a href="README_ja.md">日本語</a>
  </p>

  <div>
    <a href="https://pypi.org/project/nacho-python/"><img src="https://img.shields.io/pypi/v/nacho-python.svg" alt="PyPI version"/></a>
    <a href="https://pypi.org/project/nacho-python/"><img src="https://img.shields.io/pypi/pyversions/nacho-python.svg" alt="Python versions"/></a>
    <a href="https://github.com/nya-foundation/nacho/blob/main/LICENSE"><img src="https://img.shields.io/github/license/nya-foundation/nacho.svg" alt="License"/></a>
    <a href="https://pepy.tech/projects/nacho-python"><img src="https://static.pepy.tech/badge/nacho-python" alt="PyPI Downloads"/></a>
    <a href="https://hub.docker.com/r/k3scat/nacho"><img src="https://img.shields.io/docker/pulls/k3scat/nacho" alt="Docker Pulls"/></a>
    <a href="https://deepwiki.com/Nya-Foundation/Nacho"><img src="https://deepwiki.com/badge.svg" alt="Ask DeepWiki"/></a>
  </div>

  <div>
    <a href="https://codecov.io/gh/nya-foundation/nacho"><img src="https://codecov.io/gh/nya-foundation/nacho/branch/main/graph/badge.svg" alt="Code Coverage"/></a>
    <a href="https://github.com/nya-foundation/nacho/actions/workflows/scan.yml"><img src="https://github.com/nya-foundation/nacho/actions/workflows/scan.yml/badge.svg" alt="CodeQL and Dependencies Scan"/></a>
    <a href="https://github.com/nya-foundation/nacho/actions/workflows/publish.yml"><img src="https://github.com/nya-foundation/nacho/actions/workflows/publish.yml/badge.svg" alt="CI/CD Builds"/></a>
  </div>
</div>

## Overview

Nacho is a self-hosted configuration service for Python. Run one Nacho server,
point your services at it with a few lines of code, and push configuration
changes that reach them live — no redeploy, no restart, no polling.

Every write is validated against a JSON Schema before it is stored, every
revision is kept in a rollback history, and a built-in single-file web UI
manages all of it. When you do not need a server, the same library works
standalone against a local file or an in-memory dict.

| Capability | Description |
|---|---|
| Centralized configuration | One server manages every service's configuration through a REST API, a CLI, and a web UI. |
| Live updates | Clients subscribe over WebSocket and receive changes the moment they happen. |
| Schema-first validation | Writes are checked against a JSON Schema and rejected before they reach storage. |
| History and rollback | Every revision is snapshotted; any revision can be inspected and restored. |
| Drop-in Python client | `RemoteStorageBackend` gives a remote application the same API as a local file. |
| Optimistic concurrency | Revision-checked writes turn lost updates into explicit `409 Conflict` responses. |
| Multi-format | JSON, YAML, and TOML are interchangeable across API payloads, stored files, and the UI editor. |
| Standalone mode | Use Nacho as a plain configuration library with no server at all. |

## Installation

Nacho keeps its core dependency footprint small through optional extras:

```bash
pip install nacho-python[server]    # run a configuration server
pip install nacho-python[remote]    # connect a service to a server
pip install nacho-python[schema]    # JSON Schema validation for standalone use
pip install nacho-python            # core: standalone local file management
```

Requires Python 3.9 or later. Docker images are available for containerized
deployments (see [Docker](#docker)).

## Quick start

Start a server:

```bash
pip install nacho-python[server]
nacho server --config config.yaml --api-key "secure-key"
```

The server is now live at `http://127.0.0.1:8000` with a REST API, WebSocket
push, interactive API docs at `/docs`, and a management UI at `/ui`.

Connect a service:

```bash
pip install nacho-python[remote]
```

```python
from nacho import Nacho, RemoteStorageBackend

config = Nacho(
    storage=RemoteStorageBackend(
        url="http://127.0.0.1:8000",
        app_name="my-service",
        api_key="secure-key",
        watch=True,            # receive live updates over WebSocket
    ),
    events=True,
)

# Read configuration exactly like a local dict
port = config.get_int("server.port", default=8000)

# React the instant someone changes it on the server
@config.on_change("features.*")
def on_flag_change(path, new_value, **kwargs):
    print(f"{path} is now {new_value}")
```

Change a value from the UI, the CLI, or the API, and every connected client
sees it immediately.

No server needed? Nacho also works as a standalone file-backed library:
`config = Nacho("config.yaml")`. See
[Standalone usage](#standalone-usage).

## Running a server

The CLI is the usual way to run a server:

```bash
nacho server \
  --config config.yaml \
  --schema schema.json \
  --port 8000 \
  --api-key "secure-key" \
  --data-dir ".nacho/apps" \
  --history-limit 50
```

The server binds to `127.0.0.1` by default. Pass `--host 0.0.0.0` to accept
connections from other machines; the CLI prints a warning if you expose the
server without `--api-key`, because an unauthenticated server grants full
write access to anyone who can reach it.

| Flag | Default | Description |
|---|---|---|
| `--host` | `127.0.0.1` | Bind address (`0.0.0.0` to listen on all interfaces) |
| `--port` | `8000` | Bind port |
| `--config`, `-c` | none | Configuration file to serve as an app |
| `--schema` | none | JSON Schema enforced for `--config` |
| `--app-name` | `default` | App name for the `--config` file |
| `--data-dir` | none | Directory for API-created app state and history |
| `--api-key` | none | Enable bearer-token authentication |
| `--history-limit` | `50` | Revision snapshots kept per app (`0` disables history) |
| `--read-only` | off | Reject every write |
| `--reload` | off | Auto-reload for development |

### Embedding in an existing application

`NachoOrchestrator` wraps one or more `Nacho` instances in a FastAPI
application, so a server can also be constructed in code or mounted into an
existing app:

```python
from fastapi import FastAPI
from nacho import Nacho, NachoOrchestrator

app = FastAPI(title="My Application")

orchestrator = NachoOrchestrator(
    apps={"config": Nacho("config.yaml", events=True)},
    api_key="secure-key",
    cors_origins=["https://admin.example.com"],
)

app.mount("/config", orchestrator.app)   # configuration API under /config
```

Run it directly with `orchestrator.run(host="127.0.0.1", port=8000)` when it
is not mounted.

### Management UI

The server hosts a single-file web UI at `/ui` — no separate process, no build
step. It provides:

- App management: list, create, rename, describe, and delete apps.
- Configuration editing: a code editor for JSON, YAML, and TOML with syntax
  highlighting, format switching, on-demand validation, and revision-aware
  saves that surface conflicts instead of clobbering newer data.
- Schema editing: view, edit, or clear an app's JSON Schema; the current
  configuration is re-checked against the new schema before it is accepted.
- History: browse revision snapshots and restore any of them with one click.
- Live updates: changes pushed over WebSocket are reflected in real time, and
  unsaved local edits are preserved when a remote change arrives.

When the server runs with `--api-key`, the UI prompts for the key on first
load. The `/ui` page itself is public so the sign-in screen can load; every
API call behind it requires authentication.

### Authentication

Passing `--api-key` (or `api_key=` to `NachoOrchestrator`) enables bearer
authentication for the whole API. Clients send the key either as an
`Authorization: Bearer <key>` header or through the cookie the UI sets for
its own WebSocket handshake. Requests with a missing or wrong key receive
`401 Unauthorized`. The comparison is timing-safe.

`/health`, `/ui`, `/docs`, `/redoc`, and `/openapi.json` stay public: the API
surface is not a secret, only the data behind it.

## REST API

Interactive documentation is available at `/docs` (Swagger UI) and `/redoc`
once the server is running.

### Payload format

Config and schema payloads are native JSON objects:

```bash
curl -X POST http://127.0.0.1:8000/api/apps \
  -H "Authorization: Bearer secure-key" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "my-service",
    "data": {"database": {"host": "localhost", "port": 5432}},
    "schema": {"type": "object", "properties": {"database": {"type": "object"}}}
  }'
```

Payloads may also be sent as encoded strings in any supported format, which
is how the CLI and UI submit YAML and TOML:

```json
{"data": "database:\n  host: localhost\n", "format": "yaml"}
```

### Revisions and optimistic concurrency

Every app carries a monotonically increasing revision, bumped on each
successful write. Reads of `/config` (full or per-path) return the current
revision in the `ETag` and `X-Nacho-Revision` response headers. Writes may
include a `revision` field stating the revision the client last saw; if the
server has moved on, the write fails with `409 Conflict` and the stored
configuration is left untouched:

```bash
curl -X PUT http://127.0.0.1:8000/api/apps/my-service/config/cache.ttl \
  -H "Authorization: Bearer secure-key" \
  -H "Content-Type: application/json" \
  -d '{"value": 600, "revision": 3}'
```

Omitting `revision` performs an unconditional write.

### History and rollback

The server snapshots every revision (configuration, schema, and metadata)
into a per-app ring buffer — on disk under `data_dir/history/` when a data
directory is configured, in memory otherwise. `--history-limit` controls
retention.

Rollback is roll-forward: restoring revision 41 does not rewrite history but
creates a new revision whose content equals snapshot 41. The revision counter
stays monotonic, live clients are notified like on any other write, and a
rollback can itself be rolled back. A snapshot restores configuration and
schema together, so the result is always self-consistent.

```bash
curl http://127.0.0.1:8000/api/apps/my-service/history
curl http://127.0.0.1:8000/api/apps/my-service/history/41
curl -X POST http://127.0.0.1:8000/api/apps/my-service/rollback \
  -H "Content-Type: application/json" \
  -d '{"revision": 41, "expected_revision": 42}'
```

### Endpoint reference

System:

| Endpoint | Method | Description |
|---|---|---|
| `/health` | GET | Health check and instance summary |
| `/ui` | GET | Built-in web management UI |
| `/docs`, `/redoc` | GET | Interactive API documentation |
| `/api/convert` | POST | Convert a payload between JSON, YAML, and TOML |

App management:

| Endpoint | Method | Description |
|---|---|---|
| `/api/apps` | GET | List all apps |
| `/api/apps` | POST | Create an app |
| `/api/apps/{app}` | GET | Get app info |
| `/api/apps/{app}` | PUT | Replace an app's config, schema, and description |
| `/api/apps/{app}` | DELETE | Delete an app |
| `/api/apps/{app}/metadata` | PATCH | Rename an app or change its description |

Configuration and schema:

| Endpoint | Method | Description |
|---|---|---|
| `/api/apps/{app}/config` | GET | Get the full configuration |
| `/api/apps/{app}/config` | PUT | Replace the full configuration |
| `/api/apps/{app}/config/{path}` | GET | Get the value at a dotted path |
| `/api/apps/{app}/config/{path}` | PUT | Set the value at a dotted path |
| `/api/apps/{app}/config/{path}` | DELETE | Delete the key at a dotted path |
| `/api/apps/{app}/schema` | GET | Get the app's JSON Schema |
| `/api/apps/{app}/schema` | PUT | Replace or clear the app's JSON Schema |
| `/api/apps/{app}/validate` | POST | Validate a payload against the app's schema |

History:

| Endpoint | Method | Description |
|---|---|---|
| `/api/apps/{app}/history` | GET | List revision snapshots, newest first |
| `/api/apps/{app}/history/{revision}` | GET | Get one revision snapshot |
| `/api/apps/{app}/rollback` | POST | Restore a snapshot as a new revision |

Real-time:

| Endpoint | Protocol | Description |
|---|---|---|
| `/ws/{app}` | WebSocket | Receive the current config on subscribe, then every change |

The WebSocket is receive-only: the server sends an `initial_config` message
on subscribe followed by an `update` message per change, each carrying the
app name, revision, and full configuration. Writes always go through REST, so
there is never ambiguity about who owns the state.

## Remote clients

A remote client reads and writes through the REST API and receives pushes
over WebSocket. Once constructed, a remote-backed `Nacho` instance behaves
exactly like a file-backed one — the same `get`, `set`, `on_change`, and
schema APIs.

Requires `pip install nacho-python[remote]`.

```text
                 REST reads/writes
  +-------------+  GET/PUT/PATCH/DELETE   +----------------------+
  | Python app  | -----------------------> | Nacho server         |
  | Nacho       |                          | REST API + Web UI    |
  | Remote      | <----------------------- | File/dict storage    |
  | client      |    WebSocket pushes      | Schema validation    |
  +-------------+       /ws/{app}          +----------------------+
         |                                             ^
         | on_change handlers                          |
         +---------------------------------------------+
                    live config updates
```

```python
from nacho import Nacho, RemoteStorageBackend

storage = RemoteStorageBackend(
    url="https://config-server.example.com",
    app_name="my-service",
    api_key="secure-key",
    watch=True,               # opt in to WebSocket updates
)

config = Nacho(storage=storage, events=True)

host = config.get("database.host")

@config.on_change("features.*")
def on_feature_change(path, new_value, **kwargs):
    print(f"feature flag updated: {path} = {new_value}")
```

Connecting never mutates the server. Reading a nonexistent app raises a clear
error (so a typo cannot silently return an empty config), while the first
`save()` to a nonexistent app creates it. If the WebSocket connection drops,
the watcher reconnects automatically with a bounded number of consecutive
retries (`reconnect=0` retries forever), and the counter resets on every
successful connection.

The CLI covers the same ground without the SDK — see
[Command-line interface](#command-line-interface).

## Event system

With `events=True`, Nacho dispatches change notifications after every
successful write, whether the change was made locally or pushed from a
server. Events carry the changed path, old value, new value, and event type.

```python
from nacho import Nacho, EventType

config = Nacho("config.yaml", events=True)

# Fires for any change to a key under "database"
@config.on_change("database.*")
def on_db_change(path, old_value, new_value, **kwargs):
    print(f"database key changed: {path}")

# Fires once per write operation (aggregate event)
@config.on_change("@global")
def on_any_change(**kwargs):
    print("config was modified")

# Fires for CREATE or UPDATE events under "cache"
@config.on_event([EventType.CREATE, EventType.UPDATE], path_pattern="cache.*")
def on_cache_change(event_type, path, new_value, **kwargs):
    print(f"{event_type.name} {path} = {new_value}")

config.set("database.host", "new-host")  # on_db_change, on_any_change
config.set("cache.ttl", 600)             # on_cache_change (CREATE)
config.set("cache.ttl", 300)             # on_cache_change (UPDATE)
```

Path pattern reference:

| Pattern | Fires when |
|---|---|
| `None` (default) | Any change at any path |
| `"@global"` | Once per write operation (aggregate) |
| `"*"` | Any per-key event (not the aggregate) |
| `"database.*"` | Any key nested under `database` |

Handlers may be sync or async. Async handlers are scheduled on the running
event loop when one exists, and executed with `asyncio.run()` otherwise.
Registering a handler on an instance created without `events=True` logs a
warning, because the handler would never fire.

## Schema validation

Nacho enforces the schema on every write. An invalid value raises
`ValidationError` before the change is applied, so the configuration is never
left in an invalid state. The same guarantee applies to local writes and to
writes accepted by the server.

Standalone usage requires `pip install nacho-python[schema]`.

```json
{
    "type": "object",
    "required": ["database"],
    "properties": {
        "database": {
            "type": "object",
            "required": ["host", "port"],
            "properties": {
                "host": {"type": "string"},
                "port": {"type": "integer", "minimum": 1024}
            }
        }
    }
}
```

```python
from nacho import Nacho, ValidationError

config = Nacho("config.yaml", schema="schema.json")

# An invalid write raises immediately; the config is not modified
try:
    config.set("database.port", "not-a-number")
except ValidationError as e:
    print(e.errors)                 # list of violation strings

# Inspect the current config without writing
errors = config.validate()

# Validate an arbitrary dict against the schema
errors = config.check({"database": {"host": "localhost", "port": 80}})
```

## Standalone usage

Nacho does not require a server. Point it at a local file, or hand it a plain
dict, and it works as a self-contained configuration library for scripts,
tests, and single-process applications. Everything below behaves identically
with a file, a dict, or a remote server behind it.

### Reading and writing

```python
from nacho import Nacho

config = Nacho({"database": {"host": "127.0.0.1", "port": 5432}})  # in-memory
config = Nacho("config.yaml")                                      # file-backed

# Typed reads with sensible coercion
host    = config.get("database.host")
port    = config.get_int("database.port")
debug   = config.get_bool("app.debug")
tags    = config.get_list("app.tags")
options = config.get_dict("app.options")

config.update({"logging": {"level": "DEBUG"}})   # deep-merge
config.replace({"database": {"host": "prod-db", "port": 5432}})
config.delete("legacy.setting")
config.load()                                    # reload from storage
config.save()                                    # persist to storage
print(config.json())                             # export as a JSON string
```

### Transactions

Group multiple writes into one atomic operation. The transaction commits when
the block exits cleanly and is discarded on any exception:

```python
with config.transaction() as txn:
    txn.set("database.host", "new-host")
    txn.set("database.port", 5433)
# Handlers fire once here with the aggregated changes
config.save()
```

### Environment variable overrides

Pass `env_prefix` to overlay environment variables on the configuration at
load time. Variable names follow `{PREFIX}_{NESTED_KEY}`, with nesting levels
separated by the delimiter (default `_`):

```bash
export MYAPP_DATABASE_HOST=prod-db.example.com
export MYAPP_DATABASE_PORT=5433
export MYAPP_FEATURES_ENABLED=true
```

```python
config = Nacho("config.yaml", env_prefix="MYAPP")

config.get("database.host")          # "prod-db.example.com"
config.get_int("database.port")      # 5433
config.get_bool("features.enabled")  # True
```

Values are coerced where unambiguous: `true`/`false`/`yes`/`no`/`on`/`off`
become booleans, numeric strings become numbers (`"1"` is the integer 1, not
a boolean), and JSON-looking strings are parsed as JSON. Everything else
stays a string. Env overrides are runtime-only overlays: `save()` persists
the stored configuration, not the overlaid view.

## Command-line interface

```bash
nacho --help
nacho --version
```

Every remote command takes `--remote <url>`, `--app-name <name>` (default
`default`), and `--api-key <key>`. Errors are written to stderr and failures
exit non-zero, so the commands compose cleanly in scripts and pipelines.

### Values

```bash
# Read a key, or the whole config, locally or remotely
nacho get database.host --config config.yaml
nacho get --format json --remote http://config-server:8000 --app-name my-service

# Include the current revision in the output
nacho get --show-revision --format json --remote http://config-server:8000

# Write and delete, with optional conflict-safe revision checks
nacho set cache.ttl 600 --remote http://config-server:8000 --revision 3
nacho delete legacy.setting --remote http://config-server:8000 --revision 4

# Local file equivalents
nacho set database.port 5432 --config config.yaml
nacho delete legacy.setting --config config.yaml
```

### Apps

```bash
nacho apps list --remote http://config-server:8000
nacho apps create my-service \
  --remote http://config-server:8000 \
  --description "Core service" \
  --config config.yaml \
  --schema schema.json
nacho apps delete my-service --remote http://config-server:8000
```

### Schemas and validation

```bash
# Print or replace the schema the server enforces
nacho schema get --remote http://config-server:8000 --app-name my-service
nacho schema push schema.json --remote http://config-server:8000 --app-name my-service

# Validate a local file against the server's stored schema
nacho validate --config config.yaml --remote http://config-server:8000 --app-name my-service

# Validate against a local schema file instead
nacho validate --config config.yaml --schema schema.json
```

### History and rollback

```bash
nacho history list --remote http://config-server:8000 --app-name my-service
nacho history show 41 --remote http://config-server:8000 --app-name my-service

# Restore revision 41 as a new revision; --revision-check makes it conflict-safe
nacho rollback 41 --remote http://config-server:8000 --app-name my-service --revision-check 42
```

### Live updates

```bash
# Print the current config, then one JSON line per change (Ctrl+C to stop)
nacho watch --remote http://config-server:8000 --app-name my-service
```

### Scaffolding

```bash
# Create a config file from a built-in template
nacho init config.yaml --template default
# Templates: empty, default, web-app, api-service, microservice
```

## Docker

Nacho ships a multi-stage `Dockerfile` producing a small Alpine-based image
that runs the configuration server as a non-root user, with a container
health check against `/health`. Published images are available on Docker Hub
and GHCR:

```bash
docker pull k3scat/nacho:latest
docker pull ghcr.io/nya-foundation/nacho:latest

# Run the server (UI at http://localhost:8000/ui)
docker run -p 8000:8000 k3scat/nacho:latest

# Run with authentication enabled
docker run -p 8000:8000 k3scat/nacho:latest \
  server --host 0.0.0.0 --config config.yaml --api-key "secure-key"

# Mount your own config for the default app
docker run -p 8000:8000 \
  -v "$(pwd)/config.yaml:/app/config.yaml" k3scat/nacho:latest
```

Or with Compose:

```bash
docker compose up --build
```

The image entrypoint is `nacho`; the default command is
`server --host 0.0.0.0 --config config.yaml`. Append any `nacho server` flags
to override the defaults. The container exposes port `8000`.

## Operational notes

- Dot-notation paths are intentionally simple. Literal dots in key names and
  numeric string keys are ambiguous; prefer nested object keys.
- The built-in API-key authentication suits local, private, and single-tenant
  deployments. Shared production deployments should add scoped tokens, audit
  logging, and rate limiting in front of the service.
- Server state is file-backed and single-process. The revision counter is
  authoritative in memory, so run one server process per data directory; the
  storage abstraction is the boundary to implement a stronger backend if you
  need multi-process or high-availability operation.
- Editing a `--config` file by hand while the server is running is not
  detected; the server's next write wins. Make changes through the API, CLI,
  or UI.

## Development

```bash
git clone https://github.com/nya-foundation/nacho.git
cd nacho
uv sync --all-extras

uv run pytest                                  # fast suites (unit + smoke), 95% coverage gate
uv run pytest -m "integration or e2e" --no-cov # live-server suites
uv run pytest -m docker --no-cov               # builds and exercises the Docker image
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for the branch model, code style, and
release process.

## Community

Open an issue on [GitHub](https://github.com/nya-foundation/nacho/issues) or
join the [Nya Foundation Discord](https://discord.gg/jXAxVPSs7K).

## License

MIT — see [LICENSE](LICENSE) for details.
