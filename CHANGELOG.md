# CHANGELOG


## v1.0.0 (2026-07-18)

### Bug Fixes

- Harden persistence and restart recovery
  ([`0f0fd81`](https://github.com/Nya-Foundation/nacho/commit/0f0fd813e8506b7b0e02dab645f279a9ba3421cc))

Preserve revision monotonicity, make persisted mutations atomic, and scope client synchronization to
  server generations. Add SDK, UI, E2E, and container regression coverage while tightening packaging
  and deployment defaults.

- Ui refine
  ([`323f1de`](https://github.com/Nya-Foundation/nacho/commit/323f1dea9e38f0d9392c0d75c369df2358e33342))

### Features

- **server**: Single API key, no read-only key and no roles
  ([`c6538ca`](https://github.com/Nya-Foundation/nacho/commit/c6538ca2738fa65f03b8102ee9807bd87eec3de7))

Access is now all-or-nothing. The `--read-only-api-key` flag, the `read_only_api_key=` argument, and
  the admin/read role split inside AuthGuard are removed; one key authenticates every request, and a
  credential that is not that key gets 401 for reads and writes alike.

Read-only remains available where it belongs, as two independent controls that need no roles:

- A client that should never write builds its instance with `read_only=True`, which raises
  PermissionError locally with no round trip. This works over RemoteStorageBackend as well as local
  files, so a service can hold itself to reads without the server knowing. - A deployment that must
  refuse every write runs with `--read-only`, which answers 403 to any mutation regardless of
  caller.

AuthMiddleware no longer needs a safe-method table, since the decision is a single boolean. A 403
  from the API now unambiguously means read-only mode, so the UI reports it that way.

BREAKING CHANGE: `--read-only-api-key` and the `read_only_api_key` argument to
  NachoOrchestrator/AuthGuard are gone. Deployments that issued a read-only key should either drop
  it and share the single API key, or keep writes out by running that server with `--read-only`.
  Consumers that only read should pass `read_only=True` when constructing Nacho.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

Claude-Session: https://claude.ai/code/session_01W3nMMEK466hdCJTF4R9Hwr

- **ui**: History diffs, safer edit flows, and an accessible editor
  ([`be5ff44`](https://github.com/Nya-Foundation/nacho/commit/be5ff44d5c83388337f14e2c3745b453c5685e8f))

Polish pass over the management UI following a four-lens design review (interaction, visual,
  accessibility, information design).

Correctness and data loss: - Validate no longer reports "valid against the schema" for apps that
  have no schema; it now says the payload parses and offers to add one. - Save renders schema
  violations as a list with the failing path set apart, matching Validate. Previously the same
  server response was flattened into a run-on paragraph on the path operators actually take. - Guard
  the four unguarded discard paths against confirmDiscard(): the 409 "load the server's version"
  link, refresh/Discard when the *other* tab holds a draft, and backdrop/Escape dismissal of the
  new-app modal (whose fields are now restored if the user keeps editing). Renaming an app preserves
  in-flight edits instead of dropping them. - errText() distinguishes 401 from 403; a valid
  read-only key no longer reports "check your API key".

Accessibility: - The code editor was an inescapable keyboard trap (WCAG 2.1.2): Tab was swallowed
  unconditionally. Escape now disarms tab capture, Shift+Tab always escapes, and a hint describes
  the escape hatch via aria-describedby. - Restore focus after modals close and after Save disables
  itself. - Notice containers are live regions; the tabs implement the full APG contract (roving
  tabindex, selection follows focus, Home/End, aria-controls); the selected app exposes
  aria-current; history actions are labelled. - Retune --muted, --faint, --rule-input and a new
  --amber-mark so every token meets its WCAG floor on both canvases.

Information design: - History gains diffs. Each row summarises itself against its predecessor (+n -n
  and the changed keys), and expanding a revision shows a unified diff rather than a full document
  dump, with raw snapshot and compare-with-current one click away. The Restore dialog states what
  the rollback will actually change. The comparison mirrors `nacho history diff` exactly (sorted
  keys, indent 2), so UI and CLI describe a revision identically -- no new endpoint required. -
  Timestamps are relative with the exact stamp on hover, replacing raw ISO-8601 with microseconds. -
  Sidebar gains a filter past 8 apps and shows elapsed time, which ranks across apps, rather than a
  revision number, which does not.

Visual: - Reclaim the dead space at wide viewports as a marginalia rail carrying the app's standing
  facts against a hairline; the editor grows into the width and now fills the viewport exactly with
  no residual scroll. - Reserve amber for state that changes under you (live, unsaved, current
  revision) and make positional markers ink -- the dirty state previously fired six amber dots at
  once. - Disabled Save empties to an outline instead of a heavy grey slab.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

Claude-Session: https://claude.ai/code/session_01W3nMMEK466hdCJTF4R9Hwr

### Breaking Changes

- **server**: `--read-only-api-key` and the `read_only_api_key` argument to
  NachoOrchestrator/AuthGuard are gone. Deployments that issued a read-only key should either drop
  it and share the single API key, or keep writes out by running that server with `--read-only`.
  Consumers that only read should pass `read_only=True` when constructing Nacho.


## v0.1.1 (2026-07-18)

### Bug Fixes

- **server**: Reject non-str API keys at construction
  ([`1ccfbed`](https://github.com/Nya-Foundation/nacho/commit/1ccfbedae46de9c9b0fdc89acbe7877a44ee841c))

Keys are compared as UTF-8 bytes, so a non-str api_key raised AttributeError deep inside hmac
  comparison — but only once a caller presented a *valid* credential, surfacing as an opaque 500
  long after the misconfiguration. Unauthenticated requests returned early at `if not token`, so a
  login smoke test looked healthy.

A falsy non-str key was worse: `api_key=[]` is falsy, so the orchestrator skipped AuthGuard entirely
  and served the API with no authentication at all, reporting auth_required=false on /health. A
  guard inside AuthGuard.__init__ alone would not catch that, so validate_api_key() also runs in
  NachoOrchestrator before the truthiness check.

Reported by a downstream integrator who passed their own list-shaped api_key config straight
  through.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>

Claude-Session: https://claude.ai/code/session_017Nbw4HkcW6Jb1uEazKcosX

### Documentation

- **ui**: Document the pre-authentication embedding contract (en/zh/ja)
  ([`af9fb94`](https://github.com/Nya-Foundation/nacho/commit/af9fb94d47afcd7de4b7a839d333a3b3bd5ca52b))

Host applications that mount the orchestrator behind their own session auth were reverse-engineering
  the SPA to avoid a second login. The two names they depend on are now a documented, tested
  contract: localStorage["nacho_api_key"] for the REST bearer header, and the URL-encoded
  NACHO_api_key cookie for the WebSocket handshake, whose path follows the mount point.

Marked as a public contract at the source so it is not renamed casually, and pinned by a UI test
  that seeds both stores and asserts no sign-in screen appears and live updates flow.

Deliberately not adding a `?token=` query parameter: query strings leak through browser history,
  Referer headers, and proxy logs. The docs say so, and point read-only embedders at
  --read-only-api-key.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>

Claude-Session: https://claude.ai/code/session_017Nbw4HkcW6Jb1uEazKcosX


## v0.1.0 (2026-07-18)

### Bug Fixes

- Correctness bugs in auth, CLI flags, WS reconnect, events, env parsing
  ([`ef19cef`](https://github.com/Nya-Foundation/nacho/commit/ef19cef721e7958b849be797c854510d6e35ab75))

- auth: compare API keys as bytes so non-ASCII tokens return 403 instead of 500 - cli: boolean flags
  use store_true ('nacho --debug server' no longer errors); default bind is 127.0.0.1 with a warning
  when exposed without --api-key (Docker CMD passes --host 0.0.0.0 explicitly) - remote: WS
  reconnect counter resets on successful connect (bounds consecutive failures, not lifetime
  disconnects); close() interrupts the backoff sleep - event: handler errors no longer crash on
  functools.partial callbacks; tracebacks are logged with exc_info - config: change events are
  diffed from the exact snapshots swapped under the write lock (no post-lock race); the
  deepcopy+diff cost is skipped entirely when events are disabled; registering a handler with
  events=False warns - env: '1'/'0' parse as integers, not booleans - __init__: NachoOrchestrator
  removed from __all__ when server extra is absent

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>

- **core**: Correctness fixes across io, path, env, events, and transactions
  ([`471195b`](https://github.com/Nya-Foundation/nacho/commit/471195bbbb03de663b97e939eb2f7f20cf5737da))

- load_file: an empty JSON file loads as {} instead of crashing construction - save_file: serialize
  before touching the file, use yaml.safe_dump so unserializable data fails at save time instead of
  bricking the config, fsync before rename, and preserve the target file's permissions -
  set_nested_value: raise ValueError when a path cannot be written instead of silently returning
  False; type-strict change detection so replacing the int 1 with True is a real change; digit
  segments on dicts use string keys so numeric JSON keys stay reachable - transactions: replay
  recorded ops onto current state at commit so interleaved writes are no longer silently discarded -
  events: dispatch in swap order under an emit lock; keep strong refs to async handler tasks; saves
  serialize in snapshot order - env: floats only parse when they round-trip ("3.10" stays a string),
  quoting forces string type, double-delimiter nesting (NACHO_DB__MAX_CONNECTIONS ->
  db.max_connections), overlay conflicts warn instead of crashing; warn when a set() is masked by an
  env override - FileStorageBackend no longer creates the file at construction (read-only instances
  never write); drop dead create_file_if_not_exists - fix install hint and remove dead
  RemoteStorageBackend import guard

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>

Claude-Session: https://claude.ai/code/session_01JwKYuxXqoUsvckp38ApPYC

- **server**: Normalize-and-check guard on app-derived filesystem paths
  ([`9118cf8`](https://github.com/Nya-Foundation/nacho/commit/9118cf8cbf6f5cba8664e6e4a11f3a60f4a08469))

CodeQL flags every flow of an app name into HistoryStore/AppStore paths as py/path-injection (20
  alerts on PR #6): the strict app-name regex does prevent traversal, but a regex is not a sanitizer
  static analysis can verify. safe_child_path() normalizes the joined path and refuses anything that
  escapes the base directory — real defense in depth at the filesystem boundary, and the canonical
  guard CodeQL recognizes.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>

Claude-Session: https://claude.ai/code/session_017Nbw4HkcW6Jb1uEazKcosX

- **server**: Safe defaults, honest writes, boot robustness, non-blocking I/O
  ([`824268d`](https://github.com/Nya-Foundation/nacho/commit/824268d27e5b6b17d1ac2fc021224855ba4a2244))

- secure-by-default: no CORS unless requested (was wildcard), run() binds 127.0.0.1 (was 0.0.0.0);
  the bundled UI is same-origin and SDK/CLI clients are not browsers, so cross-origin stays opt-in -
  HTTP route handlers are now sync and run in Starlette's threadpool, so disk writes no longer stall
  the event loop and every WS broadcast - PUT config/{path} reports failure honestly: writing
  through a scalar segment is a 400 (was silent 200), and an identical value is an explicit no-op
  (changed: false) with no revision bump - identical full-app PUT / schema PUT / empty metadata
  PATCH no longer bump the revision, so reconciliation loops can't flush the history ring - one
  corrupt or schema-invalid persisted app is skipped with a loud log at boot instead of preventing
  the whole service from starting - renaming an app disconnects old-name WS subscribers instead of
  leaving them silently mirroring a config their REST writes can't reach - WS endpoint ignores
  binary frames instead of dying with a traceback - auth errors use the same {"detail": ...}
  envelope as everything else; GET / is public as documented; encoded payloads capped at 1 MiB -
  server-managed Nacho instances drop events=True: nothing registered handlers, so every write paid
  a full deep-diff for an empty pipeline

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>

Claude-Session: https://claude.ai/code/session_01JwKYuxXqoUsvckp38ApPYC

- **ui**: Style success notices, URL-encode auth cookie, dialog a11y
  ([`94041db`](https://github.com/Nya-Foundation/nacho/commit/94041dbc241c9affe8e756f97f6a594db5da9ecf))

- notice("ok", ...) had no matching CSS rule, so success feedback rendered unstyled; add .notice.ok
  with a dedicated --ok color in both themes. - The NACHO_api_key cookie was written unencoded, so
  an API key containing ";", "," or spaces corrupted the cookie and broke WebSocket auth. The UI now
  URL-encodes the value and AuthGuard decodes it (raw form still accepted for stale cookies). -
  openModal() dialogs (New app / Edit app) now carry role="dialog", aria-modal, and aria-labelledby
  like confirmDialog already did.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>

Claude-Session: https://claude.ai/code/session_017Nbw4HkcW6Jb1uEazKcosX

### Chores

- Upgrade all locked dependencies; build image with uv from the lockfile
  ([`e782449`](https://github.com/Nya-Foundation/nacho/commit/e7824495377c59535f0281b90552bb19a9bac7f4))

Dependencies: uv lock --upgrade refreshed 16 of 54 packages (fastapi 0.139.2, starlette 1.3.1,
  uvicorn 0.51.0, websockets 16.1, pytest 9.1.1, rpds-py 2026.6.3, and friends). All suites pass on
  the new versions — the single remaining warning is FastAPI's own internal starlette deprecation,
  not ours. pyproject version floors are deliberately unchanged: they are library minimums, and
  loosening install constraints is a feature for consumers.

Dockerfile: rebuilt around uv and the lockfile —

- deps resolve with 'uv sync --frozen' from uv.lock: reproducible builds, and the dependency layer
  caches until pyproject.toml/uv.lock change (replaces the editable-install caching trick) - no
  compiler toolchain: every compiled dep ships musllinux wheels for both amd64 and arm64 (verified
  against PyPI for the cp314 tags) - runtime stage carries only the venv (non-editable install) plus
  an empty writable workdir — the source-tree copy is gone - base bumped to python:3.14-alpine;
  bytecode precompiled at build time - image size: 130MB -> 114MB uncompressed (30MB -> 27MB
  compressed); docker test suite (build, health, UI, REST, remote client) passes

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>

- **tooling**: Adopt ruff for formatting and lint
  ([`7e59e2e`](https://github.com/Nya-Foundation/nacho/commit/7e59e2e9918a49d14c07c55f1c16cb3dc4b279b8))

- [tool.ruff] replaces [tool.black]/[tool.isort]; the lint extra now installs ruff instead of
  flake8/black/isort nobody ran - repo-wide ruff format pass; lint fixes: exception chaining on
  raise sites (B904), reliable async-callable detection (B004), explicit optional-hook marker on
  StorageBackend.cleanup (B027)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>

Claude-Session: https://claude.ai/code/session_01JwKYuxXqoUsvckp38ApPYC

### Continuous Integration

- Docker suite on PRs, UI suite in release, staging lint/scan, py3.9 live leg
  ([`8f60689`](https://github.com/Nya-Foundation/nacho/commit/8f60689ffc9108f9023d33c8e4709cbbac0df6f4))

- test.yml: Dockerfile/.dockerignore changes now trigger CI, and a docker-tests job builds and
  exercises the image when image-affecting paths change (dorny/paths-filter) — previously the image
  was only ever tested at release time. - test.yml: the live integration/e2e job now runs on 3.9
  (oldest supported) alongside 3.13 instead of 3.13 only. - publish.yml: the browser UI suite now
  gates the release like the other suites already did. - format.yml/scan.yml: run on staging,
  closing the documented dev -> staging -> main flow's lint/scan gap.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>

Claude-Session: https://claude.ai/code/session_017Nbw4HkcW6Jb1uEazKcosX

- Install test jobs from uv.lock via uv sync --frozen
  ([`6e1c245`](https://github.com/Nya-Foundation/nacho/commit/6e1c2452cc74bf6de8c403b072b6723bf59bc2b6))

The test matrix, live-tests job, and the pre-release test job in publish.yml now set up uv (pinned
  0.7.9, cached) and install with 'uv sync --frozen --all-extras', so CI tests exactly the locked
  versions the Docker image ships — no more floating-constraint drift between CI and the artifact.

- pyproject.toml and uv.lock added to the test workflow's trigger paths, so dependency bumps run the
  full suite - --frozen makes a stale lockfile a hard CI failure instead of a silent re-resolve -
  semantic-release's own setup-python step in publish.yml is untouched (it does not install project
  dependencies)

Verified locally: uv lock --check passes, workflow YAML parses, and a frozen --all-extras install on
  Python 3.9 (the oldest supported floor) runs green.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>

- Pin uv 0.11.29 so Python 3.14 resolves to a stable release
  ([`4de506a`](https://github.com/Nya-Foundation/nacho/commit/4de506acd0f596ba9f19a527d6f2de5f3a5659e3))

uv 0.7.9 predates the 3.14 final release: its interpreter registry only knows cpython-3.14.0a7, so
  the CI matrix leg for '3.14' ran the test suite on an alpha whose typing._eval_type predates the
  final API — the locked pydantic then fails collection with "_eval_type() got an unexpected keyword
  argument 'prefer_fwd_module'". The suite passes on a real 3.14 (verified on 3.14.4).

uv 0.11.29 resolves '3.14' to the current stable and reads the existing uv.lock unchanged (verified
  with `uv lock --check`). The Dockerfile's uv stage is bumped to match; the image was rebuilt and
  its test suite run.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>

Claude-Session: https://claude.ai/code/session_017Nbw4HkcW6Jb1uEazKcosX

- Scan code for real, enforce lint, test and scan images before pushing
  ([`959470b`](https://github.com/Nya-Foundation/nacho/commit/959470b31fe7006d39b9ca8598a5b45b4f337a11))

- scan.yml: CodeQL now runs on pushes/PRs to main and dev with no path filter (it previously only
  fired on dependency-manifest changes on side branches, so source was never scanned);
  dependency-review stays PR-only - format.yml -> lint: ruff format --check + ruff check on
  PRs/pushes to dev and main; drops the old job that installed black but never ran it and
  auto-committed with [skip ci] - publish.yml: docker test suite (pytest -m docker) gates
  publishing, and Trivy scans a locally-built image before any push (was: scan after the multi-arch
  image was already public) - test.yml: Codecov uploads from one matrix leg and no longer fails fork
  PRs that lack the token - untrack .serena/ (personal tooling config); fix .dockerignore typo

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>

Claude-Session: https://claude.ai/code/session_01JwKYuxXqoUsvckp38ApPYC

### Documentation

- Document new defaults, CLI exit codes, and revision-aware SDK (en/zh/ja)
  ([`0a9eb3a`](https://github.com/Nya-Foundation/nacho/commit/0a9eb3a9886cef2ebe505f5a0b5b23953e38af5b))

- authentication: '/' is public, cross-origin access is opt-in - remote clients: revision tracking,
  ConflictError recovery example, keepalive and permanent-failure watcher behavior - transactions:
  commit replays onto current state - env overrides: float round-trip rule, quoting escape hatch,
  doubled-delimiter nesting - CLI: exit-code table, --type flag, apps show/rename/describe -
  development: ui test suite and ruff commands

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>

Claude-Session: https://claude.ai/code/session_01JwKYuxXqoUsvckp38ApPYC

- Read-only key, If-None-Match polling, and history diff (en/zh/ja)
  ([`f97cc92`](https://github.com/Nya-Foundation/nacho/commit/f97cc9295c63bbd332a60c29fd05a3ac1a56e0a6))

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>

Claude-Session: https://claude.ai/code/session_017Nbw4HkcW6Jb1uEazKcosX

- Rewrite README (en/zh/ja) and CONTRIBUTING
  ([`e577cfa`](https://github.com/Nya-Foundation/nacho/commit/e577cfad30910cdd9e3798ddaa43bba5f2087f88))

Complete rewrite of all Markdown documentation: professional tone, no emoji, accurate to the current
  codebase.

- README: documents the new surface — history/rollback (REST, CLI, UI), apps/schema/watch CLI
  commands, server flag table incl. --history-limit, revision concurrency via body 'revision'
  (If-Match references removed), loopback default bind and auth posture (401, public /docs), remote
  client connect/reconnect semantics, env override coercion rules, operational notes, and a
  development section with the real test invocations - README_zh / README_ja: full translations of
  the new README, structure verified one-to-one (58 code fences, 56 headings, 64 table rows each) -
  CONTRIBUTING: tightened and updated — uv-first setup, marker-by-directory test layout with the
  coverage-gate caveat, conventional commits table, release pipeline as actually implemented
  (test-gated publish)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>

- Ruff in CONTRIBUTING, single-process and local-write caveats (en/zh/ja)
  ([`e743643`](https://github.com/Nya-Foundation/nacho/commit/e743643ebe7e63354c54a71879c928a1e3a64b29))

- CONTRIBUTING still instructed black/isort; the project is ruff-only. Also list the ui suite, and
  include the UI + docker suites in the release-gate description. - README: document that app state,
  revisions, and WS subscriptions are per-process (one server process per data dir; no --workers),
  and that local CLI writes are read-modify-write without a cross-process lock. Mirrored in the
  zh/ja translations.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>

Claude-Session: https://claude.ai/code/session_017Nbw4HkcW6Jb1uEazKcosX

### Features

- Add brand identity assets (logo, icon, social banner)
  ([`752aa78`](https://github.com/Nya-Foundation/nacho/commit/752aa7877af063134a8969eac2fc2d39408afadd))

Direction A 'Config Dot': geometric n. mark on rounded tile, amber accent (#D6892A/#E0A44A) on warm
  neutrals, Inter-derived wordmark outlined to paths. SVG light/dark lockups and marks, 512px icon,
  1280x640 GitHub social banner.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>

- Cli app/schema/watch commands, consistent API responses, better auth UX
  ([`2d7a766`](https://github.com/Nya-Foundation/nacho/commit/2d7a7665b52b064f0d04292710708b66b9c8be97))

CLI: - new 'nacho apps list|create|delete' for remote app management - new 'nacho schema get|push'
  for remote schema management - new 'nacho watch' streaming live config updates over WebSocket -
  'nacho validate --remote' validates a local file against the schema the server actually enforces
  (--schema now optional in remote mode) - 'nacho get KEY --show-revision' works for single keys
  (server now sends revision headers on path GETs) - errors and warnings go to stderr; deleting a
  missing key exits 1; unknown init template is rejected at parse time

API: - schema GET returns {"data": <schema>} (was double-nested) - PUT /api/apps/{name} no longer
  renames; PATCH /metadata is the rename path - validate response 'data' is always the submitted
  payload, never current config - auth failures return 401 with WWW-Authenticate (was 403); /docs,
  /redoc, /openapi.json are public as advertised by GET /

UI: - adapts to the new schema response shape - WS reconnect retries forever with capped backoff
  instead of giving up - sidebar refreshes on live updates plus a light 30s poll - app-list load
  failures render an error instead of an unhandled rejection

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>

- Config history and rollback
  ([`f486baf`](https://github.com/Nya-Foundation/nacho/commit/f486bafc7a4d2b59b565b395ceab5a3ad2fe240f))

Every revision bump now stores a full snapshot (config + schema + metadata) in a per-app ring buffer
  — one JSON file per revision under data_dir/history/{app}/ when a data directory is configured,
  in-memory otherwise. --history-limit N controls retention (default 50, 0 disables). No database:
  snapshots are kilobytes, writes are already serialized under the manager lock, and pruning is a
  file unlink.

Rollback is roll-forward: restoring revision N creates a new revision whose content equals snapshot
  N. The counter stays monotonic (WS protocol, ETag, and conflict detection all assume it), and a
  rollback can itself be rolled back. Config and schema restore together, so the result always
  validates.

- REST: GET /api/apps/{name}/history (metadata, newest first) GET
  /api/apps/{name}/history/{revision} (full snapshot) POST /api/apps/{name}/rollback {revision,
  expected_revision} - CLI: nacho history list|show, nacho rollback REV [--revision-check N] - UI:
  History tab with snapshot viewer and conflict-safe Restore - fix: full-app replace (PUT
  /api/apps/{name}) and rename now broadcast to WebSocket watchers — previously only config-endpoint
  writes did - tests: HistoryStore both backends, manager rollback semantics, API error paths, WS
  broadcast on rollback, CLI commands, live-server integration, CLI e2e flow (set, history
  list/show, rollback, get)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>

- **cli**: History diff command and --read-only-api-key server flag
  ([`4c5a6ae`](https://github.com/Nya-Foundation/nacho/commit/4c5a6aeded3db15f87225e70b1cf1ffa704f8de5))

- `nacho history diff A [B]` prints a unified diff between two stored revisions, or between revision
  A and the current config when B is omitted, with a note when the schema also differs. - `nacho
  server --read-only-api-key` exposes the new read-only key; the unauthenticated-exposure warning
  now accounts for it (a server with only a read-only key cannot be written to at all). - e2e:
  read-only key read/write split and a live history-diff flow.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>

Claude-Session: https://claude.ai/code/session_017Nbw4HkcW6Jb1uEazKcosX

- **cli**: Shared REST client, typed exit codes, and app metadata commands
  ([`84c7c5f`](https://github.com/Nya-Foundation/nacho/commit/84c7c5fbd47f3c01adc6c31075363185c841acfc))

- all remote operations go through the shared NachoClient; the CLI's duplicate hand-rolled REST
  helpers are gone (840 -> 681 lines with more behavior) - typed exit codes so scripts can branch
  without parsing stderr: 0 success, 1 generic, 2 usage, 3 not found, 4 revision conflict, 5 auth
  failure (e2e auth flow asserts the new code) - one @cli_command error path replaces nine
  copy-pasted try/except blocks; argparse parent parsers replace twelve duplicated flag definitions;
  dead unreachable branches removed - 'get missing.key' exits 3 with a stderr message instead of
  printing None with exit 0, consistent between local and remote - 'set --type
  {auto,str,int,float,bool,json}' can force a type (storing the string "3.10" from the CLI was
  previously impossible) - new 'apps show', 'apps rename', 'apps describe' subcommands
  (revision-check aware); --format is json/yaml/toml (raw dropped); bare 'nacho' prints help and
  exits 0; --debug works after the subcommand; loopback detection for the exposed-server warning -
  e2e suite fails loudly in CI when the nacho binary is missing instead of silently collecting zero
  tests - tests/unit/test_cli.py rewritten: 74 tests, 100% statement coverage of cli/main.py

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>

Claude-Session: https://claude.ai/code/session_01JwKYuxXqoUsvckp38ApPYC

- **remote**: Revision-aware SDK with typed errors, WS keepalive, and safe shutdown
  ([`829aebf`](https://github.com/Nya-Foundation/nacho/commit/829aebf6d2418a953ba2d80bcad7eb7623aa076b))

- new shared NachoClient (nacho/client.py): one implementation of auth headers, URL building, and
  error mapping for the SDK and CLI; HTTP failures raise typed errors (AuthError, NotFoundError,
  ConflictError, RemoteError) that preserve the server's detail payload - RemoteStorageBackend
  tracks the server revision from loads, saves, and WS pushes, and sends it on save() so concurrent
  remote writes surface as ConflictError instead of silently losing updates - WS keepalive pings
  detect half-open connections that previously left watchers silently stale forever - permanent
  handshake failures (bad key, missing app) stop the retry loop with a clear error instead of
  retrying every 5s forever - construction now fails fast on rejected credentials (verify against an
  authenticated endpoint, not /health) - start/close are lock-guarded; close() can no longer orphan
  a just-created connection - stale WS revisions and stale REST reads are dropped so local state
  never rolls backwards

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>

Claude-Session: https://claude.ai/code/session_01JwKYuxXqoUsvckp38ApPYC

- **server**: Read-only API key, request body cap, and conditional GETs
  ([`37815ee`](https://github.com/Nya-Foundation/nacho/commit/37815ee211a8555cf9e48645a8567b507f1eb92a))

- AuthGuard now grants roles: the existing api_key is "admin", and an optional read_only_api_key
  grants "read" — safe methods and WebSocket subscriptions pass, writes get 403. Dashboards and
  pollers no longer need the write credential. - Request bodies over 2 MiB are rejected with 413 via
  Content-Length, closing the gap where a raw JSON object bypassed the 1 MiB encoded- string cap. -
  GET /config and /config/{path} honour If-None-Match against the revision ETag and answer 304 with
  no body, so pollers only pay for revisions that actually moved.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>

Claude-Session: https://claude.ai/code/session_017Nbw4HkcW6Jb1uEazKcosX

- **ui**: "paper & Dot" redesign of the management UI
  ([`308d51a`](https://github.com/Nya-Foundation/nacho/commit/308d51aaa3cf7188cd0bf126c62be3b714a4ee24))

Complete visual refactor aligned with the Config Dot brand identity, produced by a three-designer /
  three-judge design panel and synthesized into one spec:

- typeset-document aesthetic: warm paper (#F6F6F3) and ink (#1E1E1B) surfaces, hairline rules
  instead of card chrome, hierarchy from typography and whitespace; light and dark themes via
  prefers-color-scheme (dark editor sheet is the brand tile) - the amber dot (#D6892A) is the entire
  accent system - live status, current revision, selected app, active tab, dirty marker, armed Save;
  green removed from the palette; syntax colors stay desaturated with ink-weight keys - inline SVG
  brand mark and wordmark, data-URI favicon, border radii derived from the logo tile ratio, single
  shadow (modal/toast only), system fonts, zero external requests - interaction refinements: editor
  drafts survive tab switches, manual refresh link when clean / Discard when dirty, Cmd/Ctrl+S save,
  one-shot connect pulse + hollow reconnecting dot, inline history snapshot expansion, tab ARIA with
  arrow keys, reduced-motion support - all hardened behavior preserved byte-for-byte against the
  test contract: auth/cookie handling, monotonic WS revision application, dirty-editor conflict
  protection, close-code-aware reconnects

1825 lines (was 1424); Playwright UI suite (7), smoke, unit (479), integration and e2e (18) all
  green.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>

Claude-Session: https://claude.ai/code/session_01JwKYuxXqoUsvckp38ApPYC

- **ui**: Styled confirm dialogs replace native confirm()
  ([`6d50f35`](https://github.com/Nya-Foundation/nacho/commit/6d50f354029d5c2c8ee40a6fe8dd6e8114d58eb5))

- promise-based confirmDialog() on the existing modal infrastructure: scrim, tile-radius sheet,
  text-link Cancel, ink confirm with danger fill for destructive actions (delete app, discard edits)
  - specific copy per action: "Discard unsaved changes?" names the app and dirty buffers; "Restore
  revision N?" explains rollback-as-new- revision; "Delete "name"?" states the blast radius - full
  keyboard/a11y handling: focus trapped between the two actions, confirm focused on open, Escape
  cancels, focus restored to the invoking element; role=dialog aria-modal aria-labelledby - every
  native confirm() call replaced (discard on app/tab switch and sign-out, notice reload actions,
  restore, restore-over-dirty-drafts, delete); beforeunload stays native by design - Playwright
  tests updated: active-tab re-click asserts no #confirm- dialog appears; history restore drives the
  styled dialog

UI suite (7), smoke, and unit (479) suites green.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>

Claude-Session: https://claude.ai/code/session_01JwKYuxXqoUsvckp38ApPYC

### Performance Improvements

- **server**: Per-app locks and concurrent WebSocket broadcast
  ([`e445acd`](https://github.com/Nya-Foundation/nacho/commit/e445acd2eac888030ca3754c26dcf62e09986f12))

The AppManager lock previously serialized every write across ALL apps and held disk I/O (app store +
  history snapshot) while doing so. The manager lock now guards only the app registry; each
  ConfigApp carries its own lock that keeps revision check, mutation, and persistence of one app
  atomic while different apps proceed in parallel. A tombstone flag stops a writer that raced a
  delete from resurrecting the app's files on disk.

WebSocketHub.broadcast now gathers sends concurrently with a per-send timeout, so one slow or
  half-dead subscriber can no longer delay delivery to every other subscriber of the same app.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>

Claude-Session: https://claude.ai/code/session_017Nbw4HkcW6Jb1uEazKcosX

### Refactoring

- Delete dead code and consolidate duplicated logic
  ([`1116778`](https://github.com/Nya-Foundation/nacho/commit/111677844c70333c82fe2b1f491d403121cb3909))

Removals (all verified unreferenced outside their own tests): -
  EventPipeline.emit()/register_handler() and the misleading 'server compat' comments;
  Nacho.data/event_pipeline/event_disabled properties; reload alias - _AsyncEventRunner background
  loop (asyncio.run covers the no-loop case) - AuthGuard.set_api_key; CLI 'connect' command
  (duplicate of 'get'); unused template metadata; dead remote kwargs in local CLI branches; --event
  flag - If-Match/ETag request channel (body 'revision' is the single concurrency mechanism;
  response headers unchanged); set_path get/re-get dance - env prefix-free scan mode and its
  system-var blocklist (prefix is now required); unreachable create_missing option

Consolidations: - one normalize_format validator shared by all server request models -
  SchemaValidator._load now reuses utils.io.load_file (plus object check) - shared TRUTHY/FALSY
  string sets between env parsing and get_bool - single remote app-creation path: connecting never
  mutates the server; load() raises a helpful 404 error, save() auto-creates on first write -
  install hints corrected to the real package name (nacho-python[...]) - ruff clean: fixed all
  pre-existing unused imports/variables

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>

### Testing

- Browser UI suite, live concurrency/auth/format coverage, client units
  ([`d21fd9b`](https://github.com/Nya-Foundation/nacho/commit/d21fd9b474eaf0a6dbbb42a23398ec2666f2b567))

- tests/ui: 7 Playwright tests driving the real SPA against a live server subprocess — load, auth
  flow (wrong and right key), edit+save round trip, live WS update, dirty-editor conflict
  protection, active-tab re-click, history restore; the UI previously had zero functional coverage -
  tests/integration/test_live_concurrency.py: optimistic-concurrency over a real transport —
  stale-revision 409, N concurrent writers losing no updates, SDK conflict + recovery, wrong-key
  REST/WS, cookie auth (REST and WS handshake), YAML/TOML round trip, and read-only mode against a
  live server - tests/unit/test_client.py: full coverage of the shared NachoClient (error mapping,
  revision headers, every endpoint's payload shape) - new 'ui' marker (excluded from the default
  run) and a CI job that installs chromium and runs the browser suite

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>

Claude-Session: https://claude.ai/code/session_01JwKYuxXqoUsvckp38ApPYC

- Real e2e coverage for WS/auth/schema flows; ci: gate publish on tests
  ([`7dfe394`](https://github.com/Nya-Foundation/nacho/commit/7dfe3943db1e0e71f77c4c55f31faef83b8b036f))

Tests: - live_server now starts through the real 'nacho server' CLI entrypoint, via a
  make_live_server factory supporting api_key and same-port/data-dir restarts - new integration
  suite joins both halves of the WS contract for the first time: a real websocket-client watcher
  against a real server receives pushed updates; survives a server restart and resubscribes; bearer
  auth enforced over real transport (REST 401 + authenticated WS push); schema-violating writes
  rejected by a live server - e2e CLI flow rewritten: set/get round-trip with typed values,
  apps/schema lifecycle incl. rejected invalid write and 'validate --remote', auth flow with
  --api-key; assertions check parsed JSON and exit codes, and no set-up step result is ignored -
  sleep-based races replaced with bounded waits (event tests, watcher join) - coverage excludes no
  longer hide 'pass'/'raise ImportError' branches

CI/packaging: - test.yml: Python 3.9 added to the matrix (suite verified on 3.9); PRs to main now
  trigger tests; new live-tests job runs integration+e2e suites - publish.yml: publish job is gated
  on a test job (unit+smoke+live), matching what the workflow header always claimed; stale
  requirements.txt trigger gone - requirements.txt deleted (duplicated pyproject extras and had
  drifted) - pyproject: 3.14 classifier added - Dockerfile: remote extra included (in-container
  --remote now works), HEALTHCHECK against /health, dependency layer comments fixed -
  docker-compose: bogus host-side BuildKit env removed, explicit --host 0.0.0.0

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>

- Ws fan-out, real CLI watch, UI create/delete/reconnect/cookie-auth
  ([`7d207fb`](https://github.com/Nya-Foundation/nacho/commit/7d207fb941f66ebe55167134df76cbbd9c91bb75))

Close the e2e blind spots found in review:

- integration: one REST write must fan out to ALL live WS subscribers (broadcast loop was only ever
  exercised with a single watcher). - e2e: `nacho watch` runs against a real server for the first
  time — initial config line, then a pushed update. - ui: app create/delete through the modal flow,
  WS reconnect + resumed live updates after a server restart, and an API key with cookie-hostile
  characters (";", spaces) authenticating the WS via the encoded cookie. - unit:
  AuthGuard.verify_cookie accepts encoded and raw forms.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>

Claude-Session: https://claude.ai/code/session_017Nbw4HkcW6Jb1uEazKcosX


## v0.0.3 (2026-05-22)

### Bug Fixes

- Update ui url path
  ([`f02ece8`](https://github.com/Nya-Foundation/nacho/commit/f02ece853debda89c11b98b8ef45c30a9ea9a760))

### Chores

- Doc update..
  ([`9a5b6fd`](https://github.com/Nya-Foundation/nacho/commit/9a5b6fd47f600923f311117fea1a027117537e90))


## v0.0.2 (2026-05-18)

### Bug Fixes

- Bump test coverage, and minor fixes
  ([`fb53b39`](https://github.com/Nya-Foundation/nacho/commit/fb53b395fa9a490483153ce1c3e4a3ef1c29ec43))

### Chores

- Update README.md text banner
  ([`c335054`](https://github.com/Nya-Foundation/nacho/commit/c335054b328509580b796d50f09a0e7c06d27602))


## v0.0.1 (2026-05-18)

### Bug Fixes

- Update python ver test coverage... fix test error on cli output assertion
  ([`7c102ad`](https://github.com/Nya-Foundation/nacho/commit/7c102ad660b7e1977145bbc1dc0b20909f3cfcd9))

### Chores

- Add text banner
  ([`30eb777`](https://github.com/Nya-Foundation/nacho/commit/30eb777dee409ebcc9070f1c885f0e0d39fc4279))


## v0.0.0 (2026-05-18)
