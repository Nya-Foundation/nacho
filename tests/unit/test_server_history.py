"""Tests for HistoryStore and AppManager rollback semantics."""

import threading

import pytest

from nacho import Nacho
from nacho.server.runtime import (
    AppManager,
    HistoryStore,
    RevisionConflictError,
    safe_child_path,
)
from nacho.storage.base import StorageBackend, StorageError


def test_safe_child_path_joins_and_refuses_escapes(tmp_path):
    assert safe_child_path(tmp_path, "svc") == tmp_path / "svc"
    assert safe_child_path(tmp_path, "svc.json") == tmp_path / "svc.json"
    for hostile in ("..", "../escape", "a/../../b", "/etc/passwd"):
        with pytest.raises(ValueError):
            safe_child_path(tmp_path, hostile)


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


def test_negative_history_limit_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="zero or greater"):
        HistoryStore(tmp_path, limit=-1)


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
    manager.update_schema("svc", None)  # rev 2: schema cleared
    manager.replace_config("svc", {"x": "s"})  # rev 3: allowed once schema gone

    app = manager.rollback("svc", 1)
    assert app.revision == 4  # roll-forward, never rewound
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


def test_new_server_state_and_history_files_are_private(tmp_path):
    data_dir = tmp_path / "state"
    manager = AppManager(data_dir=data_dir, history_limit=10)
    manager.create("svc", config_data={"secret": "value"})
    assert (data_dir.stat().st_mode & 0o777) == 0o700
    assert ((data_dir / "svc.json").stat().st_mode & 0o777) == 0o600
    assert ((data_dir / "history").stat().st_mode & 0o777) == 0o700
    assert ((data_dir / "history" / "svc").stat().st_mode & 0o777) == 0o700
    assert ((data_dir / "history" / "svc" / "00000001.json").stat().st_mode & 0o777) == 0o600


def test_replacing_persisted_seed_preserves_or_advances_revision(tmp_path):
    data_dir = tmp_path / "state"
    config_file = tmp_path / "config.yaml"
    config_file.write_text("x: 1\n")

    first = AppManager(data_dir=data_dir, history_limit=10)
    first.create("svc", config=Nacho(config_file), replace=True)
    first.set_config_path("svc", "x", 2)
    assert first.get("svc").revision == 2

    second = AppManager(data_dir=data_dir, history_limit=10)
    second.load_persisted()
    second.create("svc", config=Nacho(config_file), replace=True)
    assert second.get("svc").revision == 2
    assert [e["revision"] for e in second.list_history("svc")] == [2, 1]

    config_file.write_text("x: 3\n")
    third = AppManager(data_dir=data_dir, history_limit=10)
    third.load_persisted()
    third.create("svc", config=Nacho(config_file), replace=True)
    assert third.get("svc").revision == 3
    assert third.get("svc").config.get_all() == {"x": 3}


class ControlledBackend(StorageBackend):
    def __init__(self, data):
        super().__init__()
        self.data = dict(data)
        self.fail = False
        self.started = threading.Event()
        self.release = threading.Event()
        self.block = False

    def load(self):
        return dict(self.data)

    def save(self, data):
        self.started.set()
        if self.block:
            assert self.release.wait(5)
        if self.fail:
            raise StorageError("disk full")
        self.data = dict(data)


def test_failed_config_save_restores_memory_revision_and_history():
    backend = ControlledBackend({"x": 1})
    manager = AppManager(history_limit=10)
    manager.create("svc", config=Nacho(backend))
    backend.fail = True

    with pytest.raises(StorageError, match="disk full"):
        manager.set_config_path("svc", "x", 2)

    app = manager.get("svc")
    assert app.config.get_all() == {"x": 1}
    assert app.revision == 1
    assert [e["revision"] for e in manager.list_history("svc")] == [1]


def test_failed_history_write_restores_memory_and_revision(monkeypatch):
    manager = AppManager(history_limit=10)
    app = manager.create("svc", config_data={"x": 1})
    real_record = manager.history.record

    def reject_new_revision(snapshot, **kwargs):
        if snapshot["revision"] == 2:
            raise OSError("history disk full")
        return real_record(snapshot, **kwargs)

    monkeypatch.setattr(manager.history, "record", reject_new_revision)
    with pytest.raises(OSError, match="history disk full"):
        manager.set_config_path("svc", "x", 2)

    assert app.config.get_all() == {"x": 1}
    assert app.revision == 1
    assert [e["revision"] for e in manager.list_history("svc")] == [1]


def test_reads_wait_for_persistence_and_observe_matching_revision():
    backend = ControlledBackend({"x": 1})
    manager = AppManager(history_limit=10)
    app = manager.create("svc", config=Nacho(backend))
    backend.block = True

    writer = threading.Thread(target=lambda: manager.set_config_path("svc", "x", 2))
    writer.start()
    assert backend.started.wait(2)

    result = []
    reader = threading.Thread(target=lambda: result.append(app.snapshot()))
    reader.start()
    assert reader.is_alive(), "snapshot should wait while the write is being persisted"

    backend.release.set()
    writer.join(5)
    reader.join(5)
    assert result[0]["config"] == {"x": 2}
    assert result[0]["revision"] == 2


def test_failed_rename_restores_indexes_history_and_metadata(manager, monkeypatch):
    manager.create("svc", config_data={"x": 1}, description="before")
    real_save = manager.store.save
    calls = 0

    def fail_once(app):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("disk full")
        return real_save(app)

    monkeypatch.setattr(manager.store, "save", fail_once)
    with pytest.raises(OSError, match="disk full"):
        manager.rename("svc", new_name="renamed", description="after")

    app = manager.get("svc")
    assert app is not None
    assert manager.get("renamed") is None
    assert app.description == "before"
    assert app.revision == 1
    assert [entry["revision"] for entry in manager.list_history("svc")] == [1]


def test_failed_commit_does_not_prune_last_good_history_entry(tmp_path, monkeypatch):
    manager = AppManager(data_dir=tmp_path, history_limit=1)
    manager.create("svc", config_data={"x": 1})
    real_save = manager.store.save
    calls = 0

    def fail_once(app):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("store unavailable")
        return real_save(app)

    monkeypatch.setattr(manager.store, "save", fail_once)
    with pytest.raises(OSError, match="store unavailable"):
        manager.set_config_path("svc", "x", 2)
    assert [entry["revision"] for entry in manager.list_history("svc")] == [1]


def test_rollback_can_be_invalid_against_nothing(manager):
    """Restoring a snapshot re-applies its own schema, so it always validates."""
    schema = {"type": "object", "required": ["x"]}
    manager.create("svc", config_data={"x": 1}, schema=schema)
    manager.update_schema("svc", {"type": "object"})  # rev 2, looser schema
    app = manager.rollback("svc", 1)
    assert app.schema == schema  # strict schema restored together with config
