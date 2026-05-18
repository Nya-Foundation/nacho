# Nacho

```text
 _   _     _      ____  _   _   ___
| \ | |   / \    / ___|| | | | / _ \
|  \| |  / _ \  | |    | |_| || | | |
| |\  | / ___ \ | |___ |  _  || |_| |
|_| \_|/_/   \_\ \____||_| |_| \___/
```

<div align="center">

  <h3>Lightweight, schema-first dynamic configuration service for Python.</h3>

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
    <a href="https://github.com/nya-foundation/nacho/actions/workflows/scan.yml"><img src="https://github.com/nya-foundation/nacho/actions/workflows/scan.yml/badge.svg" alt="CodeQL & Dependencies Scan"/></a>
    <a href="https://github.com/nya-foundation/nacho/actions/workflows/publish.yml"><img src="https://github.com/nya-foundation/nacho/actions/workflows/publish.yml/badge.svg" alt="CI/CD Builds"/></a>
  </div>
</div>

> **Note:** This project is under active development. If you encounter unexpected behavior, please open an issue on GitHub.

## What is Nacho?

Nacho is a schema-first dynamic configuration service for Python applications.
It handles YAML, JSON, and TOML configuration files and provides a consistent API across local files, in-memory dicts, and remote configuration servers.

| Feature | Description |
|---|---|
| **Multi-format support** | Read and write YAML, JSON, and TOML with a unified API. |
| **Schema-first validation** | Validate every write against a JSON Schema — invalid data is rejected before it reaches storage. |
| **Event system** | Register handlers that fire on specific configuration changes, keyed by dot-notation path patterns. |
| **Environment overrides** | Overlay environment variables at runtime without writing them back to storage. |
| **Remote configuration** | Connect to a Nacho API server for centralized configuration and optional WebSocket push. |
| **Thread safe** | All read/write operations are protected by a reentrant lock. |
| **Pluggable storage** | Swap in file, in-memory, or remote backends without changing application code. |

## Prerequisites

- Python 3.9 or higher
- Docker (optional, for containerized deployment)

## Installation

Nacho uses optional extras to keep the core dependency footprint small.

```bash
# Core — local file management only
pip install nacho-python

# With web server and REST API
pip install nacho-python[server]

# With JSON Schema validation
pip install nacho-python[schema]

# With remote client
pip install nacho-python[remote]

# Everything
pip install nacho-python[all]

# Development and testing
pip install nacho-python[dev]
```

| Extra | Dependencies | Purpose |
|---|---|---|
| *(none)* | pyyaml, tomli-w | Local file read/write (YAML, JSON, TOML) |
| `server` | fastapi, uvicorn, websockets | REST API and WebSocket watch server |
| `schema` | jsonschema, rfc3987 | JSON Schema validation on writes |
| `remote` | requests, websocket-client | Remote configuration client |
| `all` | All of the above | Complete installation |
| `dev` | pytest, httpx, coverage | Development and testing |

## Quick Start

```python
from nacho import Nacho

# File-backed configuration (file is created if it does not exist)
config = Nacho("config.yaml", events=True)

# Register a handler that fires when any key under "database" changes
@config.on_change("database.*")
def on_db_change(path, old_value, new_value, **kwargs):
    print(f"{path}: {old_value} -> {new_value}")

# Read values with dot-notation keys
host = config.get("database.host", default="localhost")
port = config.get_int("database.port", default=5432)

# Write values — triggers registered handlers
config.set("database.pool_size", 10)

# Persist to disk
config.save()
```

## Configuration Management

Nacho accepts a file path, a dict, or an explicit storage backend.

```python
from nacho import Nacho

# In-memory with initial data
config = Nacho({"database": {"host": "127.0.0.1", "port": 5432}})

# File-backed
config = Nacho("config.yaml")

# Read with type coercion
host    = config.get("database.host")            # str
port    = config.get_int("database.port")        # int
debug   = config.get_bool("app.debug")           # bool
tags    = config.get_list("app.tags")            # list
options = config.get_dict("app.options")         # dict

# Deep-merge additional keys (does not remove existing keys)
config.update({"logging": {"level": "DEBUG"}})

# Replace the entire config
config.replace({"database": {"host": "prod-db", "port": 5432}})

# Delete a key
config.delete("legacy.setting")

# Reload from storage and re-apply env overrides
config.reload()

# Export current config as a JSON string
print(config.json())
```

### Atomic transactions

Group multiple writes into a single atomic operation. The transaction commits when the block exits cleanly; it is discarded on any exception.

```python
with config.transaction() as txn:
    txn.set("database.host", "new-host")
    txn.set("database.port", 5433)
# Handlers fire once here with the aggregated changes
config.save()
```

## Environment Variable Overrides

Pass `env_prefix` to apply environment variables on top of the configuration at load time. Variable names follow the pattern `{PREFIX}_{NESTED_KEY}`, with nested levels separated by the delimiter (default: `_`).

```bash
export MYAPP_DATABASE_HOST=prod-db.example.com
export MYAPP_DATABASE_PORT=5433
export MYAPP_FEATURES_ENABLED=true
```

```python
config = Nacho(
    "config.yaml",
    env_prefix="MYAPP",
    env_delimiter="_",
)

config.get("database.host")      # "prod-db.example.com"
config.get_int("database.port")  # 5433
config.get_bool("features.enabled")  # True
```

Environment values are coerced to bool, int, float, or JSON objects where possible, and fall back to string otherwise. Env overrides are runtime-only overlays: `save()` persists the stored config, not the effective env-overlaid values.

## Event System

The event system dispatches change notifications after every successful write. Events carry the changed path, old value, new value, and event type.

```python
from nacho import Nacho, EventType

config = Nacho("config.yaml", events=True)

# Fires for any change to a key under "database"
@config.on_change("database.*")
def on_db_change(path, old_value, new_value, **kwargs):
    print(f"database key changed: {path}")

# Fires once per write operation (aggregate event), regardless of which key changed
@config.on_change("@global")
def on_any_change(**kwargs):
    print("config was modified")

# Fires for CREATE or UPDATE events under "cache"
@config.on_event([EventType.CREATE, EventType.UPDATE], path_pattern="cache.*")
def on_cache_change(event_type, path, new_value, **kwargs):
    print(f"{event_type.name} {path} = {new_value}")

config.set("database.host", "new-host")  # triggers on_db_change, on_any_change
config.set("cache.ttl", 600)             # triggers on_cache_change (CREATE)
config.set("cache.ttl", 300)             # triggers on_cache_change (UPDATE)
```

**Path pattern reference:**

| Pattern | Fires when |
|---|---|
| `None` (default) | Any change at any path |
| `"@global"` | Once per write operation (aggregate) |
| `"*"` | Any per-key event (not aggregate) |
| `"database.*"` | Any key nested under `database` |

Handlers may be sync or async. Async handlers are scheduled on the running event loop when one exists, or run via `asyncio.run()` otherwise.

## Schema Validation

Nacho enforces schema on every write. An invalid value raises `ValidationError` before the change is applied — the configuration is never left in an invalid state.

Requires `pip install nacho-python[schema]`.

```json
// schema.json
{
    "type": "object",
    "properties": {
        "database": {
            "type": "object",
            "required": ["host", "port"],
            "properties": {
                "host": {"type": "string"},
                "port": {"type": "integer", "minimum": 1024}
            }
        }
    },
    "required": ["database"]
}
```

```python
from nacho import Nacho, ValidationError

config = Nacho("config.yaml", schema="schema.json")

# Invalid write raises immediately — config is not modified
try:
    config.set("database.port", "not-a-number")
except ValidationError as e:
    print(e.errors)  # list of violation strings

# Inspect the current config against the schema without writing
errors = config.validate()
if errors:
    print("Current config has violations:", errors)

# Validate an arbitrary dict against the schema
errors = config.check({"database": {"host": "localhost", "port": 80}})
print(errors)  # ["port must be >= 1024"]
```

## Remote Configuration

Connect to a Nacho server and optionally receive real-time updates over WebSocket. The client writes through the REST API; the server can push changes back over WebSocket.

Requires `pip install nacho-python[remote]`.

```python
from nacho import Nacho, RemoteStorageBackend

storage = RemoteStorageBackend(
    url="https://config-server.example.com",
    app_name="my-service",
    api_key="secure-key",
    watch=True,  # opt in to WebSocket updates
)

config = Nacho(storage=storage, events=True)

# The API is identical to file-backed usage
host = config.get("database.host")

# Handlers fire on changes pushed from the server
@config.on_change("features.*")
def on_feature_change(path, new_value, **kwargs):
    print(f"feature flag updated: {path} = {new_value}")
```

## REST API Server

`NachoOrchestrator` wraps one or more `Nacho` instances in a FastAPI application.
The server is API-first: use `/docs` for interactive OpenAPI documentation, `/ws/{app}` for live config updates, and `/ui` for the built-in management UI.

Requires `pip install nacho-python[server]`.

```python
from nacho import Nacho, NachoOrchestrator

apps = {
    "my-service": Nacho("config.yaml", events=True),
}

server = NachoOrchestrator(
    apps=apps,
    api_key="secure-key",
    cors_origins=["https://admin.example.com"],
)
server.run(host="0.0.0.0", port=8000)
```

### Management UI

Nacho ships a built-in web UI for managing apps, configurations, and schemas.
Once the server is running it is available at `/ui` — there is no separate
process or build step; the page is a single file served directly by FastAPI.

The UI supports:

- **App management** — list, create, rename, describe, and delete apps.
- **Configuration editing** — a code editor for JSON, YAML, and TOML with
  syntax highlighting, one-click format switching, on-demand validation, and
  revision-aware saves (a stale write surfaces a conflict instead of
  clobbering newer data).
- **Schema editing** — view, edit, or clear an app's JSON Schema after
  creation, in JSON, YAML, or TOML; the current configuration is re-checked
  against the new schema.
- **Live updates** — changes pushed over WebSocket are reflected in real time.

When the server is started with `--api-key`, the UI prompts for the key on
first load and remembers it in the browser. The `/ui` page itself is public so
the sign-in screen can load; every API call behind it stays authenticated.

### Mounting into an existing FastAPI application

```python
from fastapi import FastAPI
from nacho import Nacho, NachoOrchestrator

app = FastAPI(title="My Application")

orchestrator = NachoOrchestrator(
    apps={"config": Nacho("config.yaml", events=True)},
    api_key="secure-key",
)

# Configuration API available under /config
app.mount("/config", orchestrator.app)
```

	Interactive API documentation is available at `/docs` (Swagger) and `/redoc` once the server is running.

### API write format and revisions

The API accepts native JSON objects for config and schema payloads:

```bash
curl -X POST http://localhost:8000/api/apps \
  -H "Authorization: Bearer secure-key" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "my-service",
    "data": {"database": {"host": "localhost", "port": 5432}},
    "schema": {
      "type": "object",
      "properties": {
        "database": {"type": "object"}
      }
    }
  }'
```

The older encoded-string format is still supported for JSON, YAML, and TOML:

```json
{"data": "{\"feature\": true}", "format": "json"}
```

Full-config reads return `ETag` and `X-Nacho-Revision`. Writes can include either `If-Match: "<revision>"` or a JSON `revision` field. If the server has moved ahead, the write returns `409 Conflict` and leaves the config unchanged.

```bash
curl http://localhost:8000/api/apps/my-service/config \
  -H "Authorization: Bearer secure-key" \
  -i

curl -X PUT http://localhost:8000/api/apps/my-service/config/cache.ttl \
  -H "Authorization: Bearer secure-key" \
  -H "If-Match: \"3\"" \
  -H "Content-Type: application/json" \
  -d '{"value": 600}'
```

### API reference

**System**

| Endpoint | Method | Description |
|---|---|---|
| `/health` | GET | Health check and instance summary |
| `/ui` | GET | Built-in web management UI |
| `/api/convert` | POST | Convert a payload between JSON, YAML, and TOML |

**App management**

| Endpoint | Method | Description |
|---|---|---|
| `/api/apps` | GET | List all apps |
| `/api/apps` | POST | Create a new app |
| `/api/apps/{app}` | GET | Get app info |
| `/api/apps/{app}` | PUT | Replace app config and metadata |
| `/api/apps/{app}` | DELETE | Delete an app |
| `/api/apps/{app}/metadata` | PATCH | Update app name or description |

**Configuration**

| Endpoint | Method | Description |
|---|---|---|
| `/api/apps/{app}/config` | GET | Get full configuration |
| `/api/apps/{app}/config` | PUT | Replace full configuration |
| `/api/apps/{app}/config/{path}` | GET | Get value at path |
| `/api/apps/{app}/config/{path}` | PUT | Set value at path |
| `/api/apps/{app}/config/{path}` | DELETE | Delete key at path |
| `/api/apps/{app}/schema` | GET | Get the app's JSON Schema |
| `/api/apps/{app}/schema` | PUT | Replace or clear the app's JSON Schema |
| `/api/apps/{app}/validate` | POST | Validate a config payload against the schema |

**Real-time**

| Endpoint | Protocol | Description |
|---|---|---|
| `/ws/{app}` | WebSocket | Receive configuration change events |

## Command-Line Interface

```bash
nacho --help
nacho --version
```

### Server

```bash
nacho server \
  --config config.yaml \
  --schema schema.json \
  --host 0.0.0.0 \
  --port 8000 \
  --api-key "secure-key" \
  --app-name "my-service" \
  --data-dir ".nacho/apps" \
  --event true \
  --read-only false
```

### Local configuration

```bash
# Create a new config from a template
nacho init config.yaml --template default

# Available templates: empty, default, web-app, api-service, microservice

# Read
nacho get database.host --config config.yaml
nacho get --config config.yaml --format json

# Write
nacho set database.port 5432 --config config.yaml

# Delete
nacho delete legacy.setting --config config.yaml

# Validate against schema
nacho validate --config config.yaml --schema schema.json
```

### Remote

```bash
nacho get database.host \
  --remote http://config-server:8000 \
  --app-name my-service \
  --api-key "secure-key"

# Read full config and include the current remote revision
nacho get \
  --remote http://config-server:8000 \
  --app-name my-service \
  --api-key "secure-key" \
  --format json \
  --show-revision

nacho set cache.ttl 600 \
  --remote http://config-server:8000 \
  --app-name my-service \
  --api-key "secure-key" \
  --revision 3

nacho delete legacy.setting \
  --remote http://config-server:8000 \
  --app-name my-service \
  --api-key "secure-key" \
  --revision 4
```

## Docker

Nacho ships a multi-stage `Dockerfile` that builds a small Alpine-based image
running the REST API server.

```bash
# Build the image
docker build -t nacho .

# Run the server (UI at http://localhost:8000/ui)
docker run -p 8000:8000 nacho

# Run with authentication enabled
docker run -p 8000:8000 nacho \
  nacho server --config config.yaml --api-key "secure-key"

# Mount your own config for the default app
docker run -p 8000:8000 \
  -v "$(pwd)/config.yaml:/app/config.yaml" nacho
```

Or use `docker-compose`:

```bash
docker compose up --build
```

The image entrypoint is `nacho`, and the default command is
`server --config config.yaml`. Append any `nacho server` flags
(`--api-key`, `--read-only`, `--event`, …) to override the defaults. The
container exposes port `8000` and runs as a non-root user.

## Current Limits

- Dot-notation paths are intentionally simple. Literal dots in key names and numeric string keys are ambiguous; prefer nested object keys for now.
- The built-in API key auth is suitable for local, private, or single-tenant deployments. Shared production deployments should add scoped tokens, audit logs, and rate limits in front of the service.
- File-backed server state is best for development and small single-process deployments. Use the storage abstraction as the boundary for a stronger durable backend when you need multi-process or high-availability operation.

## Community

Need help? Open an issue on [GitHub](https://github.com/nya-foundation/nacho/issues) or join the [Nya Foundation Discord](https://discord.gg/jXAxVPSs7K).

## License

MIT — see [LICENSE](LICENSE) for details.
