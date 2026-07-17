"""Tests for HistoryStore and AppManager rollback semantics."""

import pytest

from nacho.server.runtime import AppManager, HistoryStore, RevisionConflictError


def _snapshot(name="svc", revision=1, config=None, schema=None):
    return {
        "name": name,
        "description": None,
        "revision": revision,
        "created_at": "2026-07-17T00:00:00+00:00",
        "updated_at": f"2026-07-17T00:00:{revision:02d}+00:00",
        "schema": schema,
        "config": config if config is not None else {"n": revision},
    }


# ---------------------------------------------------------------------------
# HistoryStore — both backends
# ---------------------------------------------------------------------------
@pytest.fixture(params=["memory", "disk"])
def store(request, tmp_path):
    data_dir = tmp_path if request.param == "disk" else None
    return HistoryStore(data_dir, limit=3)


def test_record_list_get_roundtrip(store):
    for rev in (1, 2, 3):
        store.record(_snapshot(revision=rev))
    entries = store.list("svc")
    assert [e["revision"] for e in entries] == [3, 2, 1]  # newest first
    assert entries[0]["config_count"] == 1
    assert store.get("svc", 2)["config"] == {"n": 2}
    assert store.get("svc", 99) is None


def test_prunes_to_limit(store):
    for rev in range(1, 6):
        store.record(_snapshot(revision=rev))
    assert [e["revision"] for e in store.list("svc")] == [5, 4, 3]
    assert store.get("svc", 1) is None


def test_limit_zero_disables_history(tmp_path):
    store = HistoryStore(tmp_path, limit=0)
    store.record(_snapshot())
    assert store.list("svc") == []
    assert not (tmp_path / "history").exists()


def test_rename_moves_history(store):
    store.record(_snapshot(revision=1))
    store.rename("svc", "renamed")
    assert store.list("svc") == []
    assert [e["revision"] for e in store.list("renamed")] == [1]


def test_delete_clears_history(store):
    store.record(_snapshot(revision=1))
    store.delete("svc")
    assert store.list("svc") == []


def test_apps_do_not_share_history(store):
    store.record(_snapshot(name="a", revision=1))
    store.record(_snapshot(name="b", revision=1, config={"other": True}))
    assert store.get("a", 1)["config"] == {"n": 1}
    assert store.get("b", 1)["config"] == {"other": True}


# ---------------------------------------------------------------------------
# AppManager — recording and rollback
# ---------------------------------------------------------------------------
@pytest.fixture(params=["memory", "disk"])
def manager(request, tmp_path):
    data_dir = tmp_path if request.param == "disk" else None
    return AppManager(data_dir=data_dir, history_limit=10)


def test_every_write_records_a_snapshot(manager):
    manager.create("svc", config_data={"x": 1})
    manager.replace_config("svc", {"x": 2})
    manager.set_config_path("svc", "y", 3)
    revisions = [e["revision"] for e in manager.list_history("svc")]
    assert revisions == [3, 2, 1]
    assert manager.get_history_snapshot("svc", 1)["config"] == {"x": 1}
    assert manager.get_history_snapshot("svc", 3)["config"] == {"x": 2, "y": 3}


def test_unchanged_write_records_nothing(manager):
    manager.create("svc", config_data={"x": 1})
    manager.replace_config("svc", {"x": 1})  # identical — no revision bump
    assert [e["revision"] for e in manager.list_history("svc")] == [1]


def test_rollback_restores_config_and_schema_as_new_revision(manager):
    schema = {"type": "object", "properties": {"x": {"type": "integer"}}}
    manager.create("svc", config_data={"x": 1}, schema=schema)
    manager.update_schema("svc", None)          # rev 2: schema cleared
    manager.replace_config("svc", {"x": "s"})   # rev 3: allowed once schema gone

    app = manager.rollback("svc", 1)
    assert app.revision == 4                    # roll-forward, never rewound
    assert app.config.get_all() == {"x": 1}
    assert app.schema == schema
    # The rollback itself is in history, so it can be undone.
    assert manager.get_history_snapshot("svc", 4)["config"] == {"x": 1}


def test_rollback_to_identical_content_is_a_noop(manager):
    manager.create("svc", config_data={"x": 1})
    app = manager.rollback("svc", 1)
    assert app.revision == 1


def test_rollback_missing_revision_raises_lookup_error(manager):
    manager.create("svc", config_data={"x": 1})
    with pytest.raises(LookupError, match="not in history"):
        manager.rollback("svc", 42)


def test_rollback_honours_expected_revision(manager):
    manager.create("svc", config_data={"x": 1})
    manager.replace_config("svc", {"x": 2})
    with pytest.raises(RevisionConflictError):
        manager.rollback("svc", 1, expected_revision=1)


def test_rollback_missing_app_raises_key_error(manager):
    with pytest.raises(KeyError):
        manager.rollback("ghost", 1)


def test_disk_history_survives_manager_restart(tmp_path):
    first = AppManager(data_dir=tmp_path, history_limit=10)
    first.create("svc", config_data={"x": 1})
    first.replace_config("svc", {"x": 2})

    second = AppManager(data_dir=tmp_path, history_limit=10)
    second.load_persisted()
    app = second.rollback("svc", 1)
    assert app.config.get_all() == {"x": 1}


def test_rollback_can_be_invalid_against_nothing(manager):
    """Restoring a snapshot re-applies its own schema, so it always validates."""
    schema = {"type": "object", "required": ["x"]}
    manager.create("svc", config_data={"x": 1}, schema=schema)
    manager.update_schema("svc", {"type": "object"})  # rev 2, looser schema
    app = manager.rollback("svc", 1)
    assert app.schema == schema  # strict schema restored together with config
