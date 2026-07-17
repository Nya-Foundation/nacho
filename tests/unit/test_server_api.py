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
        # API docs are deliberately public — GET / advertises them.
        assert client.get("/docs").status_code == 200
        assert client.get("/openapi.json").status_code == 200
        response = client.get("/api/apps/svc/config")
        assert response.status_code == 401
        assert response.headers["WWW-Authenticate"] == "Bearer"

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


def test_replace_app_ignores_body_name():
    """PUT replaces content only; renaming is PATCH /metadata's job."""
    orchestrator = NachoOrchestrator(apps={"svc": Nacho({"x": 1}, events=True)})

    with TestClient(orchestrator.app) as client:
        response = client.put(
            "/api/apps/svc",
            json={"name": "other", "data": json.dumps({"x": 3}), "format": "json"},
        )
        assert response.status_code == 200
        assert client.get("/api/apps/svc/config").json() == {"x": 3}
        assert client.get("/api/apps/other").status_code == 404


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

        response = client.put("/api/apps/svc/config/x", json={"value": 2, "revision": 1})
        assert response.status_code == 200
        assert response.json()["revision"] == 2

        response = client.put("/api/apps/svc/config/x", json={"value": 3, "revision": 1})
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
        assert client.post("/api/convert", json={"data": {}, "to": "yaml"}).status_code == 401
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

        assert client.get("/api/apps/with/schema").json()["data"] == schema
        assert client.get("/api/apps/without/schema").json()["data"] is None


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
        assert client.get("/api/apps/svc/schema").json()["data"] == schema
        assert client.get("/api/apps/svc").json()["data"]["schema"] is True


def test_update_schema_rejects_schema_the_current_config_violates():
    orchestrator = NachoOrchestrator(apps={"svc": Nacho({"port": "not-a-number"}, events=True)})
    schema = {"type": "object", "properties": {"port": {"type": "integer"}}}

    with TestClient(orchestrator.app) as client:
        response = client.put("/api/apps/svc/schema", json={"schema": schema})
        assert response.status_code == 400
        assert "port" in response.json()["detail"]
        # The schema was not applied.
        assert client.get("/api/apps/svc/schema").json()["data"] is None


def test_update_schema_with_null_clears_schema():
    schema = {"type": "object", "properties": {"port": {"type": "integer"}}}
    orchestrator = NachoOrchestrator()

    with TestClient(orchestrator.app) as client:
        client.post("/api/apps", json={"name": "svc", "data": {"port": 1}, "schema": schema})
        response = client.put("/api/apps/svc/schema", json={"schema": None})
        assert response.status_code == 200
        assert response.json()["schema"] is None
        assert client.get("/api/apps/svc/schema").json()["data"] is None


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


# ---------------------------------------------------------------------------
# App listing / info / deletion
# ---------------------------------------------------------------------------
def test_list_apps_returns_every_app():
    orchestrator = NachoOrchestrator(
        apps={"a": Nacho({"x": 1}, events=True), "b": Nacho({"y": 2}, events=True)}
    )
    with TestClient(orchestrator.app) as client:
        apps = client.get("/api/apps").json()["data"]
        assert set(apps) == {"a", "b"}


def test_get_app_info_and_missing_app_404():
    orchestrator = NachoOrchestrator(apps={"svc": Nacho({"x": 1}, events=True)})
    with TestClient(orchestrator.app) as client:
        assert client.get("/api/apps/svc").json()["data"]["name"] == "svc"
        assert client.get("/api/apps/ghost").status_code == 404


def test_delete_app_removes_it_and_404_when_absent():
    orchestrator = NachoOrchestrator(apps={"svc": Nacho({"x": 1}, events=True)})
    with TestClient(orchestrator.app) as client:
        assert client.delete("/api/apps/svc").status_code == 200
        assert client.get("/api/apps/svc").status_code == 404
        assert client.delete("/api/apps/svc").status_code == 404


def test_delete_app_blocked_in_read_only_mode():
    orchestrator = NachoOrchestrator(
        apps={"svc": Nacho({"x": 1}, events=True)}, read_only=True
    )
    with TestClient(orchestrator.app) as client:
        assert client.delete("/api/apps/svc").status_code == 403


# ---------------------------------------------------------------------------
# Metadata / replace
# ---------------------------------------------------------------------------
def test_update_metadata_renames_and_describes():
    orchestrator = NachoOrchestrator(apps={"svc": Nacho({"x": 1}, events=True)})
    with TestClient(orchestrator.app) as client:
        response = client.patch(
            "/api/apps/svc/metadata", json={"name": "renamed", "description": "now described"}
        )
        assert response.status_code == 200
        assert response.json()["app"]["name"] == "renamed"
        assert client.get("/api/apps/renamed").json()["data"]["description"] == "now described"


def test_update_metadata_missing_app_404():
    orchestrator = NachoOrchestrator()
    with TestClient(orchestrator.app) as client:
        assert client.patch("/api/apps/ghost/metadata", json={"name": "x"}).status_code == 404


def test_update_metadata_name_collision_400():
    orchestrator = NachoOrchestrator(
        apps={"a": Nacho({"x": 1}, events=True), "b": Nacho({"y": 2}, events=True)}
    )
    with TestClient(orchestrator.app) as client:
        assert client.patch("/api/apps/a/metadata", json={"name": "b"}).status_code == 400


def test_replace_missing_app_returns_404():
    orchestrator = NachoOrchestrator()
    with TestClient(orchestrator.app) as client:
        response = client.put("/api/apps/ghost", json={"name": "ghost", "data": {"x": 1}})
        assert response.status_code == 404


def test_replace_config_missing_app_returns_404():
    orchestrator = NachoOrchestrator()
    with TestClient(orchestrator.app) as client:
        assert client.put("/api/apps/ghost/config", json={"data": {"x": 1}}).status_code == 404


# ---------------------------------------------------------------------------
# Config path endpoints
# ---------------------------------------------------------------------------
def test_get_path_missing_returns_404():
    orchestrator = NachoOrchestrator(apps={"svc": Nacho({"x": 1}, events=True)})
    with TestClient(orchestrator.app) as client:
        assert client.get("/api/apps/svc/config/nope").status_code == 404


def test_set_path_missing_app_returns_404():
    orchestrator = NachoOrchestrator()
    with TestClient(orchestrator.app) as client:
        assert client.put("/api/apps/ghost/config/x", json={"value": 1}).status_code == 404


def test_delete_path_removes_key():
    orchestrator = NachoOrchestrator(apps={"svc": Nacho({"a": 1, "b": 2}, events=True)})
    with TestClient(orchestrator.app) as client:
        response = client.delete("/api/apps/svc/config/a")
        assert response.status_code == 200
        assert client.get("/api/apps/svc/config").json() == {"b": 2}


def test_delete_path_missing_key_404():
    orchestrator = NachoOrchestrator(apps={"svc": Nacho({"a": 1}, events=True)})
    with TestClient(orchestrator.app) as client:
        assert client.delete("/api/apps/svc/config/ghost").status_code == 404


def test_delete_path_missing_app_404():
    orchestrator = NachoOrchestrator()
    with TestClient(orchestrator.app) as client:
        assert client.delete("/api/apps/ghost/config/x").status_code == 404


# ---------------------------------------------------------------------------
# Validate endpoint
# ---------------------------------------------------------------------------
def test_validate_endpoint_reports_valid_and_invalid():
    schema = {"type": "object", "properties": {"port": {"type": "integer"}},
              "required": ["port"]}
    orchestrator = NachoOrchestrator()
    with TestClient(orchestrator.app) as client:
        client.post("/api/apps", json={"name": "svc", "data": {"port": 1}, "schema": schema})

        ok = client.post("/api/apps/svc/validate", json={"data": {"port": 9}})
        assert ok.json()["valid"] is True

        bad = client.post("/api/apps/svc/validate", json={"data": {"port": "x"}})
        assert bad.json()["valid"] is False and bad.json()["errors"]


def test_validate_endpoint_reports_unparseable_payload():
    orchestrator = NachoOrchestrator(apps={"svc": Nacho({"x": 1}, events=True)})
    with TestClient(orchestrator.app) as client:
        response = client.post(
            "/api/apps/svc/validate", json={"data": "{not json", "format": "json"}
        )
        assert response.status_code == 200
        assert response.json()["valid"] is False


# ---------------------------------------------------------------------------
# WebSocket / schema edge cases
# ---------------------------------------------------------------------------
def test_websocket_unknown_app_is_closed():
    orchestrator = NachoOrchestrator()
    with TestClient(orchestrator.app) as client:
        with pytest.raises(WebSocketDisconnect) as exc:
            with client.websocket_connect("/ws/ghost"):
                pass
        assert exc.value.code == 4004


def test_get_schema_missing_app_404():
    orchestrator = NachoOrchestrator()
    with TestClient(orchestrator.app) as client:
        assert client.get("/api/apps/ghost/schema").status_code == 404


# ---------------------------------------------------------------------------
# Value coercion / payload parsing
# ---------------------------------------------------------------------------
def test_set_path_coerces_typed_values():
    orchestrator = NachoOrchestrator(apps={"svc": Nacho({}, events=True)})
    with TestClient(orchestrator.app) as client:
        cases = [
            ("s", "42", "str", "42"),
            ("i", "42", "int", 42),
            ("f", "1.5", "float", 1.5),
            ("b", "no", "bool", False),
            ("b2", True, "bool", True),
            ("lst", "[1, 2]", "list", [1, 2]),
            ("dct", '{"k": 1}', "dict", {"k": 1}),
        ]
        for key, value, type_hint, expected in cases:
            response = client.put(
                f"/api/apps/svc/config/{key}", json={"value": value, "type": type_hint}
            )
            assert response.status_code == 200, (key, response.text)
            assert response.json()["value"] == expected


def test_set_path_rejects_bad_conversion():
    orchestrator = NachoOrchestrator(apps={"svc": Nacho({}, events=True)})
    with TestClient(orchestrator.app) as client:
        response = client.put(
            "/api/apps/svc/config/n", json={"value": "not-an-int", "type": "int"}
        )
        assert response.status_code == 400


def test_create_app_rejects_non_object_payload():
    orchestrator = NachoOrchestrator()
    with TestClient(orchestrator.app) as client:
        response = client.post(
            "/api/apps", json={"name": "svc", "data": "[1, 2, 3]", "format": "json"}
        )
        assert response.status_code == 400


# ---------------------------------------------------------------------------
# Revision conflicts on the remaining write endpoints
# ---------------------------------------------------------------------------
def test_replace_app_revision_conflict():
    orchestrator = NachoOrchestrator(apps={"svc": Nacho({"x": 1}, events=True)})
    with TestClient(orchestrator.app) as client:
        response = client.put(
            "/api/apps/svc", json={"name": "svc", "data": {"x": 2}, "revision": 99}
        )
        assert response.status_code == 409


def test_metadata_revision_conflict():
    orchestrator = NachoOrchestrator(apps={"svc": Nacho({"x": 1}, events=True)})
    with TestClient(orchestrator.app) as client:
        response = client.patch(
            "/api/apps/svc/metadata", json={"description": "new", "revision": 99}
        )
        assert response.status_code == 409


def test_replace_config_revision_conflict():
    orchestrator = NachoOrchestrator(apps={"svc": Nacho({"x": 1}, events=True)})
    with TestClient(orchestrator.app) as client:
        response = client.put(
            "/api/apps/svc/config", json={"data": {"x": 2}, "revision": 99}
        )
        assert response.status_code == 409


def test_replace_schema_missing_app_404():
    orchestrator = NachoOrchestrator()
    with TestClient(orchestrator.app) as client:
        assert client.put(
            "/api/apps/ghost/schema", json={"schema": {"type": "object"}}
        ).status_code == 404


def test_set_path_bool_rejects_unrecognized_string():
    orchestrator = NachoOrchestrator(apps={"svc": Nacho({}, events=True)})
    with TestClient(orchestrator.app) as client:
        response = client.put(
            "/api/apps/svc/config/flag", json={"value": "maybe", "type": "bool"}
        )
        assert response.status_code == 400


def test_replace_config_rejects_schema_violation():
    schema = {"type": "object", "properties": {"port": {"type": "integer"}},
              "required": ["port"]}
    orchestrator = NachoOrchestrator()
    with TestClient(orchestrator.app) as client:
        client.post("/api/apps", json={"name": "svc", "data": {"port": 1}, "schema": schema})
        response = client.put("/api/apps/svc/config", json={"data": {"port": "bad"}})
        assert response.status_code == 400


def test_delete_path_revision_conflict():
    orchestrator = NachoOrchestrator(apps={"svc": Nacho({"a": 1, "b": 2}, events=True)})
    with TestClient(orchestrator.app) as client:
        response = client.delete("/api/apps/svc/config/a", params={"revision": 99})
        assert response.status_code == 409


def test_delete_path_rejecting_schema_violation():
    schema = {"type": "object", "properties": {"port": {"type": "integer"}},
              "required": ["port"]}
    orchestrator = NachoOrchestrator()
    with TestClient(orchestrator.app) as client:
        client.post("/api/apps", json={"name": "svc", "data": {"port": 1}, "schema": schema})
        # deleting the required key would make the config invalid
        response = client.delete("/api/apps/svc/config/port")
        assert response.status_code == 400


def test_single_nacho_instance_is_wrapped_as_default_app():
    orchestrator = NachoOrchestrator(apps=Nacho({"x": 1}, events=True))
    with TestClient(orchestrator.app) as client:
        assert client.get("/api/apps/default/config").json() == {"x": 1}


def test_orchestrator_mounted_under_subpath_serves_every_route():
    """Health, UI, API, and WebSocket all stay reachable when mounted at /config."""
    from fastapi import FastAPI

    parent = FastAPI()
    orchestrator = NachoOrchestrator(apps={"svc": Nacho({"x": 1}, events=True)})
    parent.mount("/config", orchestrator.app)

    with TestClient(parent) as client:
        assert client.get("/config/health").json()["status"] == "ok"
        ui = client.get("/config/ui")
        assert ui.status_code == 200 and "Nacho" in ui.text
        assert client.get("/config/api/apps/svc/config").json() == {"x": 1}
        with client.websocket_connect("/config/ws/svc") as ws:
            assert ws.receive_json()["type"] == "initial_config"
