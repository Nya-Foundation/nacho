# Nacho

<div align="center">

<pre>
 _   _     _      ____  _   _   ___
| \ | |   / \    / ___|| | | | / _ \
|  \| |  / _ \  | |    | |_| || | | |
| |\  | / ___ \ | |___ |  _  || |_| |
|_| \_|/_/   \_\ \____||_| |_| \___/
</pre>

  <h3>Python 向けの軽量なセルフホスト型動的設定サービス</h3>

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

## 概要

Nacho は Python 向けのセルフホスト型設定サービスです。Nacho サーバーを 1 つ起動し、
数行のコードでサービスを接続すれば、設定変更をライブで配信できます —
再デプロイも再起動もポーリングも不要です。

すべての書き込みは保存前に JSON Schema で検証され、すべてのリビジョンは
ロールバック履歴として保持され、組み込みのシングルファイル Web UI で
そのすべてを管理できます。サーバーが不要な場合は、同じライブラリを
ローカルファイルやインメモリの dict に対してスタンドアロンで使用できます。

| 機能 | 説明 |
|---|---|
| 集中設定管理 | 1 つのサーバーが REST API、CLI、Web UI を通じてすべてのサービスの設定を管理します。 |
| ライブ更新 | クライアントは WebSocket で購読し、変更が発生した瞬間に受け取ります。 |
| スキーマファーストの検証 | 書き込みは JSON Schema に対してチェックされ、ストレージに到達する前に拒否されます。 |
| 履歴とロールバック | すべてのリビジョンがスナップショットされ、任意のリビジョンを確認・復元できます。 |
| ドロップインの Python クライアント | `RemoteStorageBackend` により、リモートアプリケーションでもローカルファイルと同じ API を利用できます。 |
| 楽観的並行性制御 | リビジョンチェック付きの書き込みにより、更新の喪失を明示的な `409 Conflict` レスポンスに変換します。 |
| マルチフォーマット | JSON、YAML、TOML は API ペイロード、保存ファイル、UI エディタの間で相互に交換可能です。 |
| スタンドアロンモード | サーバーなしで、Nacho を通常の設定ライブラリとして使用できます。 |

## インストール

Nacho はオプションの extras によってコア依存関係を小さく保っています:

```bash
pip install nacho-python[server]    # 設定サーバーを起動する
pip install nacho-python[remote]    # サービスをサーバーに接続する
pip install nacho-python[schema]    # スタンドアロン利用向けの JSON Schema 検証
pip install nacho-python            # コア: スタンドアロンのローカルファイル管理
```

Python 3.9 以降が必要です。コンテナデプロイ向けに Docker イメージも提供しています
（[Docker](#docker) を参照）。

## クイックスタート

サーバーを起動します:

```bash
pip install nacho-python[server]
nacho server --config config.yaml --api-key "secure-key"
```

これでサーバーが `http://127.0.0.1:8000` で稼働し、REST API、WebSocket プッシュ、
`/docs` のインタラクティブな API ドキュメント、`/ui` の管理 UI が利用できます。

サービスを接続します:

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
        watch=True,            # WebSocket 経由でライブ更新を受信する
    ),
    events=True,
)

# ローカルの dict とまったく同じように設定を読み取る
port = config.get_int("server.port", default=8000)

# サーバー上で誰かが値を変更した瞬間に反応する
@config.on_change("features.*")
def on_flag_change(path, new_value, **kwargs):
    print(f"{path} is now {new_value}")
```

UI、CLI、または API から値を変更すると、接続中のすべてのクライアントに
即座に反映されます。

サーバーが不要な場合は、Nacho はスタンドアロンのファイルベースのライブラリとしても動作します:
`config = Nacho("config.yaml")`。詳細は
[スタンドアロンでの利用](#スタンドアロンでの利用) を参照してください。

## サーバーの実行

サーバーの起動には通常 CLI を使用します:

```bash
nacho server \
  --config config.yaml \
  --schema schema.json \
  --port 8000 \
  --api-key "secure-key" \
  --data-dir ".nacho/apps" \
  --history-limit 50
```

サーバーはデフォルトで `127.0.0.1` にバインドします。他のマシンからの接続を
受け付けるには `--host 0.0.0.0` を指定します。`--api-key` なしでサーバーを
公開すると CLI が警告を出力します。認証のないサーバーは、到達可能な誰にでも
完全な書き込みアクセスを与えてしまうためです。

| フラグ | デフォルト | 説明 |
|---|---|---|
| `--host` | `127.0.0.1` | バインドアドレス（`0.0.0.0` ですべてのインターフェースで待ち受け） |
| `--port` | `8000` | バインドポート |
| `--config`, `-c` | なし | アプリとして提供する設定ファイル |
| `--schema` | なし | `--config` に対して適用する JSON Schema |
| `--app-name` | `default` | `--config` ファイルのアプリ名 |
| `--data-dir` | なし | API で作成されたアプリの状態と履歴を保存するディレクトリ |
| `--api-key` | なし | ベアラートークン認証を有効化 |
| `--history-limit` | `50` | アプリごとに保持するリビジョンスナップショット数（`0` で履歴を無効化） |
| `--read-only` | オフ | すべての書き込みを拒否 |
| `--reload` | オフ | 開発用の自動リロード |

### 既存アプリケーションへの組み込み

`NachoOrchestrator` は 1 つ以上の `Nacho` インスタンスを FastAPI
アプリケーションとしてラップするため、サーバーをコードで構築したり、
既存アプリにマウントしたりすることもできます:

```python
from fastapi import FastAPI
from nacho import Nacho, NachoOrchestrator

app = FastAPI(title="My Application")

orchestrator = NachoOrchestrator(
    apps={"config": Nacho("config.yaml", events=True)},
    api_key="secure-key",
    cors_origins=["https://admin.example.com"],
)

app.mount("/config", orchestrator.app)   # /config 配下に設定 API をマウント
```

マウントしない場合は、`orchestrator.run(host="127.0.0.1", port=8000)` で
直接実行できます。

### 管理 UI

サーバーは `/ui` でシングルファイルの Web UI をホストします — 別プロセスも
ビルドステップも不要です。以下の機能を提供します:

- アプリ管理: アプリの一覧表示、作成、リネーム、説明の設定、削除。
- 設定編集: JSON、YAML、TOML に対応したコードエディタ。シンタックス
  ハイライト、フォーマット切り替え、オンデマンド検証に加え、リビジョンを
  考慮した保存により、より新しいデータを上書きするのではなく競合として
  表示します。
- スキーマ編集: アプリの JSON Schema の表示、編集、クリア。新しいスキーマを
  受け入れる前に、現在の設定がそのスキーマに対して再チェックされます。
- 履歴: リビジョンスナップショットを閲覧し、ワンクリックで任意のスナップ
  ショットを復元できます。
- ライブ更新: WebSocket でプッシュされた変更はリアルタイムに反映され、
  リモートの変更が届いた際も未保存のローカル編集は保持されます。

サーバーが `--api-key` 付きで起動している場合、UI は初回ロード時にキーの
入力を求めます。サインイン画面を表示できるように `/ui` ページ自体は公開
されていますが、その背後のすべての API 呼び出しには認証が必要です。

### 認証

`--api-key`（または `NachoOrchestrator` への `api_key=`）を指定すると、
API 全体でベアラー認証が有効になります。クライアントはキーを
`Authorization: Bearer <key>` ヘッダーとして送信するか、UI が自身の
WebSocket ハンドシェイク用に設定する Cookie を通じて送信します。キーが
欠落または誤っているリクエストには `401 Unauthorized` が返されます。
キーの比較はタイミングセーフです。

`/`、`/health`、`/ui`、`/docs`、`/redoc`、`/openapi.json` は公開のままです:
秘密にすべきは API の存在ではなく、その背後にあるデータだからです。

クロスオリジンのブラウザアクセスは、`cors_origins=[...]` でオプトイン
しない限り無効です — バンドルされた UI は同一オリジンで動作し、SDK や
CLI はブラウザではないため、ドライブバイの Web ページがデフォルト設定の
サーバーに到達することはできません。

## REST API

サーバー起動後、`/docs`（Swagger UI）と `/redoc` でインタラクティブな
ドキュメントを利用できます。

### ペイロードのフォーマット

設定とスキーマのペイロードはネイティブの JSON オブジェクトです:

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

ペイロードは、サポートされている任意のフォーマットのエンコード済み文字列
として送信することもできます。CLI と UI はこの方法で YAML と TOML を送信
しています:

```json
{"data": "database:\n  host: localhost\n", "format": "yaml"}
```

### リビジョンと楽観的並行性制御

各アプリは単調増加するリビジョンを持ち、書き込みが成功するたびに
インクリメントされます。`/config` の読み取り（全体・パス単位のいずれも）は、
現在のリビジョンを `ETag` および `X-Nacho-Revision` レスポンスヘッダーで
返します。書き込みには、クライアントが最後に確認したリビジョンを示す
`revision` フィールドを含めることができます。サーバー側が先に進んでいた
場合、書き込みは `409 Conflict` で失敗し、保存済みの設定は変更されません:

```bash
curl -X PUT http://127.0.0.1:8000/api/apps/my-service/config/cache.ttl \
  -H "Authorization: Bearer secure-key" \
  -H "Content-Type: application/json" \
  -d '{"value": 600, "revision": 3}'
```

`revision` を省略すると、無条件の書き込みになります。

### 履歴とロールバック

サーバーはすべてのリビジョン（設定、スキーマ、メタデータ）をアプリごとの
リングバッファにスナップショットします — データディレクトリが設定されて
いる場合は `data_dir/history/` 配下のディスク上に、それ以外の場合は
メモリ上に保存されます。保持数は `--history-limit` で制御します。

ロールバックはロールフォワード方式です: リビジョン 41 を復元しても履歴が
書き換えられることはなく、スナップショット 41 と同じ内容を持つ新しい
リビジョンが作成されます。リビジョンカウンターは単調増加を保ち、ライブ
クライアントには通常の書き込みと同様に通知され、ロールバック自体も
ロールバックできます。スナップショットは設定とスキーマを同時に復元する
ため、結果は常に自己整合的です。

```bash
curl http://127.0.0.1:8000/api/apps/my-service/history
curl http://127.0.0.1:8000/api/apps/my-service/history/41
curl -X POST http://127.0.0.1:8000/api/apps/my-service/rollback \
  -H "Content-Type: application/json" \
  -d '{"revision": 41, "expected_revision": 42}'
```

### エンドポイントリファレンス

システム:

| エンドポイント | メソッド | 説明 |
|---|---|---|
| `/health` | GET | ヘルスチェックとインスタンス概要 |
| `/ui` | GET | 組み込みの Web 管理 UI |
| `/docs`, `/redoc` | GET | インタラクティブな API ドキュメント |
| `/api/convert` | POST | ペイロードを JSON、YAML、TOML の間で変換 |

アプリ管理:

| エンドポイント | メソッド | 説明 |
|---|---|---|
| `/api/apps` | GET | すべてのアプリを一覧表示 |
| `/api/apps` | POST | アプリを作成 |
| `/api/apps/{app}` | GET | アプリ情報を取得 |
| `/api/apps/{app}` | PUT | アプリの設定、スキーマ、説明を置き換え |
| `/api/apps/{app}` | DELETE | アプリを削除 |
| `/api/apps/{app}/metadata` | PATCH | アプリのリネームまたは説明の変更 |

設定とスキーマ:

| エンドポイント | メソッド | 説明 |
|---|---|---|
| `/api/apps/{app}/config` | GET | 設定全体を取得 |
| `/api/apps/{app}/config` | PUT | 設定全体を置き換え |
| `/api/apps/{app}/config/{path}` | GET | ドット区切りパスの値を取得 |
| `/api/apps/{app}/config/{path}` | PUT | ドット区切りパスの値を設定 |
| `/api/apps/{app}/config/{path}` | DELETE | ドット区切りパスのキーを削除 |
| `/api/apps/{app}/schema` | GET | アプリの JSON Schema を取得 |
| `/api/apps/{app}/schema` | PUT | アプリの JSON Schema を置き換えまたはクリア |
| `/api/apps/{app}/validate` | POST | アプリのスキーマに対してペイロードを検証 |

履歴:

| エンドポイント | メソッド | 説明 |
|---|---|---|
| `/api/apps/{app}/history` | GET | リビジョンスナップショットを新しい順に一覧表示 |
| `/api/apps/{app}/history/{revision}` | GET | 1 つのリビジョンスナップショットを取得 |
| `/api/apps/{app}/rollback` | POST | スナップショットを新しいリビジョンとして復元 |

リアルタイム:

| エンドポイント | プロトコル | 説明 |
|---|---|---|
| `/ws/{app}` | WebSocket | 購読時に現在の設定を受信し、以降はすべての変更を受信 |

WebSocket は受信専用です: サーバーは購読時に `initial_config` メッセージを
送信し、その後は変更ごとに `update` メッセージを送信します。各メッセージは
アプリ名、リビジョン、設定全体を含みます。書き込みは常に REST を経由する
ため、状態の所有者について曖昧さが生じることはありません。

## リモートクライアント

リモートクライアントは REST API を通じて読み書きし、WebSocket でプッシュを
受信します。一度構築すれば、リモートバックエンドの `Nacho` インスタンスは
ファイルバックエンドのものとまったく同じように振る舞います — `get`、`set`、
`on_change`、スキーマ関連の API はすべて同一です。

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
    watch=True,               # WebSocket 更新をオプトインする
)

config = Nacho(storage=storage, events=True)

host = config.get("database.host")

@config.on_change("features.*")
def on_feature_change(path, new_value, **kwargs):
    print(f"feature flag updated: {path} = {new_value}")
```

接続がサーバーの状態を変更することはありません: 誤った API キーは構築時に
明確に失敗し、存在しないアプリの読み取りは明確なエラーを送出し（タイプミス
が空の設定を静かに返すことはありません）、存在しないアプリへの最初の
`save()` がそのアプリを作成します。

バックエンドはリビジョンを認識します。すべてのロードとプッシュは、その
とき観測したサーバーリビジョンを記録し、`save()` はそれを送り返します —
その間に別のクライアントが書き込んでいた場合、`save()` は相手の書き込みを
静かに上書きする代わりに、（サーバーの期待/実際のリビジョンを含む）
`ConflictError` を送出します。`load()` を呼び出して変更を適用し直し、
もう一度保存してください:

```python
from nacho import ConflictError

try:
    config.save()
except ConflictError:
    config.load()          # 並行して行われた変更を取り込む
    config.set("my.key", value)
    config.save()
```

WebSocket 接続が切断された場合、ウォッチャーは連続リトライ回数の上限付きで
自動的に再接続し（`reconnect=0` で無制限にリトライ）、接続が成功するたびに
カウンターはリセットされます。キープアライブの ping がハーフオープンな接続
を検出し、恒久的な失敗（不正なキー、削除されたアプリ）は永遠にリトライし
続ける代わりに、明確なログ行を出力してリトライループを停止します。古い
プッシュや順序が乱れたプッシュは破棄されるため、ローカルスナップショットが
巻き戻ることはありません。

CLI は SDK なしで同じ操作をカバーします —
[コマンドラインインターフェース](#コマンドラインインターフェース) を参照
してください。

## イベントシステム

`events=True` を指定すると、変更がローカルで行われたかサーバーからプッシュ
されたかに関わらず、Nacho は書き込みが成功するたびに変更通知をディスパッチ
します。イベントには変更されたパス、旧値、新値、イベントタイプが含まれます。

```python
from nacho import Nacho, EventType

config = Nacho("config.yaml", events=True)

# "database" 配下のキーへの任意の変更で発火する
@config.on_change("database.*")
def on_db_change(path, old_value, new_value, **kwargs):
    print(f"database key changed: {path}")

# 書き込み操作ごとに 1 回発火する（集約イベント）
@config.on_change("@global")
def on_any_change(**kwargs):
    print("config was modified")

# "cache" 配下の CREATE または UPDATE イベントで発火する
@config.on_event([EventType.CREATE, EventType.UPDATE], path_pattern="cache.*")
def on_cache_change(event_type, path, new_value, **kwargs):
    print(f"{event_type.name} {path} = {new_value}")

config.set("database.host", "new-host")  # on_db_change, on_any_change
config.set("cache.ttl", 600)             # on_cache_change (CREATE)
config.set("cache.ttl", 300)             # on_cache_change (UPDATE)
```

パスパターンのリファレンス:

| パターン | 発火条件 |
|---|---|
| `None`（デフォルト） | 任意のパスでの任意の変更 |
| `"@global"` | 書き込み操作ごとに 1 回（集約） |
| `"*"` | キー単位の任意のイベント（集約イベントは除く） |
| `"database.*"` | `database` 配下にネストされた任意のキー |

ハンドラーは同期・非同期のどちらでも構いません。非同期ハンドラーは、実行中
のイベントループが存在すればそこにスケジュールされ、存在しなければ
`asyncio.run()` で実行されます。`events=True` なしで作成されたインスタンス
にハンドラーを登録すると警告がログに出力されます。そのハンドラーは決して
発火しないためです。

## スキーマ検証

Nacho はすべての書き込みでスキーマを適用します。無効な値は変更が適用される
前に `ValidationError` を送出するため、設定が無効な状態のまま残ることは
ありません。この保証はローカルの書き込みにも、サーバーが受け付けた書き込み
にも同様に適用されます。

スタンドアロンでの利用には `pip install nacho-python[schema]` が必要です。

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

# 無効な書き込みは即座に例外を送出し、設定は変更されない
try:
    config.set("database.port", "not-a-number")
except ValidationError as e:
    print(e.errors)                 # 違反内容の文字列リスト

# 書き込みを行わずに現在の設定を検査する
errors = config.validate()

# 任意の dict をスキーマに対して検証する
errors = config.check({"database": {"host": "localhost", "port": 80}})
```

## スタンドアロンでの利用

Nacho にサーバーは必須ではありません。ローカルファイルを指定するか、通常の
dict を渡すだけで、スクリプト、テスト、シングルプロセスのアプリケーション
向けの自己完結型設定ライブラリとして動作します。以下の内容はすべて、
ファイル、dict、リモートサーバーのいずれをバックエンドにしても同一に
振る舞います。

### 読み取りと書き込み

```python
from nacho import Nacho

config = Nacho({"database": {"host": "127.0.0.1", "port": 5432}})  # インメモリ
config = Nacho("config.yaml")                                      # ファイルバックエンド

# 妥当な型変換を伴う型付き読み取り
host    = config.get("database.host")
port    = config.get_int("database.port")
debug   = config.get_bool("app.debug")
tags    = config.get_list("app.tags")
options = config.get_dict("app.options")

config.update({"logging": {"level": "DEBUG"}})   # ディープマージ
config.replace({"database": {"host": "prod-db", "port": 5432}})
config.delete("legacy.setting")
config.load()                                    # ストレージから再読み込み
config.save()                                    # ストレージへ永続化
print(config.json())                             # JSON 文字列としてエクスポート
```

### トランザクション

複数の書き込みを 1 つのアトミックな操作にまとめます。トランザクションは
ブロックが正常に終了したときにコミットされ、例外が発生した場合は破棄
されます。コミットはトランザクションの操作を*現在の*設定に対して再生する
ため、トランザクションが開いている間に行われた無関係な書き込みは破棄
されず、保持されます:

```python
with config.transaction() as txn:
    txn.set("database.host", "new-host")
    txn.set("database.port", 5433)
# ここでハンドラーが集約された変更とともに 1 回だけ発火する
config.save()
```

### 環境変数によるオーバーライド

`env_prefix` を渡すと、ロード時に環境変数を設定にオーバーレイします。
変数名は `{PREFIX}_{NESTED_KEY}` の形式に従い、ネストの階層はデリミタ
（デフォルトは `_`）で区切ります:

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

値は曖昧でない場合に型変換されます: `true`/`false`/`yes`/`no`/`on`/`off` は
ブール値になり、数値文字列は数値になり（`"1"` はブール値ではなく整数 1）、
JSON と見なせる文字列は JSON としてパースされます。浮動小数点数はテキスト
がラウンドトリップする場合にのみパースされるため、`MYAPP_VERSION=3.10` は
文字列 `"3.10"` のままになり、値をクォートする（`MYAPP_PORT='"8080"'`）と
文字列のまま維持されます。それ以外はすべて文字列のままです。

名前自体にアンダースコアを含むキーは、ネストにデリミタを二重にして使い
ます: `MYAPP_DB__MAX_CONNECTIONS` は `db.max_connections` を設定します。
環境変数オーバーライドは実行時のみのオーバーレイです: `save()` は
オーバーレイされたビューではなく、保存されている設定を永続化します。

## コマンドラインインターフェース

```bash
nacho --help
nacho --version
```

すべてのリモートコマンドは `--remote <url>`、`--app-name <name>`（デフォルト
`default`）、`--api-key <key>` を受け取ります。エラーは stderr に書き込まれ、
終了コードが失敗の種類を区別するため、スクリプトはメッセージを解析せずに
分岐できます:

| 終了コード | 意味 |
|---|---|
| 0 | 成功 |
| 1 | 一般エラー（スキーマ違反、トランスポート障害、extras の欠落） |
| 2 | 使い方のエラー（不正なフラグや引数） |
| 3 | 見つからない（アプリ、キー、パス、履歴リビジョンの欠落） |
| 4 | リビジョン競合（並行書き込みが勝った） |
| 5 | 認証失敗（API キーの誤りや欠落、読み取り専用サーバー） |

出力は `--format {json,yaml,toml}`（デフォルト `json`）でレンダリングされる
ため、すべてのコマンドの出力は機械可読です。`nacho get missing.key` は
`None` を表示する代わりに、stderr にメッセージを出力して終了コード 3 で
終了します。

### 値の操作

```bash
# キーまたは設定全体を、ローカルまたはリモートから読み取る
nacho get database.host --config config.yaml
nacho get --format json --remote http://config-server:8000 --app-name my-service

# 現在のリビジョンを出力に含める
nacho get --show-revision --format json --remote http://config-server:8000

# 書き込みと削除。オプションで競合安全なリビジョンチェック付き
nacho set cache.ttl 600 --remote http://config-server:8000 --revision 3
nacho delete legacy.setting --remote http://config-server:8000 --revision 4

# 自動検出が誤る可能性がある場合に型を強制する
nacho set app.version 3.10 --type str --remote http://config-server:8000
nacho set app.flags '{"beta": true}' --type json --remote http://config-server:8000

# ローカルファイルでの同等の操作
nacho set database.port 5432 --config config.yaml
nacho delete legacy.setting --config config.yaml
```

### アプリ

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

### スキーマと検証

```bash
# サーバーが適用しているスキーマを表示または置き換える
nacho schema get --remote http://config-server:8000 --app-name my-service
nacho schema push schema.json --remote http://config-server:8000 --app-name my-service

# サーバーに保存されたスキーマに対してローカルファイルを検証する
nacho validate --config config.yaml --remote http://config-server:8000 --app-name my-service

# 代わりにローカルのスキーマファイルに対して検証する
nacho validate --config config.yaml --schema schema.json
```

### 履歴とロールバック

```bash
nacho history list --remote http://config-server:8000 --app-name my-service
nacho history show 41 --remote http://config-server:8000 --app-name my-service

# リビジョン 41 を新しいリビジョンとして復元。--revision-check で競合安全にする
nacho rollback 41 --remote http://config-server:8000 --app-name my-service --revision-check 42
```

### ライブ更新

```bash
# 現在の設定を表示し、その後は変更ごとに 1 行の JSON を出力する（Ctrl+C で停止）
nacho watch --remote http://config-server:8000 --app-name my-service
```

### スキャフォールディング

```bash
# 組み込みテンプレートから設定ファイルを作成する
nacho init config.yaml --template default
# テンプレート: empty, default, web-app, api-service, microservice
```

## Docker

Nacho はマルチステージの `Dockerfile` を同梱しており、設定サーバーを非 root
ユーザーで実行する小さな Alpine ベースのイメージを生成します。コンテナの
ヘルスチェックは `/health` に対して行われます。公開イメージは Docker Hub と
GHCR で入手できます:

```bash
docker pull k3scat/nacho:latest
docker pull ghcr.io/nya-foundation/nacho:latest

# サーバーを起動する（UI は http://localhost:8000/ui）
docker run -p 8000:8000 k3scat/nacho:latest

# 認証を有効にして起動する
docker run -p 8000:8000 k3scat/nacho:latest \
  server --host 0.0.0.0 --config config.yaml --api-key "secure-key"

# デフォルトアプリ用に自分の設定ファイルをマウントする
docker run -p 8000:8000 \
  -v "$(pwd)/config.yaml:/app/config.yaml" k3scat/nacho:latest
```

または Compose で:

```bash
docker compose up --build
```

イメージのエントリーポイントは `nacho` で、デフォルトコマンドは
`server --host 0.0.0.0 --config config.yaml` です。任意の `nacho server`
フラグを追加してデフォルトを上書きできます。コンテナはポート `8000` を
公開します。

## 運用上の注意

- ドット記法のパスは意図的にシンプルに保たれています。キー名に含まれる
  リテラルのドットや数値文字列のキーは曖昧になるため、ネストされた
  オブジェクトキーを推奨します。
- 組み込みの API キー認証は、ローカル、プライベート、シングルテナントの
  デプロイに適しています。共有される本番デプロイでは、サービスの前段に
  スコープ付きトークン、監査ログ、レートリミットを追加すべきです。
- サーバーの状態はファイルベースかつシングルプロセスです。リビジョン
  カウンターはメモリ上の値が正となるため、データディレクトリごとに
  サーバープロセスは 1 つだけ実行してください。マルチプロセスや高可用性
  での運用が必要な場合は、ストレージ抽象化がより強力なバックエンドを
  実装するための境界になります。
- サーバーの実行中に `--config` ファイルを手動で編集しても検出されず、
  サーバーの次の書き込みが優先されます。変更は API、CLI、または UI を
  通じて行ってください。

## 開発

```bash
git clone https://github.com/nya-foundation/nacho.git
cd nacho
uv sync --all-extras

uv run pytest                                  # 高速スイート（unit + smoke）、95% カバレッジゲート
uv run pytest -m "integration or e2e" --no-cov # ライブサーバースイート
uv run pytest -m docker --no-cov               # Docker イメージのビルドとテスト
uv run playwright install chromium             # 一度だけのブラウザダウンロード
uv run pytest -m ui --no-cov                   # ブラウザ駆動の Web UI スイート

uvx ruff format . && uvx ruff check .          # フォーマットと lint（CI で強制）
```

ブランチモデル、コードスタイル、リリースプロセスについては
[CONTRIBUTING.md](CONTRIBUTING.md) を参照してください。

## コミュニティ

[GitHub](https://github.com/nya-foundation/nacho/issues) で Issue を作成
するか、[Nya Foundation Discord](https://discord.gg/jXAxVPSs7K) に参加して
ください。

## ライセンス

MIT — 詳細は [LICENSE](LICENSE) を参照してください。
