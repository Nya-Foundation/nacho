# Nacho

<div align="center">

<pre>
 _   _     _      ____  _   _   ___
| \ | |   / \    / ___|| | | | / _ \
|  \| |  / _ \  | |    | |_| || | | |
| |\  | / ___ \ | |___ |  _  || |_| |
|_| \_|/_/   \_\ \____||_| |_| \___/
</pre>

  <h3>Python 向けの軽量・セルフホスト型な動的構成サービス。</h3>

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

> **注意:** 本プロジェクトは活発に開発中です。想定外の挙動に遭遇した場合は、GitHub で issue を作成してください。

## Nacho とは？

Nacho は Python 向けの軽量・セルフホスト型な構成**サービス**です。

Nacho サーバーを起動し、数行のコードでサービスをそこに接続すれば、構成変更を
プッシュするだけで、その変更が各サービスへ**リアルタイム**に届きます——再デプロイも
再起動も不要です。あらゆる変更はストレージへ保存される前に JSON Schema で検証され、
組み込みの Web UI でそのすべてを管理できます。サーバーが不要な場合は、同じ
ライブラリをスタンドアロンモードでローカルファイルに対して直接使うこともできます。

| 機能 | 説明 |
|---|---|
| **集中型の構成サーバー** | 1 つの Nacho サーバーを起動し、すべてのサービスの構成を REST API・CLI・Web UI から一元管理。 |
| **リアルタイム更新** | クライアントは WebSocket で購読し、変更が起きた瞬間にそれを受け取る——ポーリングも再起動も不要。 |
| **スキーマファーストな検証** | すべての書き込みを JSON Schema に対して検査；不正なデータはストレージへ到達する前に拒否される。 |
| **そのまま使える Python クライアント** | `RemoteStorageBackend` はリモートアプリにローカルファイルと同一の API を与える——ストレージを差し替えるだけで、他は何も変えなくてよい。 |
| **組み込みの管理 UI** | サーバー自身がホストする単一ファイルの Web UI から、JSON・YAML・TOML でアプリを作成し、構成やスキーマを編集。 |
| **マルチフォーマット** | JSON・YAML・TOML をあらゆる場所で：API ペイロード、保存ファイル、UI エディタ。 |
| **スタンドアロンモード** | サーバー不要——Nacho をローカルファイルやインメモリ辞書に向け、ただの構成ライブラリとして利用。 |

## 前提条件

- Python 3.9 以上
- Docker（任意、コンテナ化デプロイ用）

## インストール

Nacho はコア依存関係を小さく保つため、任意の extras を使用します。

```bash
# 構成サーバーを実行
pip install nacho-python[server]

# サービスをサーバーに接続（リモートクライアント）
pip install nacho-python[remote]

# コア——スタンドアロンのローカルファイル管理のみ
pip install nacho-python

# JSON Schema 検証付き
pip install nacho-python[schema]

# すべての機能
pip install nacho-python[all]

# 開発とテスト
pip install nacho-python[dev]
```

| Extra | 依存関係 | 用途 |
|---|---|---|
| `server` | fastapi, uvicorn, websockets | REST API と WebSocket 構成サーバー |
| `remote` | requests, websocket-client | リモート構成クライアント |
| `schema` | jsonschema, rfc3987 | 書き込み時の JSON Schema 検証 |
| *(なし)* | pyyaml, tomli-w | スタンドアロンのローカルファイル読み書き（YAML、JSON、TOML） |
| `all` | 上記すべて | 完全インストール |
| `dev` | pytest, httpx, coverage | 開発とテスト |

## クイックスタート

**1. Nacho サーバーを起動する**

```bash
pip install nacho-python[server]
nacho server --config config.yaml --api-key "secure-key"
```

サーバーは `http://localhost:8000` で稼働します——REST API、WebSocket プッシュ、
そして `/ui` の組み込み管理 UI を提供します。

**2. サービスをそこに接続する**

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
        watch=True,           # WebSocket でリアルタイム更新を受け取る
    ),
    events=True,
)

# ローカルの辞書とまったく同じように構成を読み取る
port = config.get_int("server.port", default=8000)

# 誰かがサーバー上でそれを変更した瞬間に反応する
@config.on_change("features.*")
def on_flag_change(path, new_value, **kwargs):
    print(f"{path} is now {new_value}")
```

UI・CLI・API のどこから値を変更しても——接続中のすべてのクライアントがただちにそれを受け取ります。

> **サーバーは不要ですか？** Nacho はスタンドアロンのファイルベースのライブラリとしても動作します：
> `config = Nacho("config.yaml")`。[スタンドアロンのファイルベース利用](#スタンドアロンのファイルベース利用)を参照してください。

## Nacho サーバーの実行

`NachoOrchestrator` は 1 つ以上の `Nacho` インスタンスを FastAPI アプリケーションでラップします。
このサーバーは API ファーストです。インタラクティブな OpenAPI ドキュメントには `/docs`、リアルタイムの構成更新には `/ws/{app}`、組み込みの管理 UI には `/ui` を使用します。

`pip install nacho-python[server]` が必要です。

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

サーバーを起動する最も簡単な方法は CLI です——[コマンドラインインターフェース](#コマンドラインインターフェース)を参照してください。

### 管理 UI

Nacho はアプリ、構成、スキーマを管理するための組み込み Web UI を同梱しています。
サーバーの起動後、`/ui` で利用できます——別プロセスやビルド手順は不要で、ページは FastAPI が直接配信する単一ファイルです。

UI は以下をサポートします:

- **アプリ管理** —— アプリの一覧表示、作成、リネーム、説明の設定、削除。
- **構成編集** —— JSON、YAML、TOML 対応のコードエディタ。シンタックスハイライト、ワンクリックのフォーマット切り替え、オンデマンド検証、リビジョン対応の保存（古い書き込みは新しいデータを上書きせず、競合として表示される）を備える。
- **スキーマ編集** —— アプリ作成後に JSON Schema を JSON、YAML、TOML で表示・編集・クリア可能。現在の構成は新しいスキーマに対して再検査される。
- **リアルタイム更新** —— WebSocket でプッシュされた変更がリアルタイムに反映される。

サーバーが `--api-key` 付きで起動された場合、UI は初回読み込み時にキーの入力を求め、ブラウザに記憶します。`/ui` ページ自体はサインイン画面を読み込めるよう公開されていますが、その背後のすべての API 呼び出しは認証された状態を保ちます。

### 既存の FastAPI アプリケーションへのマウント

```python
from fastapi import FastAPI
from nacho import Nacho, NachoOrchestrator

app = FastAPI(title="My Application")

orchestrator = NachoOrchestrator(
    apps={"config": Nacho("config.yaml", events=True)},
    api_key="secure-key",
)

# 構成 API は /config 配下で利用可能
app.mount("/config", orchestrator.app)
```

	サーバーの起動後、インタラクティブな API ドキュメントは `/docs`（Swagger）と `/redoc` で利用できます。

### API の書き込み形式とリビジョン

API は構成およびスキーマのペイロードとしてネイティブな JSON オブジェクトを受け付けます:

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

従来のエンコード済み文字列形式も、JSON、YAML、TOML で引き続きサポートされます:

```json
{"data": "{\"feature\": true}", "format": "json"}
```

構成全体の読み取りは `ETag` と `X-Nacho-Revision` を返します。書き込みには `If-Match: "<revision>"` ヘッダーまたは JSON の `revision` フィールドのいずれかを含められます。サーバーが先に進んでいる場合、書き込みは `409 Conflict` を返し、構成は変更されません。

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

### API リファレンス

**システム**

| エンドポイント | メソッド | 説明 |
|---|---|---|
| `/health` | GET | ヘルスチェックとインスタンス概要 |
| `/ui` | GET | 組み込みの Web 管理 UI |
| `/api/convert` | POST | ペイロードを JSON、YAML、TOML 間で変換 |

**アプリ管理**

| エンドポイント | メソッド | 説明 |
|---|---|---|
| `/api/apps` | GET | すべてのアプリを一覧表示 |
| `/api/apps` | POST | 新しいアプリを作成 |
| `/api/apps/{app}` | GET | アプリ情報を取得 |
| `/api/apps/{app}` | PUT | アプリの構成とメタデータを置き換え |
| `/api/apps/{app}` | DELETE | アプリを削除 |
| `/api/apps/{app}/metadata` | PATCH | アプリ名または説明を更新 |

**構成**

| エンドポイント | メソッド | 説明 |
|---|---|---|
| `/api/apps/{app}/config` | GET | 構成全体を取得 |
| `/api/apps/{app}/config` | PUT | 構成全体を置き換え |
| `/api/apps/{app}/config/{path}` | GET | 指定パスの値を取得 |
| `/api/apps/{app}/config/{path}` | PUT | 指定パスに値を設定 |
| `/api/apps/{app}/config/{path}` | DELETE | 指定パスのキーを削除 |
| `/api/apps/{app}/schema` | GET | アプリの JSON Schema を取得 |
| `/api/apps/{app}/schema` | PUT | アプリの JSON Schema を置き換えまたはクリア |
| `/api/apps/{app}/validate` | POST | 構成ペイロードをスキーマに対して検証 |

**リアルタイム**

| エンドポイント | プロトコル | 説明 |
|---|---|---|
| `/ws/{app}` | WebSocket | 構成変更イベントを受信 |

## リモートクライアント

リモートクライアントは Nacho サーバーに接続し、任意で WebSocket 経由のリアルタイム更新を受け取ります。クライアントは REST API を通じて書き込み、サーバーは WebSocket で変更をプッシュバックします。いったん構築されると、リモートバックエンドの `Nacho` インスタンスは、ファイルベースのものと**まったく同じ**ように振る舞います——同じ `get`、`set`、`on_change`、スキーマ API です。

`pip install nacho-python[remote]` が必要です。

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
    watch=True,  # WebSocket 更新をオプトインで有効化
)

config = Nacho(storage=storage, events=True)

# API はファイルベースの使い方と同一
host = config.get("database.host")

# ハンドラはサーバーからプッシュされた変更で発火する
@config.on_change("features.*")
def on_feature_change(path, new_value, **kwargs):
    print(f"feature flag updated: {path} = {new_value}")
```

SDK をまったく使わず、[コマンドライン](#リモート)から直接サーバーにアクセスすることもできます:

```bash
nacho get database.host --remote http://config-server:8000 --app-name my-service
```

## イベントシステム

イベントシステムは、書き込みが成功するたびに変更通知をディスパッチします——その変更がローカルで行われたものでも、**Nacho サーバーからプッシュされたもの**でも同様です。イベントは変更されたパス、旧値、新値、イベント種別を保持します。

```python
from nacho import Nacho, EventType

config = Nacho("config.yaml", events=True)

# "database" 配下の任意のキーの変更で発火
@config.on_change("database.*")
def on_db_change(path, old_value, new_value, **kwargs):
    print(f"database key changed: {path}")

# どのキーが変更されたかに関わらず、書き込み操作ごとに 1 回発火（集約イベント）
@config.on_change("@global")
def on_any_change(**kwargs):
    print("config was modified")

# "cache" 配下の CREATE または UPDATE イベントで発火
@config.on_event([EventType.CREATE, EventType.UPDATE], path_pattern="cache.*")
def on_cache_change(event_type, path, new_value, **kwargs):
    print(f"{event_type.name} {path} = {new_value}")

config.set("database.host", "new-host")  # on_db_change、on_any_change を発火
config.set("cache.ttl", 600)             # on_cache_change を発火（CREATE）
config.set("cache.ttl", 300)             # on_cache_change を発火（UPDATE）
```

**パスパターン一覧:**

| パターン | 発火条件 |
|---|---|
| `None`（デフォルト） | 任意のパスにおける任意の変更 |
| `"@global"` | 書き込み操作ごとに 1 回（集約） |
| `"*"` | 任意のキー単位イベント（集約ではない） |
| `"database.*"` | `database` 配下にネストされた任意のキー |

ハンドラは同期・非同期のいずれでも構いません。非同期ハンドラは、実行中のイベントループがあればそこにスケジュールされ、なければ `asyncio.run()` で実行されます。

## スキーマ検証

Nacho はすべての書き込みでスキーマを強制します。不正な値は変更が適用される前にただちに `ValidationError` を送出します——構成が不正な状態のまま残ることはありません。これはローカルの書き込みと、サーバーが受け入れるデータの両方に適用されます。

`pip install nacho-python[schema]` が必要です。

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

# 不正な書き込みはただちに送出される——構成は変更されない
try:
    config.set("database.port", "not-a-number")
except ValidationError as e:
    print(e.errors)  # 違反内容の文字列リスト

# 書き込まずに、現在の構成をスキーマに対して検査
errors = config.validate()
if errors:
    print("Current config has violations:", errors)

# 任意の辞書をスキーマに対して検証
errors = config.check({"database": {"host": "localhost", "port": 80}})
print(errors)  # ["port must be >= 1024"]
```

## スタンドアロンのファイルベース利用

Nacho はサーバーを必須としません。ローカルファイル（またはそのままの辞書）を渡せば、自己完結した構成ライブラリとして動作します——スクリプト、テスト、シングルプロセスのアプリに最適です。以下の内容は、Nacho がファイル・辞書・リモートサーバーのいずれに支えられていても、同じように機能します。

### 構成管理

Nacho はファイルパス、辞書、または明示的なストレージバックエンドを受け付けます。

```python
from nacho import Nacho

# 初期データ付きのインメモリ構成
config = Nacho({"database": {"host": "127.0.0.1", "port": 5432}})

# ファイルベースの構成
config = Nacho("config.yaml")

# 型変換付きの読み取り
host    = config.get("database.host")            # str
port    = config.get_int("database.port")        # int
debug   = config.get_bool("app.debug")           # bool
tags    = config.get_list("app.tags")            # list
options = config.get_dict("app.options")         # dict

# 追加のキーをディープマージ（既存のキーは削除しない）
config.update({"logging": {"level": "DEBUG"}})

# 構成全体を置き換える
config.replace({"database": {"host": "prod-db", "port": 5432}})

# キーを削除する
config.delete("legacy.setting")

# ストレージから再読み込みし、環境変数オーバーライドを再適用
config.reload()

# 現在の構成を JSON 文字列としてエクスポート
print(config.json())
```

### アトミックなトランザクション

複数の書き込みを 1 つのアトミックな操作にまとめます。ブロックが正常に終了するとトランザクションはコミットされ、例外が発生すると破棄されます。

```python
with config.transaction() as txn:
    txn.set("database.host", "new-host")
    txn.set("database.port", 5433)
# ハンドラはここで集約された変更とともに 1 回発火する
config.save()
```

### 環境変数オーバーライド

`env_prefix` を渡すと、読み込み時に環境変数を構成へ重ね合わせます。変数名は `{PREFIX}_{NESTED_KEY}` のパターンに従い、ネストの各階層は区切り文字（デフォルト: `_`）で区切られます。

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

環境変数の値は可能な場合 bool、int、float、JSON オブジェクトへ変換され、それ以外は文字列にフォールバックします。環境変数オーバーライドは実行時のみの重ね合わせです。`save()` は環境変数を重ねた実効値ではなく、保存されている構成を永続化します。

## コマンドラインインターフェース

```bash
nacho --help
nacho --version
```

### サーバー

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

### リモート

```bash
nacho get database.host \
  --remote http://config-server:8000 \
  --app-name my-service \
  --api-key "secure-key"

# 構成全体を読み取り、現在のリモートリビジョンも含める
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

### ローカル構成

```bash
# テンプレートから新しい構成を作成
nacho init config.yaml --template default

# 利用可能なテンプレート: empty、default、web-app、api-service、microservice

# 読み取り
nacho get database.host --config config.yaml
nacho get --config config.yaml --format json

# 書き込み
nacho set database.port 5432 --config config.yaml

# 削除
nacho delete legacy.setting --config config.yaml

# スキーマに対して検証
nacho validate --config config.yaml --schema schema.json
```

## Docker

Nacho は、構成サーバーを実行する小さな Alpine ベースのイメージをビルドする、マルチステージの `Dockerfile` を同梱しています。公開済みイメージは Docker Hub と GHCR から取得できます:

```bash
# Docker Hub から取得
docker pull k3scat/nacho:latest

# GitHub Container Registry から取得
docker pull ghcr.io/nya-foundation/nacho:latest

# イメージをビルド
docker build -t nacho .

# サーバーを実行（UI は http://localhost:8000/ui）
docker run -p 8000:8000 k3scat/nacho:latest

# 認証を有効にして実行
docker run -p 8000:8000 ghcr.io/nya-foundation/nacho:latest \
  server --config config.yaml --api-key "secure-key"

# デフォルトアプリ用に独自の構成をマウント
docker run -p 8000:8000 \
  -v "$(pwd)/config.yaml:/app/config.yaml" k3scat/nacho:latest
```

または `docker-compose` を使用:

```bash
docker compose up --build
```

イメージのエントリポイントは `nacho` で、デフォルトコマンドは `server --config config.yaml` です。任意の `nacho server` フラグ（`--api-key`、`--read-only`、`--event` など）を追加すればデフォルトを上書きできます。コンテナはポート `8000` を公開し、非 root ユーザーで実行されます。

## 現在の制限

- ドット記法のパスは意図的にシンプルです。キー名中のリテラルなドットや数値文字列キーは曖昧になるため、当面はネストされたオブジェクトキーを推奨します。
- 組み込みの API キー認証は、ローカル・プライベート・シングルテナントのデプロイに適しています。共有される本番デプロイでは、サービスの前段にスコープ付きトークン、監査ログ、レート制限を追加すべきです。
- ファイルベースのサーバー状態は、開発や小規模なシングルプロセスのデプロイに最適です。マルチプロセスや高可用性の運用が必要な場合は、ストレージ抽象化を境界として、より強力で永続的なバックエンドを接続してください。

## コミュニティ

サポートが必要ですか？ [GitHub](https://github.com/nya-foundation/nacho/issues) で issue を作成するか、[Nya Foundation Discord](https://discord.gg/jXAxVPSs7K) に参加してください。

## ライセンス

MIT —— 詳細は [LICENSE](LICENSE) を参照してください。
