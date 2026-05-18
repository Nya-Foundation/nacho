"""Tests for the API-first Nacho server."""

import json

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from nacho import Nacho
from nacho.server.app import NachoOrchestrator


def test_api_reads_and_updates_config_path():
    orchestrator = NachoOrchestrator(
        apps={"svc": Nacho({"feature": {"enabled": False}}, events=True)}
    )

    with TestClient(orchestrator.app) as client:
        response = client.get("/api/apps/svc/config")
        assert response.status_code == 200
        assert response.json()["feature"]["enabled"] is False

        response = client.put(
            "/api/apps/svc/config/feature.enabled",
            json={"value": "true", "type": "bool"},
        )
        assert response.status_code == 200
        assert response.json()["value"] is True

        response = client.get("/api/apps/svc/config/feature.enabled")
        assert response.status_code == 200
        assert response.json()["value"] is True


def test_create_app_rejects_invalid_schema_backed_config():
    schema = {
        "type": "object",
        "properties": {"port": {"type": "integer"}},
        "required": ["port"],
    }
    orchestrator = NachoOrchestrator()

    with TestClient(orchestrator.app) as client:
        response = client.post(
            "/api/apps",
            json={
                "name": "bad",
                "data": json.dumps({"port": "nope"}),
                "format": "json",
                "schema": json.dumps(schema),
            },
        )
        assert response.status_code == 400
        assert "port" in response.json()["detail"]


def test_api_accepts_native_json_config_and_schema_payloads():
    schema = {
        "type": "object",
        "properties": {"port": {"type": "integer"}},
        "required": ["port"],
    }
    orchestrator = NachoOrchestrator()

    with TestClient(orchestrator.app) as client:
        response = client.post(
            "/api/apps",
            json={
                "name": "native",
                "data": {"port": 8080},
                "schema": schema,
            },
        )
        assert response.status_code == 201

        response = client.put(
            "/api/apps/native/config",
            json={"data": {"port": 9090}, "revision": 1},
        )
        assert response.status_code == 200
        assert response.json()["data"] == {"port": 9090}
        assert response.json()["revision"] == 2


def test_auth_protects_api_routes():
    orchestrator = NachoOrchestrator(
        apps={"svc": Nacho({"x": 1}, events=True)},
        api_key="secret",
    )

    with TestClient(orchestrator.app) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/docs").status_code == 403
        assert client.get("/openapi.json").status_code == 403
        assert client.get("/api/apps/svc/config").status_code == 403

        response = client.get(
            "/api/apps/svc/config",
            headers={"Authorization": "Bearer secret"},
        )
        assert response.status_code == 200
        assert response.json() == {"x": 1}


def test_websocket_auth_rejects_query_string_api_key():
    orchestrator = NachoOrchestrator(
        apps={"svc": Nacho({"x": 1}, events=True)},
        api_key="secret",
    )

    with TestClient(orchestrator.app) as client:
        with pytest.raises(WebSocketDisconnect) as exc:
            with client.websocket_connect("/ws/svc?api_key=secret"):
                pass
        assert exc.value.code == 1008

        with client.websocket_connect(
            "/ws/svc",
            headers={"Authorization": "Bearer secret"},
        ) as websocket:
            assert websocket.receive_json()["type"] == "initial_config"


def test_default_cors_does_not_allow_credentials_with_wildcard_origin():
    orchestrator = NachoOrchestrator()

    with TestClient(orchestrator.app) as client:
        response = client.options(
            "/api/apps",
            headers={
                "Origin": "https://example.com",
                "Access-Control-Request-Method": "GET",
            },
        )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "*"
    assert "access-control-allow-credentials" not in response.headers


def test_explicit_cors_origin_allows_credentials():
    orchestrator = NachoOrchestrator(cors_origins=["https://example.com"])

    with TestClient(orchestrator.app) as client:
        response = client.options(
            "/api/apps",
            headers={
                "Origin": "https://example.com",
                "Access-Control-Request-Method": "GET",
            },
        )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "https://example.com"
    assert response.headers["access-control-allow-credentials"] == "true"


def test_read_only_rejects_writes():
    orchestrator = NachoOrchestrator(
        apps={"svc": Nacho({"x": 1}, events=True)},
        read_only=True,
    )

    with TestClient(orchestrator.app) as client:
        response = client.put("/api/apps/svc/config/x", json={"value": 2})
        assert response.status_code == 403
        assert client.get("/api/apps/svc/config").json() == {"x": 1}


def test_replace_app_name_conflict_preserves_original():
    orchestrator = NachoOrchestrator(
        apps={
            "svc": Nacho({"x": 1}, events=True),
            "taken": Nacho({"x": 2}, events=True),
        }
    )

    with TestClient(orchestrator.app) as client:
        response = client.put(
            "/api/apps/svc",
            json={"name": "taken", "data": json.dumps({"x": 3}), "format": "json"},
        )
        assert response.status_code == 400
        assert client.get("/api/apps/svc/config").json() == {"x": 1}


def test_replace_app_preserves_managed_objects_and_handlers():
    config = Nacho({"x": 1}, events=True)
    fired = []

    @config.on_change("x")
    def on_x_change(path, old_value, new_value, **kwargs):
        fired.append((path, old_value, new_value))

    orchestrator = NachoOrchestrator(apps={"svc": config})
    original_app = orchestrator.manager.get("svc")

    with TestClient(orchestrator.app) as client:
        response = client.put(
            "/api/apps/svc",
            json={"name": "svc", "data": {"x": 2}},
        )
        assert response.status_code == 200
        assert response.json()["app"]["revision"] == 2
        assert orchestrator.manager.get("svc") is original_app
        assert orchestrator.manager.get("svc").config is config
        assert fired == [("x", 1, 2)]

        response = client.put("/api/apps/svc/config/x", json={"value": 3, "revision": 2})
        assert response.status_code == 200
        assert response.json()["revision"] == 3
        assert fired[-1] == ("x", 2, 3)


def test_data_dir_persists_api_created_apps(tmp_path):
    data_dir = tmp_path / "apps"
    first = NachoOrchestrator(data_dir=data_dir)

    with TestClient(first.app) as client:
        response = client.post(
            "/api/apps",
            json={"name": "svc", "data": json.dumps({"x": 1}), "format": "json"},
        )
        assert response.status_code == 201

    second = NachoOrchestrator(data_dir=data_dir)
    with TestClient(second.app) as client:
        response = client.get("/api/apps/svc/config")
        assert response.status_code == 200
        assert response.json() == {"x": 1}


def test_data_dir_persists_path_updates_and_revisions(tmp_path):
    data_dir = tmp_path / "apps"
    first = NachoOrchestrator(data_dir=data_dir)

    with TestClient(first.app) as client:
        response = client.post(
            "/api/apps",
            json={"name": "svc", "data": json.dumps({"x": 1}), "format": "json"},
        )
        assert response.status_code == 201

        response = client.put("/api/apps/svc/config/x", json={"value": 1})
        assert response.status_code == 200
        assert client.get("/api/apps/svc").json()["data"]["revision"] == 1

        response = client.put("/api/apps/svc/config/x", json={"value": 2})
        assert response.status_code == 200
        assert client.get("/api/apps/svc").json()["data"]["revision"] == 2

    second = NachoOrchestrator(data_dir=data_dir)
    with TestClient(second.app) as client:
        assert client.get("/api/apps/svc/config").json() == {"x": 2}
        assert client.get("/api/apps/svc").json()["data"]["revision"] == 2


def test_write_with_stale_revision_returns_conflict():
    orchestrator = NachoOrchestrator(apps={"svc": Nacho({"x": 1}, events=True)})

    with TestClient(orchestrator.app) as client:
        response = client.get("/api/apps/svc/config")
        assert response.status_code == 200
        assert response.headers["etag"] == '"1"'
        assert response.headers["x-nacho-revision"] == "1"

        response = client.put(
            "/api/apps/svc/config/x",
            json={"value": 2},
            headers={"If-Match": '"1"'},
        )
        assert response.status_code == 200
        assert response.json()["revision"] == 2

        response = client.put(
            "/api/apps/svc/config/x",
            json={"value": 3},
            headers={"If-Match": '"1"'},
        )
        assert response.status_code == 409
        assert response.json()["detail"]["actual"] == 2
        assert client.get("/api/apps/svc/config").json() == {"x": 2}


def test_write_with_body_revision_returns_conflict():
    orchestrator = NachoOrchestrator(apps={"svc": Nacho({"x": 1}, events=True)})

    with TestClient(orchestrator.app) as client:
        assert (
            client.put("/api/apps/svc/config/x", json={"value": 2, "revision": 1}).status_code
            == 200
        )

        response = client.put("/api/apps/svc/config/x", json={"value": 3, "revision": 1})
        assert response.status_code == 409
        assert client.get("/api/apps/svc/config").json() == {"x": 2}


def test_convert_endpoint_round_trips_formats():
    orchestrator = NachoOrchestrator()

    with TestClient(orchestrator.app) as client:
        payload = {"database": {"host": "localhost", "port": 5432}}

        to_yaml = client.post("/api/convert", json={"data": payload, "from": "json", "to": "yaml"})
        assert to_yaml.status_code == 200
        assert to_yaml.json()["format"] == "yaml"
        assert "host: localhost" in to_yaml.json()["data"]

        back = client.post(
            "/api/convert",
            json={"data": to_yaml.json()["data"], "from": "yaml", "to": "json"},
        )
        assert back.status_code == 200
        assert json.loads(back.json()["data"]) == payload

        to_toml = client.post("/api/convert", json={"data": payload, "from": "json", "to": "toml"})
        assert to_toml.status_code == 200
        assert "[database]" in to_toml.json()["data"]


def test_convert_endpoint_rejects_invalid_payload():
    orchestrator = NachoOrchestrator()

    with TestClient(orchestrator.app) as client:
        response = client.post(
            "/api/convert",
            json={"data": "not: : valid: yaml:", "from": "yaml", "to": "json"},
        )
        assert response.status_code == 400


def test_convert_endpoint_requires_auth():
    orchestrator = NachoOrchestrator(api_key="secret")

    with TestClient(orchestrator.app) as client:
        assert client.post("/api/convert", json={"data": {}, "to": "yaml"}).status_code == 403
        response = client.post(
            "/api/convert",
            json={"data": {"a": 1}, "to": "yaml"},
            headers={"Authorization": "Bearer secret"},
        )
        assert response.status_code == 200


def test_create_app_accepts_yaml_payload():
    orchestrator = NachoOrchestrator()

    with TestClient(orchestrator.app) as client:
        response = client.post(
            "/api/apps",
            json={"name": "svc", "data": "feature:\n  enabled: true\n", "format": "yaml"},
        )
        assert response.status_code == 201
        assert client.get("/api/apps/svc/config").json() == {"feature": {"enabled": True}}


def test_health_reports_auth_requirement():
    open_server = NachoOrchestrator()
    secured = NachoOrchestrator(api_key="secret")

    with TestClient(open_server.app) as client:
        assert client.get("/health").json()["auth_required"] is False
    with TestClient(secured.app) as client:
        assert client.get("/health").json()["auth_required"] is True


def test_ui_is_served_and_public_even_with_auth():
    orchestrator = NachoOrchestrator(api_key="secret")

    with TestClient(orchestrator.app) as client:
        response = client.get("/ui")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/html")
        assert "Nacho" in response.text


def test_get_schema_returns_app_schema():
    schema = {"type": "object", "properties": {"port": {"type": "integer"}}}
    orchestrator = NachoOrchestrator()

    with TestClient(orchestrator.app) as client:
        client.post("/api/apps", json={"name": "with", "data": {"port": 1}, "schema": schema})
        client.post("/api/apps", json={"name": "without", "data": {"port": 1}})

        assert client.get("/api/apps/with/schema").json()["data"]["schema"] == schema
        assert client.get("/api/apps/without/schema").json()["data"]["schema"] is None


def test_update_schema_sets_schema_after_creation():
    schema = {
        "type": "object",
        "properties": {"port": {"type": "integer"}},
        "required": ["port"],
    }
    orchestrator = NachoOrchestrator(apps={"svc": Nacho({"port": 8080}, events=True)})

    with TestClient(orchestrator.app) as client:
        response = client.put("/api/apps/svc/schema", json={"schema": schema, "revision": 1})
        assert response.status_code == 200
        assert response.json()["schema"] == schema
        assert response.json()["revision"] == 2
        assert client.get("/api/apps/svc/schema").json()["data"]["schema"] == schema
        assert client.get("/api/apps/svc").json()["data"]["schema"] is True


def test_update_schema_rejects_schema_the_current_config_violates():
    orchestrator = NachoOrchestrator(apps={"svc": Nacho({"port": "not-a-number"}, events=True)})
    schema = {"type": "object", "properties": {"port": {"type": "integer"}}}

    with TestClient(orchestrator.app) as client:
        response = client.put("/api/apps/svc/schema", json={"schema": schema})
        assert response.status_code == 400
        assert "port" in response.json()["detail"]
        # The schema was not applied.
        assert client.get("/api/apps/svc/schema").json()["data"]["schema"] is None


def test_update_schema_with_null_clears_schema():
    schema = {"type": "object", "properties": {"port": {"type": "integer"}}}
    orchestrator = NachoOrchestrator()

    with TestClient(orchestrator.app) as client:
        client.post("/api/apps", json={"name": "svc", "data": {"port": 1}, "schema": schema})
        response = client.put("/api/apps/svc/schema", json={"schema": None})
        assert response.status_code == 200
        assert response.json()["schema"] is None
        assert client.get("/api/apps/svc/schema").json()["data"]["schema"] is None


def test_update_schema_honours_revision_conflict():
    orchestrator = NachoOrchestrator(apps={"svc": Nacho({"port": 1}, events=True)})
    schema = {"type": "object"}

    with TestClient(orchestrator.app) as client:
        response = client.put("/api/apps/svc/schema", json={"schema": schema, "revision": 99})
        assert response.status_code == 409
        assert response.json()["detail"]["actual"] == 1


def test_update_schema_rejected_in_read_only_mode():
    orchestrator = NachoOrchestrator(
        apps={"svc": Nacho({"port": 1}, events=True)},
        read_only=True,
    )

    with TestClient(orchestrator.app) as client:
        response = client.put("/api/apps/svc/schema", json={"schema": {"type": "object"}})
        assert response.status_code == 403


def test_websocket_update_uses_committed_revision():
    orchestrator = NachoOrchestrator(apps={"svc": Nacho({"x": 1}, events=True)})

    with TestClient(orchestrator.app) as client:
        with client.websocket_connect("/ws/svc") as websocket:
            initial = websocket.receive_json()
            assert initial["revision"] == 1

            response = client.put("/api/apps/svc/config/x", json={"value": 2})
            assert response.status_code == 200
            assert response.json()["revision"] == 2

            update = websocket.receive_json()
            assert update["type"] == "update"
            assert update["revision"] == 2
            assert update["data"] == {"x": 2}
