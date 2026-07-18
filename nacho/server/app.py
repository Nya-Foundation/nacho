"""API-first Nacho configuration server."""

from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import uvicorn
from fastapi import (
    FastAPI,
    HTTPException,
    Request,
    Response,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from nacho._version import __version__
from nacho.config import Nacho
from nacho.schema import ValidationError
from nacho.server.auth import AuthGuard, AuthMiddleware
from nacho.utils.io import dump_string, load_string
from nacho.utils.path import get_nested_value

from .models import (
    AppCreateRequest,
    AppMetadataRequest,
    AppReplaceRequest,
    ConfigRequest,
    ConvertRequest,
    PathUpdateRequest,
    RollbackRequest,
    SchemaUpdateRequest,
)
from .runtime import AppManager, ConfigApp, RevisionConflictError

LOGGER = logging.getLogger(__name__)

_UI_INDEX = Path(__file__).parent / "ui" / "index.html"
# Cap encoded string payloads: parsing is CPU-bound (YAML anchors expand),
# and no legitimate config approaches this size.
_MAX_PAYLOAD_BYTES = 1024 * 1024
# Cap whole request bodies (a raw JSON object bypasses the string cap above).
# Checked via Content-Length, which every real JSON client sends.
_MAX_BODY_BYTES = 2 * 1024 * 1024


class InvalidConfigDataError(ValueError):
    """Raised when a request body cannot be parsed as config data."""


class NachoOrchestrator:
    """Small FastAPI wrapper around one or more :class:`Nacho` instances."""

    def __init__(
        self,
        apps: Union[Dict[str, Nacho], Nacho, None] = None,
        api_key: Optional[str] = None,
        read_only: bool = False,
        cors_origins: Optional[List[str]] = None,
        data_dir: Optional[Union[str, Path]] = None,
        logger: Optional[logging.Logger] = None,
        history_limit: int = 50,
        read_only_api_key: Optional[str] = None,
    ) -> None:
        self.read_only = read_only
        # No CORS by default: the bundled UI is same-origin and SDK/CLI
        # clients are not browsers, so cross-origin access is opt-in.
        self.cors_origins = list(cors_origins) if cors_origins is not None else []
        self.logger = logger or LOGGER
        self.auth = (
            AuthGuard(api_key=api_key, read_only_api_key=read_only_api_key)
            if (api_key or read_only_api_key)
            else None
        )
        self.manager = AppManager(
            data_dir=Path(data_dir) if data_dir else None,
            logger=self.logger,
            history_limit=history_limit,
        )

        self.manager.load_persisted()
        self._load_initial_apps(apps)

        if not self.manager.apps:
            self.manager.create("default", config_data={}, description="Default config")

        self.app = self._create_app()
        self._setup_middleware()
        self._setup_routes()

    def _load_initial_apps(self, apps: Union[Dict[str, Nacho], Nacho, None]) -> None:
        if apps is None:
            return
        if isinstance(apps, Nacho):
            apps = {"default": apps}
        for name, config in apps.items():
            self.manager.create(name, config=config, replace=True)

    def _create_app(self) -> FastAPI:
        @asynccontextmanager
        async def lifespan(_: FastAPI):
            self.logger.info("Starting Nacho API server")
            yield
            self.logger.info("Stopping Nacho API server")
            self.manager.cleanup()

        return FastAPI(
            title="Nacho API",
            description="Schema-first dynamic configuration service",
            version=__version__,
            lifespan=lifespan,
        )

    def _setup_middleware(self) -> None:
        @self.app.middleware("http")
        async def cap_body_size(request: Request, call_next):
            length = request.headers.get("content-length")
            if length and length.isdigit() and int(length) > _MAX_BODY_BYTES:
                return JSONResponse(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    content={
                        "detail": f"Request body exceeds {_MAX_BODY_BYTES // (1024 * 1024)} MiB"
                    },
                )
            return await call_next(request)

        if self.cors_origins:
            self.app.add_middleware(
                CORSMiddleware,
                allow_origins=self.cors_origins,
                allow_credentials=self._allow_cors_credentials(),
                allow_methods=["*"],
                allow_headers=["*"],
            )
        if self.auth:
            self.app.add_middleware(AuthMiddleware, auth=self.auth, logger=self.logger)

    def _setup_routes(self) -> None:
        @self.app.get("/")
        def root() -> Dict[str, Any]:
            return {
                "name": "nacho",
                "version": __version__,
                "docs": "/docs",
                "health": "/health",
            }

        @self.app.get("/health")
        def health() -> Dict[str, Any]:
            return {
                "status": "ok",
                "version": __version__,
                "apps": len(self.manager.apps),
                "read_only": self.read_only,
                "auth_required": self.auth is not None,
            }

        @self.app.get("/ui", include_in_schema=False)
        def ui() -> FileResponse:
            if not _UI_INDEX.is_file():
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Management UI is not bundled with this installation",
                )
            return FileResponse(_UI_INDEX, media_type="text/html")

        @self.app.get("/api/apps")
        def list_apps() -> Dict[str, Dict[str, Dict[str, Any]]]:
            return {"data": self.manager.list_info()}

        @self.app.post("/api/convert")
        def convert_payload(request: ConvertRequest) -> Dict[str, Any]:
            """Convert a config/schema payload between json, yaml, and toml."""
            try:
                obj = self._parse_config(request.data, request.from_)
                text = dump_string(obj, request.to)
            except ValueError as exc:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
                ) from exc
            return {"format": request.to, "data": text}

        @self.app.post("/api/apps", status_code=status.HTTP_201_CREATED)
        def create_app(request: AppCreateRequest) -> Dict[str, Any]:
            self._check_writable()
            try:
                config_data = self._parse_config(request.data, request.format)
                schema = self._parse_schema(request.schema_, request.schema_format)
                app = self.manager.create(
                    request.name,
                    config_data=config_data,
                    description=request.description,
                    schema=schema,
                )
            except (ValueError, ValidationError) as exc:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
                ) from exc
            return {"message": "App created", "app": app.info}

        @self.app.get("/api/apps/{app_name}")
        def get_app(app_name: str) -> Dict[str, Dict[str, Any]]:
            return {"data": self._get_app(app_name).info}

        @self.app.put("/api/apps/{app_name}")
        def replace_app(
            app_name: str,
            request: AppReplaceRequest,
        ) -> Dict[str, Any]:
            self._check_writable()
            try:
                config_data = self._parse_config(request.data, request.format)
                schema = self._parse_schema(request.schema_, request.schema_format)
                app = self.manager.replace(
                    app_name,
                    config_data=config_data,
                    description=request.description,
                    schema=schema,
                    expected_revision=request.revision,
                )
            except KeyError:
                raise self._not_found(app_name) from None
            except RevisionConflictError as exc:
                raise self._conflict(exc) from exc
            except (ValueError, ValidationError) as exc:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
                ) from exc
            return {"message": "App replaced", "app": app.info}

        @self.app.patch("/api/apps/{app_name}/metadata")
        def update_metadata(
            app_name: str,
            request: AppMetadataRequest,
        ) -> Dict[str, Any]:
            self._check_writable()
            try:
                app = self.manager.rename(
                    app_name,
                    new_name=request.name,
                    description=request.description,
                    expected_revision=request.revision,
                )
            except KeyError:
                raise self._not_found(app_name) from None
            except RevisionConflictError as exc:
                raise self._conflict(exc) from exc
            except ValueError as exc:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
                ) from exc
            return {"message": "App metadata updated", "app": app.info}

        @self.app.delete("/api/apps/{app_name}")
        def delete_app(app_name: str) -> Dict[str, str]:
            self._check_writable()
            if not self.manager.delete(app_name):
                raise self._not_found(app_name) from None
            return {"message": f"App {app_name!r} deleted"}

        @self.app.get("/api/apps/{app_name}/config")
        def get_config(app_name: str, request: Request, response: Response) -> Any:
            app = self._get_app(app_name)
            not_modified = self._not_modified(request, app)
            if not_modified is not None:
                return not_modified
            self._set_revision_headers(response, app)
            return app.config.get_all()

        @self.app.put("/api/apps/{app_name}/config")
        def replace_config(
            app_name: str,
            request: ConfigRequest,
        ) -> Dict[str, Any]:
            self._check_writable()
            try:
                config_data = self._parse_config(request.data, request.format)
                app = self.manager.replace_config(
                    app_name,
                    config_data,
                    expected_revision=request.revision,
                )
            except KeyError:
                raise self._not_found(app_name) from None
            except RevisionConflictError as exc:
                raise self._conflict(exc) from exc
            except (ValueError, ValidationError) as exc:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
                ) from exc
            return {
                "message": "Configuration replaced",
                "revision": app.revision,
                "data": app.config.get_all(),
            }

        @self.app.get("/api/apps/{app_name}/schema")
        def get_schema(app_name: str) -> Dict[str, Any]:
            app = self._get_app(app_name)
            return {"data": app.schema}

        @self.app.put("/api/apps/{app_name}/schema")
        def replace_schema(
            app_name: str,
            request: SchemaUpdateRequest,
        ) -> Dict[str, Any]:
            self._check_writable()
            try:
                schema = self._parse_schema(request.schema_, request.schema_format)
                app = self.manager.update_schema(
                    app_name,
                    schema,
                    expected_revision=request.revision,
                )
            except KeyError:
                raise self._not_found(app_name) from None
            except RevisionConflictError as exc:
                raise self._conflict(exc) from exc
            except (ValueError, ValidationError) as exc:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
                ) from exc
            return {"message": "Schema updated", "revision": app.revision, "schema": app.schema}

        @self.app.get("/api/apps/{app_name}/config/{path:path}")
        def get_path(app_name: str, path: str, request: Request, response: Response) -> Any:
            app = self._get_app(app_name)
            not_modified = self._not_modified(request, app)
            if not_modified is not None:
                return not_modified
            self._set_revision_headers(response, app)
            # Resolve against the snapshot directly: Nacho.get() deep-copies its
            # result, so an identity-sentinel passed to it would never compare
            # equal — get_nested_value preserves the sentinel by identity.
            missing = object()
            value = get_nested_value(app.config.get_all(), path, missing)
            if value is missing:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Configuration path {path!r} not found",
                )
            return {"path": path, "value": value}

        @self.app.put("/api/apps/{app_name}/config/{path:path}")
        def set_path(
            app_name: str,
            path: str,
            request: PathUpdateRequest,
        ) -> Dict[str, Any]:
            self._check_writable()
            try:
                value = self._convert_value(request.value, request.type)
                changed = self.manager.set_config_path(
                    app_name,
                    path,
                    value,
                    expected_revision=request.revision,
                )
                app = self._get_app(app_name)
            except KeyError:
                raise self._not_found(app_name) from None
            except RevisionConflictError as exc:
                raise self._conflict(exc) from exc
            except (ValueError, TypeError, ValidationError) as exc:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
                ) from exc
            return {
                "message": (
                    "Configuration path updated"
                    if changed
                    else "Configuration path unchanged (value already set)"
                ),
                "path": path,
                "value": value,
                "changed": changed,
                "revision": app.revision,
            }

        @self.app.delete("/api/apps/{app_name}/config/{path:path}")
        def delete_path(
            app_name: str,
            path: str,
            revision: Optional[int] = None,
        ) -> Dict[str, Any]:
            self._check_writable()
            try:
                deleted = self.manager.delete_config_path(
                    app_name,
                    path,
                    expected_revision=revision,
                )
                if not deleted:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail=f"Configuration path {path!r} not found",
                    )
                app = self._get_app(app_name)
            except KeyError:
                raise self._not_found(app_name) from None
            except RevisionConflictError as exc:
                raise self._conflict(exc) from exc
            except ValidationError as exc:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
                ) from exc
            return {"message": f"Configuration path {path!r} deleted", "revision": app.revision}

        @self.app.get("/api/apps/{app_name}/history")
        def list_history(app_name: str) -> Dict[str, Any]:
            try:
                return {"data": self.manager.list_history(app_name)}
            except KeyError:
                raise self._not_found(app_name) from None

        @self.app.get("/api/apps/{app_name}/history/{revision}")
        def get_history_snapshot(app_name: str, revision: int) -> Dict[str, Any]:
            try:
                snapshot = self.manager.get_history_snapshot(app_name, revision)
            except KeyError:
                raise self._not_found(app_name) from None
            if snapshot is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Revision {revision} of app {app_name!r} is not in history",
                )
            return {"data": snapshot}

        @self.app.post("/api/apps/{app_name}/rollback")
        def rollback(app_name: str, request: RollbackRequest) -> Dict[str, Any]:
            self._check_writable()
            try:
                app = self.manager.rollback(
                    app_name,
                    request.revision,
                    expected_revision=request.expected_revision,
                )
            except KeyError:
                raise self._not_found(app_name) from None
            except LookupError as exc:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
            except RevisionConflictError as exc:
                raise self._conflict(exc) from exc
            except ValidationError as exc:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
                ) from exc
            return {
                "message": f"Rolled back to revision {request.revision}",
                "revision": app.revision,
                "data": app.config.get_all(),
            }

        @self.app.post("/api/apps/{app_name}/validate")
        def validate_config(app_name: str, request: ConfigRequest) -> Dict[str, Any]:
            app = self._get_app(app_name)
            try:
                config_data = self._parse_config(request.data, request.format)
            except InvalidConfigDataError as exc:
                # "data" is always the submitted payload (parsed), never the
                # app's current config; None signals it could not be parsed.
                return {"valid": False, "errors": [str(exc)], "data": None}
            errors = app.config.check(config_data)
            return {"valid": not errors, "errors": errors, "data": config_data}

        @self.app.websocket("/ws/{app_name}")
        async def watch(websocket: WebSocket, app_name: str) -> None:
            if self.auth and not self.auth.verify_websocket(websocket):
                await websocket.close(code=1008, reason="Unauthorized")
                return
            app = self.manager.get(app_name)
            if app is None:
                await websocket.close(code=4004, reason=f"App {app_name!r} not found")
                return

            await app.hub.connect(websocket)
            try:
                await websocket.send_json(
                    {
                        "type": "initial_config",
                        "app": app.name,
                        "revision": app.revision,
                        "data": app.config.get_all(),
                    }
                )
                while True:
                    # receive() (not receive_text) so a binary frame is
                    # ignored instead of killing the connection.
                    message = await websocket.receive()
                    if message.get("type") == "websocket.disconnect":
                        break
            except WebSocketDisconnect:
                pass
            finally:
                app.hub.disconnect(websocket)

    def _parse_config(self, data: Any, fmt: str) -> Dict[str, Any]:
        if isinstance(data, dict):
            return data
        if isinstance(data, str) and len(data) > _MAX_PAYLOAD_BYTES:
            raise InvalidConfigDataError(
                f"Encoded payload exceeds {_MAX_PAYLOAD_BYTES // (1024 * 1024)} MiB"
            )
        try:
            parsed = load_string(data, fmt)
        except Exception as exc:
            raise InvalidConfigDataError(f"Invalid {fmt} config: {exc}") from exc
        if not isinstance(parsed, dict):
            raise InvalidConfigDataError("Configuration payload must decode to an object")
        return parsed

    def _parse_schema(self, data: Optional[Any], fmt: str) -> Optional[Dict[str, Any]]:
        if data is None:
            return None
        parsed = self._parse_config(data, fmt)
        return parsed

    def _convert_value(self, value: Any, type_hint: str) -> Any:
        if type_hint == "raw":
            return value
        if type_hint == "str":
            return str(value)
        if type_hint == "int":
            return int(value)
        if type_hint == "float":
            return float(value)
        if type_hint == "bool":
            if isinstance(value, bool):
                return value
            if isinstance(value, str):
                lowered = value.lower()
                if lowered in {"true", "yes", "1", "on"}:
                    return True
                if lowered in {"false", "no", "0", "off"}:
                    return False
            raise ValueError(f"Cannot convert {value!r} to bool")
        if type_hint in {"list", "dict"} and isinstance(value, str):
            value = json.loads(value)
        if type_hint == "list":
            return list(value)
        if type_hint == "dict":
            return dict(value)
        raise ValueError(f"Unsupported value type: {type_hint}")

    def _allow_cors_credentials(self) -> bool:
        return "*" not in self.cors_origins

    def _get_app(self, name: str) -> ConfigApp:
        app = self.manager.get(name)
        if app is None:
            raise self._not_found(name)
        return app

    def _not_found(self, name: str) -> HTTPException:
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"App {name!r} not found",
        )

    def _conflict(self, exc: RevisionConflictError) -> HTTPException:
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "revision_conflict",
                "expected": exc.expected,
                "actual": exc.actual,
            },
        )

    def _set_revision_headers(self, response: Response, app: ConfigApp) -> None:
        revision = str(app.revision)
        response.headers["ETag"] = f'"{revision}"'
        response.headers["X-Nacho-Revision"] = revision

    def _not_modified(self, request: Request, app: ConfigApp) -> Optional[Response]:
        """304 response when If-None-Match already names the current revision.

        Lets pollers re-check cheaply: the config body is only sent when the
        revision actually moved.
        """
        header = request.headers.get("if-none-match")
        if not header:
            return None
        tags = {tag.strip() for tag in header.split(",")}
        tags |= {tag[2:] for tag in tags if tag.startswith("W/")}
        if "*" not in tags and f'"{app.revision}"' not in tags:
            return None
        response = Response(status_code=status.HTTP_304_NOT_MODIFIED)
        self._set_revision_headers(response, app)
        return response

    def _check_writable(self) -> None:
        if self.read_only:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Server is in read-only mode",
            )

    def run(  # pragma: no cover - thin uvicorn wrapper, exercised via the CLI
        self, host: str = "127.0.0.1", port: int = 8000, reload: bool = False
    ) -> None:
        """Serve the API. Binds to loopback by default; pass host="0.0.0.0"
        explicitly (ideally with an api_key) to accept remote connections."""
        config = uvicorn.Config(app=self.app, host=host, port=port, reload=reload)
        uvicorn.Server(config).run()
