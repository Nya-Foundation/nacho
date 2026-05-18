# Nacho

<div align="center">

<pre>
 _   _     _      ____  _   _   ___
| \ | |   / \    / ___|| | | | / _ \
|  \| |  / _ \  | |    | |_| || | | |
| |\  | / ___ \ | |___ |  _  || |_| |
|_| \_|/_/   \_\ \____||_| |_| \___/
</pre>

  <h3>面向 Python 的轻量级、自托管动态配置服务。</h3>

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

> **注意：** 本项目正在积极开发中。如果遇到异常行为，请在 GitHub 上提交 issue。

## 什么是 Nacho？

Nacho 是面向 Python 的轻量级、自托管配置**服务**。

运行一个 Nacho 服务器，用几行代码让你的服务连接到它，然后推送配置变更——这些变更会**实时**到达各个服务，无需重新部署、无需重启。每一次变更在写入存储前都会按 JSON Schema 校验，内置的 Web UI 让你统一管理这一切。当你不需要服务器时，同一个库也能以独立模式直接读写本地文件。

| 特性 | 说明 |
|---|---|
| **集中式配置服务器** | 运行一个 Nacho 服务器，通过 REST API、CLI 或 Web UI 统一管理每个服务的配置。 |
| **实时更新** | 客户端通过 WebSocket 订阅，变更发生的瞬间即可看到——无需轮询、无需重启。 |
| **Schema 优先校验** | 每次写入都按 JSON Schema 检查；无效数据在进入存储之前即被拒绝。 |
| **即插即用的 Python 客户端** | `RemoteStorageBackend` 让远程应用拥有与本地文件完全相同的 API——只需替换存储，其余代码无需改动。 |
| **内置管理 UI** | 通过服务器自身托管的单文件 Web UI，以 JSON、YAML 或 TOML 创建应用、编辑配置或 schema。 |
| **多格式** | JSON、YAML 和 TOML 无处不在：API 负载、存储文件以及 UI 编辑器。 |
| **独立模式** | 无需服务器——让 Nacho 指向本地文件或内存字典，作为普通配置库使用。 |

## 前置条件

- Python 3.9 或更高版本
- Docker（可选，用于容器化部署）

## 安装

Nacho 使用可选的 extras，以保持核心依赖的精简。

```bash
# 运行配置服务器
pip install nacho-python[server]

# 将服务连接到服务器（远程客户端）
pip install nacho-python[remote]

# 核心——仅独立的本地文件管理
pip install nacho-python

# 含 JSON Schema 校验
pip install nacho-python[schema]

# 全部功能
pip install nacho-python[all]

# 开发与测试
pip install nacho-python[dev]
```

| Extra | 依赖 | 用途 |
|---|---|---|
| `server` | fastapi, uvicorn, websockets | REST API 与 WebSocket 配置服务器 |
| `remote` | requests, websocket-client | 远程配置客户端 |
| `schema` | jsonschema, rfc3987 | 写入时进行 JSON Schema 校验 |
| *(无)* | pyyaml, tomli-w | 独立的本地文件读写（YAML、JSON、TOML） |
| `all` | 以上全部 | 完整安装 |
| `dev` | pytest, httpx, coverage | 开发与测试 |

## 快速开始

**1. 运行一个 Nacho 服务器**

```bash
pip install nacho-python[server]
nacho server --config config.yaml --api-key "secure-key"
```

服务器现在运行于 `http://localhost:8000`——提供 REST API、WebSocket 推送，以及位于 `/ui` 的内置管理 UI。

**2. 让你的服务连接到它**

```bash
pip install nacho-python[remote]
```

```python
from nacho import Nacho, RemoteStorageBackend

config = Nacho(
    storage=RemoteStorageBackend(
        url="http://localhost:8000",
        app_name="my-service",
        api_key="secure-key",
        watch=True,           # 通过 WebSocket 接收实时更新
    ),
    events=True,
)

# 像本地字典一样读取配置
port = config.get_int("server.port", default=8000)

# 当有人在服务器上修改它时立即响应
@config.on_change("features.*")
def on_flag_change(path, new_value, **kwargs):
    print(f"{path} is now {new_value}")
```

无论从 UI、CLI 还是 API 修改某个值——每个已连接的客户端都会立即看到。

> **不需要服务器？** Nacho 也可以作为独立的、基于文件的库使用：
> `config = Nacho("config.yaml")`。参见[独立的文件存储用法](#独立的文件存储用法)。

## 运行 Nacho 服务器

`NachoOrchestrator` 将一个或多个 `Nacho` 实例封装到 FastAPI 应用中。
该服务器以 API 为先：使用 `/docs` 查看交互式 OpenAPI 文档，`/ws/{app}` 获取实时配置更新，`/ui` 访问内置的管理界面。

需要 `pip install nacho-python[server]`。

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

启动服务器最简单的方式是使用 CLI——参见[命令行界面](#命令行界面)。

### 管理 UI

Nacho 内置了一个用于管理应用、配置和 schema 的 Web UI。
服务器启动后即可在 `/ui` 访问——无需独立的进程或构建步骤；该页面是由 FastAPI 直接提供的单个文件。

该 UI 支持：

- **应用管理** —— 列出、创建、重命名、描述和删除应用。
- **配置编辑** —— 支持 JSON、YAML 和 TOML 的代码编辑器，具备语法高亮、一键格式切换、按需校验，以及基于修订号的保存（过期写入会提示冲突，而不会覆盖更新的数据）。
- **Schema 编辑** —— 在应用创建后查看、编辑或清除其 JSON Schema，支持 JSON、YAML 或 TOML；并会用新 schema 重新检查当前配置。
- **实时更新** —— 通过 WebSocket 推送的变更会实时反映出来。

当服务器以 `--api-key` 启动时，UI 会在首次加载时提示输入密钥，并在浏览器中记住它。`/ui` 页面本身是公开的，以便登录界面能够加载；其背后的每个 API 调用仍保持需要认证。

### 挂载到已有的 FastAPI 应用

```python
from fastapi import FastAPI
from nacho import Nacho, NachoOrchestrator

app = FastAPI(title="My Application")

orchestrator = NachoOrchestrator(
    apps={"config": Nacho("config.yaml", events=True)},
    api_key="secure-key",
)

# 配置 API 挂载在 /config 下
app.mount("/config", orchestrator.app)
```

	服务器运行后，可在 `/docs`（Swagger）和 `/redoc` 访问交互式 API 文档。

### API 写入格式与修订号

API 接受原生 JSON 对象作为配置和 schema 负载：

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

较旧的编码字符串格式对 JSON、YAML 和 TOML 仍然受支持：

```json
{"data": "{\"feature\": true}", "format": "json"}
```

完整配置的读取会返回 `ETag` 和 `X-Nacho-Revision`。写入可以包含 `If-Match: "<revision>"` 头或 JSON 中的 `revision` 字段。如果服务器已经领先，写入会返回 `409 Conflict`，并保持配置不变。

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

### API 参考

**系统**

| 端点 | 方法 | 说明 |
|---|---|---|
| `/health` | GET | 健康检查与实例摘要 |
| `/ui` | GET | 内置的 Web 管理界面 |
| `/api/convert` | POST | 在 JSON、YAML 和 TOML 之间转换负载 |

**应用管理**

| 端点 | 方法 | 说明 |
|---|---|---|
| `/api/apps` | GET | 列出所有应用 |
| `/api/apps` | POST | 创建新应用 |
| `/api/apps/{app}` | GET | 获取应用信息 |
| `/api/apps/{app}` | PUT | 替换应用配置与元数据 |
| `/api/apps/{app}` | DELETE | 删除应用 |
| `/api/apps/{app}/metadata` | PATCH | 更新应用名称或描述 |

**配置**

| 端点 | 方法 | 说明 |
|---|---|---|
| `/api/apps/{app}/config` | GET | 获取完整配置 |
| `/api/apps/{app}/config` | PUT | 替换完整配置 |
| `/api/apps/{app}/config/{path}` | GET | 获取指定路径的值 |
| `/api/apps/{app}/config/{path}` | PUT | 设置指定路径的值 |
| `/api/apps/{app}/config/{path}` | DELETE | 删除指定路径的键 |
| `/api/apps/{app}/schema` | GET | 获取应用的 JSON Schema |
| `/api/apps/{app}/schema` | PUT | 替换或清除应用的 JSON Schema |
| `/api/apps/{app}/validate` | POST | 对照 schema 校验配置负载 |

**实时**

| 端点 | 协议 | 说明 |
|---|---|---|
| `/ws/{app}` | WebSocket | 接收配置变更事件 |

## 远程客户端

远程客户端连接到 Nacho 服务器，并可选择通过 WebSocket 接收实时更新。客户端通过 REST API 写入；服务器通过 WebSocket 将变更推送回来。一旦构造完成，基于远程后端的 `Nacho` 实例的行为与基于文件的实例**完全一致**——相同的 `get`、`set`、`on_change` 和 schema API。

需要 `pip install nacho-python[remote]`。

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
    watch=True,  # 选择启用 WebSocket 更新
)

config = Nacho(storage=storage, events=True)

# API 与基于文件的用法完全一致
host = config.get("database.host")

# 处理器在服务器推送的变更上触发
@config.on_change("features.*")
def on_feature_change(path, new_value, **kwargs):
    print(f"feature flag updated: {path} = {new_value}")
```

你也可以完全不使用 SDK，直接从[命令行](#远程)访问服务器：

```bash
nacho get database.host --remote http://config-server:8000 --app-name my-service
```

## 事件系统

事件系统会在每次成功写入后派发变更通知——无论变更是在本地发生的，还是**从 Nacho 服务器推送而来的**。事件携带变更的路径、旧值、新值和事件类型。

```python
from nacho import Nacho, EventType

config = Nacho("config.yaml", events=True)

# 对 "database" 下任意键的变更触发
@config.on_change("database.*")
def on_db_change(path, old_value, new_value, **kwargs):
    print(f"database key changed: {path}")

# 每次写入操作触发一次（聚合事件），无论变更了哪个键
@config.on_change("@global")
def on_any_change(**kwargs):
    print("config was modified")

# 对 "cache" 下的 CREATE 或 UPDATE 事件触发
@config.on_event([EventType.CREATE, EventType.UPDATE], path_pattern="cache.*")
def on_cache_change(event_type, path, new_value, **kwargs):
    print(f"{event_type.name} {path} = {new_value}")

config.set("database.host", "new-host")  # 触发 on_db_change、on_any_change
config.set("cache.ttl", 600)             # 触发 on_cache_change（CREATE）
config.set("cache.ttl", 300)             # 触发 on_cache_change（UPDATE）
```

**路径模式参考：**

| 模式 | 触发时机 |
|---|---|
| `None`（默认） | 任意路径上的任意变更 |
| `"@global"` | 每次写入操作触发一次（聚合） |
| `"*"` | 任意按键事件（非聚合） |
| `"database.*"` | `database` 下嵌套的任意键 |

处理器可以是同步或异步的。异步处理器在存在运行中的事件循环时被调度到该循环上，否则通过 `asyncio.run()` 运行。

## Schema 校验

Nacho 在每次写入时强制执行 schema。无效的值会在变更应用之前立即抛出 `ValidationError`——配置永远不会处于无效状态。这对本地写入和服务器接受的数据同样适用。

需要 `pip install nacho-python[schema]`。

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

# 无效写入会立即抛出异常——配置不会被修改
try:
    config.set("database.port", "not-a-number")
except ValidationError as e:
    print(e.errors)  # 违规信息字符串列表

# 在不写入的情况下，对照 schema 检查当前配置
errors = config.validate()
if errors:
    print("Current config has violations:", errors)

# 对照 schema 校验任意字典
errors = config.check({"database": {"host": "localhost", "port": 80}})
print(errors)  # ["port must be >= 1024"]
```

## 独立的文件存储用法

Nacho 并不要求一定有服务器。让它指向本地文件（或直接传入一个普通字典），它就能作为一个自包含的配置库使用——非常适合脚本、测试和单进程应用。无论 Nacho 由文件、字典还是远程服务器支撑，下面的内容都同样适用。

### 配置管理

Nacho 接受文件路径、字典或显式的存储后端。

```python
from nacho import Nacho

# 带初始数据的内存配置
config = Nacho({"database": {"host": "127.0.0.1", "port": 5432}})

# 基于文件的配置
config = Nacho("config.yaml")

# 带类型转换的读取
host    = config.get("database.host")            # str
port    = config.get_int("database.port")        # int
debug   = config.get_bool("app.debug")           # bool
tags    = config.get_list("app.tags")            # list
options = config.get_dict("app.options")         # dict

# 深度合并额外的键（不会移除已有的键）
config.update({"logging": {"level": "DEBUG"}})

# 替换整个配置
config.replace({"database": {"host": "prod-db", "port": 5432}})

# 删除一个键
config.delete("legacy.setting")

# 从存储重新加载并重新应用环境变量覆盖
config.reload()

# 将当前配置导出为 JSON 字符串
print(config.json())
```

### 原子事务

将多次写入组合为单个原子操作。代码块正常退出时事务提交；发生任何异常时事务被丢弃。

```python
with config.transaction() as txn:
    txn.set("database.host", "new-host")
    txn.set("database.port", 5433)
# 处理器在此处携带聚合后的变更触发一次
config.save()
```

### 环境变量覆盖

传入 `env_prefix` 可在加载时将环境变量叠加到配置之上。变量名遵循 `{PREFIX}_{NESTED_KEY}` 模式，嵌套层级以分隔符（默认：`_`）分隔。

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

环境变量的值在可能时会被转换为 bool、int、float 或 JSON 对象，否则回退为字符串。环境变量覆盖仅在运行时叠加：`save()` 持久化的是已存储的配置，而非叠加环境变量后的有效值。

## 命令行界面

```bash
nacho --help
nacho --version
```

### 服务器

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

### 远程

```bash
nacho get database.host \
  --remote http://config-server:8000 \
  --app-name my-service \
  --api-key "secure-key"

# 读取完整配置并包含当前的远程修订号
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

### 本地配置

```bash
# 从模板创建新配置
nacho init config.yaml --template default

# 可用模板：empty、default、web-app、api-service、microservice

# 读取
nacho get database.host --config config.yaml
nacho get --config config.yaml --format json

# 写入
nacho set database.port 5432 --config config.yaml

# 删除
nacho delete legacy.setting --config config.yaml

# 对照 schema 校验
nacho validate --config config.yaml --schema schema.json
```

## Docker

Nacho 提供了一个多阶段 `Dockerfile`，构建出运行配置服务器的小型 Alpine 镜像。已发布的镜像可从 Docker Hub 和 GHCR 获取：

```bash
# 从 Docker Hub 拉取
docker pull k3scat/nacho:latest

# 从 GitHub Container Registry 拉取
docker pull ghcr.io/nya-foundation/nacho:latest

# 构建镜像
docker build -t nacho .

# 运行服务器（UI 位于 http://localhost:8000/ui）
docker run -p 8000:8000 k3scat/nacho:latest

# 启用认证运行
docker run -p 8000:8000 ghcr.io/nya-foundation/nacho:latest \
  server --config config.yaml --api-key "secure-key"

# 为默认应用挂载你自己的配置
docker run -p 8000:8000 \
  -v "$(pwd)/config.yaml:/app/config.yaml" k3scat/nacho:latest
```

或使用 `docker-compose`：

```bash
docker compose up --build
```

镜像的入口点是 `nacho`，默认命令是 `server --config config.yaml`。追加任意 `nacho server` 标志（`--api-key`、`--read-only`、`--event` 等）即可覆盖默认值。容器暴露端口 `8000`，并以非 root 用户运行。

## 当前限制

- 点号路径有意保持简单。键名中的字面点号和数字字符串键存在歧义；目前请优先使用嵌套对象键。
- 内置的 API 密钥认证适用于本地、私有或单租户部署。共享的生产部署应在服务前面增加作用域令牌、审计日志和速率限制。
- 基于文件的服务器状态最适合开发和小型单进程部署。当需要多进程或高可用运行时，请以存储抽象为边界，接入更强的持久化后端。

## 社区

需要帮助？请在 [GitHub](https://github.com/nya-foundation/nacho/issues) 上提交 issue，或加入 [Nya Foundation Discord](https://discord.gg/jXAxVPSs7K)。

## 许可证

MIT —— 详见 [LICENSE](LICENSE)。
