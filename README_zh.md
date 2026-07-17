# Nacho

<div align="center">

<pre>
 _   _     _      ____  _   _   ___
| \ | |   / \    / ___|| | | | / _ \
|  \| |  / _ \  | |    | |_| || | | |
| |\  | / ___ \ | |___ |  _  || |_| |
|_| \_|/_/   \_\ \____||_| |_| \___/
</pre>

  <h3>轻量级、可自托管的 Python 动态配置服务</h3>

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

## 概述

Nacho 是一个可自托管的 Python 配置服务。运行一个 Nacho 服务器，用几行代码将你的服务接入，即可实时推送配置变更——无需重新部署、无需重启、无需轮询。

每次写入都会先经过 JSON Schema 校验再存储，每个修订版本都会保存在回滚历史中，并由内置的单文件 Web UI 统一管理这一切。当你不需要服务器时，同一个库也可以在独立模式下直接使用本地文件或内存字典。

| 能力 | 说明 |
|---|---|
| 集中式配置 | 一个服务器通过 REST API、CLI 和 Web UI 管理所有服务的配置。 |
| 实时更新 | 客户端通过 WebSocket 订阅，变更发生的瞬间即可收到。 |
| 模式优先校验 | 写入会先按 JSON Schema 检查，未通过校验的数据在进入存储前即被拒绝。 |
| 历史与回滚 | 每个修订版本都会生成快照；任意修订版本都可以查看和恢复。 |
| 即插即用的 Python 客户端 | `RemoteStorageBackend` 让远程应用获得与本地文件完全一致的 API。 |
| 乐观并发控制 | 带修订版本检查的写入将丢失更新问题转化为显式的 `409 Conflict` 响应。 |
| 多格式支持 | JSON、YAML 和 TOML 在 API 载荷、存储文件和 UI 编辑器之间可以互换。 |
| 独立模式 | 完全不依赖服务器，将 Nacho 用作普通的配置库。 |

## 安装

Nacho 通过可选的 extras 保持核心依赖足够精简：

```bash
pip install nacho-python[server]    # 运行配置服务器
pip install nacho-python[remote]    # 将服务连接到服务器
pip install nacho-python[schema]    # 独立模式下的 JSON Schema 校验
pip install nacho-python            # 核心：独立的本地文件管理
```

需要 Python 3.9 或更高版本。容器化部署可使用 Docker 镜像（参见 [Docker](#docker)）。

## 快速开始

启动服务器：

```bash
pip install nacho-python[server]
nacho server --config config.yaml --api-key "secure-key"
```

服务器现已运行在 `http://127.0.0.1:8000`，提供 REST API、WebSocket 推送、位于 `/docs` 的交互式 API 文档，以及位于 `/ui` 的管理 UI。

连接一个服务：

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
        watch=True,            # 通过 WebSocket 接收实时更新
    ),
    events=True,
)

# 像读取本地字典一样读取配置
port = config.get_int("server.port", default=8000)

# 服务器端的值一旦被修改，立即作出响应
@config.on_change("features.*")
def on_flag_change(path, new_value, **kwargs):
    print(f"{path} is now {new_value}")
```

在 UI、CLI 或 API 中修改某个值，所有已连接的客户端都会立即看到变更。

不需要服务器？Nacho 也可以作为独立的文件型配置库使用：`config = Nacho("config.yaml")`。参见[独立使用](#独立使用)。

## 运行服务器

通常通过 CLI 运行服务器：

```bash
nacho server \
  --config config.yaml \
  --schema schema.json \
  --port 8000 \
  --api-key "secure-key" \
  --data-dir ".nacho/apps" \
  --history-limit 50
```

服务器默认绑定到 `127.0.0.1`。传入 `--host 0.0.0.0` 可接受来自其他机器的连接；如果在未设置 `--api-key` 的情况下对外暴露服务器，CLI 会打印警告，因为未启用认证的服务器会向任何能访问它的人授予完整的写权限。

| 参数 | 默认值 | 说明 |
|---|---|---|
| `--host` | `127.0.0.1` | 绑定地址（`0.0.0.0` 表示监听所有网络接口） |
| `--port` | `8000` | 绑定端口 |
| `--config`, `-c` | 无 | 作为应用对外提供的配置文件 |
| `--schema` | 无 | 对 `--config` 强制执行的 JSON Schema |
| `--app-name` | `default` | `--config` 文件对应的应用名称 |
| `--data-dir` | 无 | 存放通过 API 创建的应用状态和历史记录的目录 |
| `--api-key` | 无 | 启用 Bearer Token 认证 |
| `--history-limit` | `50` | 每个应用保留的修订版本快照数量（`0` 表示禁用历史记录） |
| `--read-only` | 关闭 | 拒绝所有写入 |
| `--reload` | 关闭 | 开发用的自动重载 |

### 嵌入到现有应用中

`NachoOrchestrator` 将一个或多个 `Nacho` 实例封装为 FastAPI 应用，因此服务器也可以在代码中构建，或挂载到现有应用中：

```python
from fastapi import FastAPI
from nacho import Nacho, NachoOrchestrator

app = FastAPI(title="My Application")

orchestrator = NachoOrchestrator(
    apps={"config": Nacho("config.yaml", events=True)},
    api_key="secure-key",
    cors_origins=["https://admin.example.com"],
)

app.mount("/config", orchestrator.app)   # 配置 API 位于 /config 之下
```

不挂载时，可直接通过 `orchestrator.run(host="127.0.0.1", port=8000)` 运行。

### 管理 UI

服务器在 `/ui` 托管一个单文件 Web UI——无需单独进程，也无需构建步骤。它提供：

- 应用管理：列出、创建、重命名、描述和删除应用。
- 配置编辑：支持 JSON、YAML 和 TOML 的代码编辑器，具备语法高亮、格式切换、按需校验，以及带修订版本感知的保存机制——遇到冲突时会明确提示，而不是覆盖更新的数据。
- 模式编辑：查看、编辑或清除应用的 JSON Schema；在接受新模式之前，会先用它重新检查当前配置。
- 历史记录：浏览修订版本快照，并可一键恢复其中任意一个。
- 实时更新：通过 WebSocket 推送的变更会实时反映在界面上，且远程变更到达时会保留未保存的本地编辑。

当服务器以 `--api-key` 运行时，UI 会在首次加载时提示输入密钥。`/ui` 页面本身是公开的，以便登录界面能够加载；其背后的每个 API 调用都需要认证。

### 认证

传入 `--api-key`（或向 `NachoOrchestrator` 传入 `api_key=`）即可为整个 API 启用 Bearer 认证。客户端通过 `Authorization: Bearer <key>` 请求头发送密钥，或使用 UI 为其自身 WebSocket 握手设置的 Cookie。密钥缺失或错误的请求会收到 `401 Unauthorized`。密钥比较采用时序安全（timing-safe）算法。

`/`、`/health`、`/ui`、`/docs`、`/redoc` 和 `/openapi.json` 保持公开：API 的接口定义并不是秘密，需要保护的只是其背后的数据。

除非通过 `cors_origins=[...]` 显式启用，否则跨源浏览器访问处于禁用状态——内置 UI 与服务器同源，而 SDK 和 CLI 并不是浏览器，因此路过式（drive-by）网页无法触及默认配置的服务器。

## REST API

服务器运行后，可在 `/docs`（Swagger UI）和 `/redoc` 访问交互式文档。

### 载荷格式

配置和模式载荷是原生 JSON 对象：

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

载荷也可以以任意受支持格式的编码字符串形式发送，CLI 和 UI 正是以这种方式提交 YAML 和 TOML：

```json
{"data": "database:\n  host: localhost\n", "format": "yaml"}
```

### 修订版本与乐观并发控制

每个应用都带有一个单调递增的修订版本号，每次成功写入后递增。对 `/config` 的读取（完整或按路径）会在 `ETag` 和 `X-Nacho-Revision` 响应头中返回当前修订版本。写入时可以包含 `revision` 字段，声明客户端最后看到的修订版本；如果服务器端的版本已经前进，写入将以 `409 Conflict` 失败，已存储的配置保持不变：

```bash
curl -X PUT http://127.0.0.1:8000/api/apps/my-service/config/cache.ttl \
  -H "Authorization: Bearer secure-key" \
  -H "Content-Type: application/json" \
  -d '{"value": 600, "revision": 3}'
```

省略 `revision` 则执行无条件写入。

### 历史与回滚

服务器将每个修订版本（配置、模式和元数据）快照到按应用划分的环形缓冲区中——配置了数据目录时保存在磁盘上的 `data_dir/history/` 下，否则保存在内存中。`--history-limit` 控制保留数量。

回滚采用向前滚动（roll-forward）的方式：恢复修订版本 41 不会改写历史，而是创建一个内容与快照 41 相同的新修订版本。修订版本计数器保持单调递增，在线客户端会像收到任何其他写入一样收到通知，且一次回滚本身也可以再次被回滚。快照会同时恢复配置和模式，因此结果始终是自洽的。

```bash
curl http://127.0.0.1:8000/api/apps/my-service/history
curl http://127.0.0.1:8000/api/apps/my-service/history/41
curl -X POST http://127.0.0.1:8000/api/apps/my-service/rollback \
  -H "Content-Type: application/json" \
  -d '{"revision": 41, "expected_revision": 42}'
```

### 端点参考

系统：

| 端点 | 方法 | 说明 |
|---|---|---|
| `/health` | GET | 健康检查与实例概要 |
| `/ui` | GET | 内置 Web 管理 UI |
| `/docs`, `/redoc` | GET | 交互式 API 文档 |
| `/api/convert` | POST | 在 JSON、YAML 和 TOML 之间转换载荷 |

应用管理：

| 端点 | 方法 | 说明 |
|---|---|---|
| `/api/apps` | GET | 列出所有应用 |
| `/api/apps` | POST | 创建应用 |
| `/api/apps/{app}` | GET | 获取应用信息 |
| `/api/apps/{app}` | PUT | 替换应用的配置、模式和描述 |
| `/api/apps/{app}` | DELETE | 删除应用 |
| `/api/apps/{app}/metadata` | PATCH | 重命名应用或修改其描述 |

配置与模式：

| 端点 | 方法 | 说明 |
|---|---|---|
| `/api/apps/{app}/config` | GET | 获取完整配置 |
| `/api/apps/{app}/config` | PUT | 替换完整配置 |
| `/api/apps/{app}/config/{path}` | GET | 获取点分路径处的值 |
| `/api/apps/{app}/config/{path}` | PUT | 设置点分路径处的值 |
| `/api/apps/{app}/config/{path}` | DELETE | 删除点分路径处的键 |
| `/api/apps/{app}/schema` | GET | 获取应用的 JSON Schema |
| `/api/apps/{app}/schema` | PUT | 替换或清除应用的 JSON Schema |
| `/api/apps/{app}/validate` | POST | 按应用的模式校验载荷 |

历史：

| 端点 | 方法 | 说明 |
|---|---|---|
| `/api/apps/{app}/history` | GET | 列出修订版本快照，最新在前 |
| `/api/apps/{app}/history/{revision}` | GET | 获取单个修订版本快照 |
| `/api/apps/{app}/rollback` | POST | 将某个快照恢复为新的修订版本 |

实时：

| 端点 | 协议 | 说明 |
|---|---|---|
| `/ws/{app}` | WebSocket | 订阅时接收当前配置，之后接收每次变更 |

该 WebSocket 仅用于接收：服务器在订阅时发送一条 `initial_config` 消息，之后每次变更发送一条 `update` 消息，每条消息都携带应用名称、修订版本和完整配置。写入始终通过 REST 进行，因此状态的归属永远不存在歧义。

## 远程客户端

远程客户端通过 REST API 读写，并通过 WebSocket 接收推送。构建完成后，基于远程后端的 `Nacho` 实例的行为与基于文件的实例完全一致——同样的 `get`、`set`、`on_change` 和模式相关 API。

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
    watch=True,               # 选择启用 WebSocket 更新
)

config = Nacho(storage=storage, events=True)

host = config.get("database.host")

@config.on_change("features.*")
def on_feature_change(path, new_value, **kwargs):
    print(f"feature flag updated: {path} = {new_value}")
```

建立连接绝不会修改服务器状态：错误的 API 密钥会在构建时立即报错，读取不存在的应用会抛出明确的错误（因此拼写错误不会悄悄返回空配置），而对不存在的应用的首次 `save()` 会创建它。

后端具备修订版本感知能力。每次加载和推送都会记录当时看到的服务器修订版本，`save()` 会将其一并发回——如果期间有其他客户端写入，`save()` 会抛出 `ConflictError`（携带服务器的期望/实际修订版本），而不是悄悄覆盖对方的写入。此时调用 `load()`，重新应用你的修改，然后再次保存即可：

```python
from nacho import ConflictError

try:
    config.save()
except ConflictError:
    config.load()          # 获取并发的变更
    config.set("my.key", value)
    config.save()
```

如果 WebSocket 连接断开，监听器会自动重连，连续重试次数有上限（`reconnect=0` 表示无限重试），并且每次成功连接后计数器都会重置。Keepalive ping 可以检测半开连接；永久性失败（密钥错误、应用被删除）会终止重试循环并输出一条明确的日志，而不是无限重试下去。过期或乱序的推送会被丢弃，因此本地快照绝不会回退。

不使用 SDK 时，CLI 可以完成同样的工作——参见[命令行界面](#命令行界面)。

## 事件系统

启用 `events=True` 后，Nacho 会在每次成功写入后派发变更通知，无论变更是本地发起的还是由服务器推送的。事件携带变更的路径、旧值、新值和事件类型。

```python
from nacho import Nacho, EventType

config = Nacho("config.yaml", events=True)

# "database" 下任意键发生变更时触发
@config.on_change("database.*")
def on_db_change(path, old_value, new_value, **kwargs):
    print(f"database key changed: {path}")

# 每次写操作触发一次（聚合事件）
@config.on_change("@global")
def on_any_change(**kwargs):
    print("config was modified")

# "cache" 下发生 CREATE 或 UPDATE 事件时触发
@config.on_event([EventType.CREATE, EventType.UPDATE], path_pattern="cache.*")
def on_cache_change(event_type, path, new_value, **kwargs):
    print(f"{event_type.name} {path} = {new_value}")

config.set("database.host", "new-host")  # on_db_change, on_any_change
config.set("cache.ttl", 600)             # on_cache_change (CREATE)
config.set("cache.ttl", 300)             # on_cache_change (UPDATE)
```

路径模式参考：

| 模式 | 触发条件 |
|---|---|
| `None`（默认） | 任意路径上的任意变更 |
| `"@global"` | 每次写操作触发一次（聚合） |
| `"*"` | 任意按键级别的事件（不含聚合事件） |
| `"database.*"` | 嵌套在 `database` 下的任意键 |

处理器可以是同步或异步的。存在正在运行的事件循环时，异步处理器会被调度到该事件循环上执行，否则通过 `asyncio.run()` 执行。在未启用 `events=True` 的实例上注册处理器会记录一条警告，因为该处理器永远不会被触发。

## 模式校验

Nacho 在每次写入时强制执行模式校验。无效的值会在变更应用之前抛出 `ValidationError`，因此配置永远不会处于无效状态。这一保证同样适用于本地写入和服务器接受的写入。

独立模式下使用需要 `pip install nacho-python[schema]`。

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

# 无效写入会立即抛出异常；配置不会被修改
try:
    config.set("database.port", "not-a-number")
except ValidationError as e:
    print(e.errors)                 # 违规信息字符串列表

# 检查当前配置而不执行写入
errors = config.validate()

# 按模式校验任意字典
errors = config.check({"database": {"host": "localhost", "port": 80}})
```

## 独立使用

Nacho 不强制要求服务器。将它指向一个本地文件，或直接交给它一个普通字典，它就是一个自包含的配置库，适用于脚本、测试和单进程应用。以下所有内容在以文件、字典或远程服务器作为后端时行为完全一致。

### 读取与写入

```python
from nacho import Nacho

config = Nacho({"database": {"host": "127.0.0.1", "port": 5432}})  # 内存模式
config = Nacho("config.yaml")                                      # 文件模式

# 带合理类型转换的类型化读取
host    = config.get("database.host")
port    = config.get_int("database.port")
debug   = config.get_bool("app.debug")
tags    = config.get_list("app.tags")
options = config.get_dict("app.options")

config.update({"logging": {"level": "DEBUG"}})   # 深度合并
config.replace({"database": {"host": "prod-db", "port": 5432}})
config.delete("legacy.setting")
config.load()                                    # 从存储重新加载
config.save()                                    # 持久化到存储
print(config.json())                             # 导出为 JSON 字符串
```

### 事务

将多次写入组合为一个原子操作。代码块正常退出时事务提交，出现任何异常时事务被丢弃。提交时会将事务中的操作重放到*当前*配置之上，因此事务打开期间落地的无关写入会被保留，而不是被丢弃：

```python
with config.transaction() as txn:
    txn.set("database.host", "new-host")
    txn.set("database.port", 5433)
# 处理器在此处携带聚合后的变更触发一次
config.save()
```

### 环境变量覆盖

传入 `env_prefix` 可在加载时将环境变量叠加到配置之上。变量名遵循 `{PREFIX}_{NESTED_KEY}` 格式，嵌套层级由分隔符（默认 `_`）分隔：

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

在无歧义的情况下会进行类型转换：`true`/`false`/`yes`/`no`/`on`/`off` 转换为布尔值，数字字符串转换为数字（`"1"` 是整数 1，而不是布尔值），形似 JSON 的字符串会按 JSON 解析。浮点数只有在文本能够往返转换（round-trip）时才会被解析，因此 `MYAPP_VERSION=3.10` 保持为字符串 `"3.10"`；给值加引号（`MYAPP_PORT='"8080"'`）会强制其保持为字符串。其余情况保持字符串不变。

键名本身含有下划线时，嵌套改用双写的分隔符表示：`MYAPP_DB__MAX_CONNECTIONS` 设置的是 `db.max_connections`。环境变量覆盖仅是运行时的叠加层：`save()` 持久化的是已存储的配置，而不是叠加后的视图。

## 命令行界面

```bash
nacho --help
nacho --version
```

每个远程命令都接受 `--remote <url>`、`--app-name <name>`（默认 `default`）和 `--api-key <key>`。错误写入 stderr，退出码可区分不同的失败类别，因此脚本无需解析错误消息即可分支处理：

| 退出码 | 含义 |
|---|---|
| 0 | 成功 |
| 1 | 一般错误（模式违规、传输失败、缺少 extras） |
| 2 | 用法错误（错误的标志或参数） |
| 3 | 未找到（应用、键、路径或历史修订版本不存在） |
| 4 | 修订版本冲突（并发写入胜出） |
| 5 | 认证失败（API 密钥错误或缺失、只读服务器） |

输出以 `--format {json,yaml,toml}`（默认 `json`）渲染，因此每条命令的输出都可被机器解析；`nacho get missing.key` 会以退出码 3 结束并向 stderr 写入消息，而不是打印 `None`。

### 值操作

```bash
# 本地或远程读取某个键，或读取整个配置
nacho get database.host --config config.yaml
nacho get --format json --remote http://config-server:8000 --app-name my-service

# 在输出中包含当前修订版本
nacho get --show-revision --format json --remote http://config-server:8000

# 写入与删除，可选带防冲突的修订版本检查
nacho set cache.ttl 600 --remote http://config-server:8000 --revision 3
nacho delete legacy.setting --remote http://config-server:8000 --revision 4

# 当自动检测可能猜错时，强制指定类型
nacho set app.version 3.10 --type str --remote http://config-server:8000
nacho set app.flags '{"beta": true}' --type json --remote http://config-server:8000

# 本地文件的等效操作
nacho set database.port 5432 --config config.yaml
nacho delete legacy.setting --config config.yaml
```

### 应用

```bash
nacho apps list --remote http://config-server:8000
nacho apps create my-service \
  --remote http://config-server:8000 \
  --description "Core service" \
  --config config.yaml \
  --schema schema.json
nacho apps show --remote http://config-server:8000 --app-name my-service
nacho apps rename my-service-v2 --remote http://config-server:8000 --app-name my-service
nacho apps describe "Payments service" --remote http://config-server:8000 --app-name my-service
nacho apps delete my-service --remote http://config-server:8000
```

### 模式与校验

```bash
# 打印或替换服务器强制执行的模式
nacho schema get --remote http://config-server:8000 --app-name my-service
nacho schema push schema.json --remote http://config-server:8000 --app-name my-service

# 用服务器上存储的模式校验本地文件
nacho validate --config config.yaml --remote http://config-server:8000 --app-name my-service

# 改用本地模式文件进行校验
nacho validate --config config.yaml --schema schema.json
```

### 历史与回滚

```bash
nacho history list --remote http://config-server:8000 --app-name my-service
nacho history show 41 --remote http://config-server:8000 --app-name my-service

# 将修订版本 41 恢复为新的修订版本；--revision-check 使其具备防冲突能力
nacho rollback 41 --remote http://config-server:8000 --app-name my-service --revision-check 42
```

### 实时更新

```bash
# 打印当前配置，之后每次变更输出一行 JSON（按 Ctrl+C 停止）
nacho watch --remote http://config-server:8000 --app-name my-service
```

### 脚手架

```bash
# 从内置模板创建配置文件
nacho init config.yaml --template default
# 模板：empty, default, web-app, api-service, microservice
```

## Docker

Nacho 提供一个多阶段 `Dockerfile`，构建出基于 Alpine 的小体积镜像，以非 root 用户运行配置服务器，并内置针对 `/health` 的容器健康检查。已发布的镜像可从 Docker Hub 和 GHCR 获取：

```bash
docker pull k3scat/nacho:latest
docker pull ghcr.io/nya-foundation/nacho:latest

# 运行服务器（UI 位于 http://localhost:8000/ui）
docker run -p 8000:8000 k3scat/nacho:latest

# 启用认证运行
docker run -p 8000:8000 k3scat/nacho:latest \
  server --host 0.0.0.0 --config config.yaml --api-key "secure-key"

# 为默认应用挂载你自己的配置
docker run -p 8000:8000 \
  -v "$(pwd)/config.yaml:/app/config.yaml" k3scat/nacho:latest
```

或使用 Compose：

```bash
docker compose up --build
```

镜像的入口点是 `nacho`；默认命令为 `server --host 0.0.0.0 --config config.yaml`。追加任意 `nacho server` 参数即可覆盖默认值。容器暴露端口 `8000`。

## 运维说明

- 点分路径有意保持简单。键名中的字面量点号和数字字符串键会产生歧义；请优先使用嵌套对象键。
- 内置的 API 密钥认证适用于本地、私有和单租户部署。共享的生产环境部署应在服务前端补充范围化令牌、审计日志和速率限制。
- 服务器状态基于文件且为单进程。修订版本计数器以内存中的值为权威，因此每个数据目录只应运行一个服务器进程；如需多进程或高可用运行，存储抽象层就是实现更强后端的边界。
- 服务器运行期间手工编辑 `--config` 文件不会被检测到；服务器的下一次写入会覆盖它。请通过 API、CLI 或 UI 进行修改。

## 开发

```bash
git clone https://github.com/nya-foundation/nacho.git
cd nacho
uv sync --all-extras

uv run pytest                                  # 快速套件（单元 + 冒烟测试），95% 覆盖率门槛
uv run pytest -m "integration or e2e" --no-cov # 需要在线服务器的套件
uv run pytest -m docker --no-cov               # 构建并测试 Docker 镜像
uv run playwright install chromium             # 一次性下载浏览器
uv run pytest -m ui --no-cov                   # 基于浏览器的 Web UI 套件

uvx ruff format . && uvx ruff check .          # 格式化与 lint（CI 强制执行）
```

分支模型、代码风格和发布流程参见 [CONTRIBUTING.md](CONTRIBUTING.md)。

## 社区

在 [GitHub](https://github.com/nya-foundation/nacho/issues) 上提交 issue，或加入 [Nya Foundation Discord](https://discord.gg/jXAxVPSs7K)。

## 许可证

MIT——详情参见 [LICENSE](LICENSE)。
