"""Tests for the event system."""

import pytest

from nacho.event import (
    Change,
    EventPipeline,
    EventType,
    _match_path,
    detect_changes,
    on_change,
    on_event,
)


class TestDetectChanges:
    def test_no_changes(self):
        assert detect_changes({"a": 1}, {"a": 1}) == []

    def test_aggregate_change_always_first(self):
        changes = detect_changes({"a": 1}, {"a": 2})
        assert changes[0].path is None
        assert changes[0].type == EventType.CHANGE

    def test_update(self):
        changes = detect_changes({"a": 1}, {"a": 2})
        paths = [(c.type, c.path) for c in changes]
        assert (EventType.UPDATE, "a") in paths
        assert (EventType.CHANGE, "a") in paths

    def test_create(self):
        changes = detect_changes({}, {"a": 1})
        paths = [(c.type, c.path) for c in changes]
        assert (EventType.CREATE, "a") in paths

    def test_delete(self):
        changes = detect_changes({"a": 1}, {})
        paths = [(c.type, c.path) for c in changes]
        assert (EventType.DELETE, "a") in paths

    def test_nested_update(self):
        old = {"db": {"host": "old", "port": 5432}}
        new = {"db": {"host": "new", "port": 5432}}
        changes = detect_changes(old, new)
        paths = [c.path for c in changes]
        assert "db.host" in paths
        assert "db" not in paths

    def test_no_partial_match(self):
        """A parent key change does not appear as a separate event."""
        old = {"db": {"host": "a"}}
        new = {"db": {"host": "b"}}
        changes = detect_changes(old, new)
        db_changes = [c for c in changes if c.path == "db"]
        assert len(db_changes) == 0


class TestPathMatcher:
    def test_exact_match(self):
        assert _match_path("a.b", "a.b") is True

    def test_no_match(self):
        assert _match_path("a.b", "a.c") is False

    def test_wildcard_all(self):
        assert _match_path("*", "a.b.c") is True

    def test_wildcard_suffix(self):
        assert _match_path("db.*", "db.host") is True
        assert _match_path("db.*", "db.port") is True

    def test_wildcard_suffix_no_parent_match(self):
        """db.* should NOT match the parent key db itself."""
        assert _match_path("db.*", "db") is False

    def test_wildcard_mid(self):
        assert _match_path("db.*.port", "db.primary.port") is True
        assert _match_path("db.*.port", "db.primary.host") is False

    def test_none_pattern_matches_everything(self):
        assert _match_path(None, None) is True
        assert _match_path(None, "db.host") is True
        assert _match_path(None, "anything") is True

    def test_global_pattern_matches_only_aggregate(self):
        assert _match_path("@global", None) is True
        assert _match_path("@global", "db.host") is False

    def test_path_pattern_no_aggregate_match(self):
        assert _match_path("db.*", None) is False


class TestEventPipeline:
    def test_register_and_dispatch(self):
        pipe = EventPipeline()
        received = []

        def handler(event_type, path, old_value, new_value, config_data, **kw):
            received.append(path)

        pipe.register(handler, EventType.CHANGE)
        change = Change(EventType.CHANGE, "a.b", 1, 2)
        pipe.dispatch([change], {})
        assert "a.b" in received

    def test_priority_order(self):
        pipe = EventPipeline()
        order = []

        def h1(**kw):
            order.append(1)

        def h2(**kw):
            order.append(2)

        pipe.register(h2, EventType.CHANGE, priority=200)
        pipe.register(h1, EventType.CHANGE, priority=100)
        pipe.dispatch([Change(EventType.CHANGE, "x", None, 1)], {})
        assert order == [1, 2]

    def test_path_filter(self):
        pipe = EventPipeline()
        fired = []

        def handler(**kw):
            fired.append(kw["path"])

        pipe.register(handler, EventType.CHANGE, path_pattern="db.*")
        pipe.dispatch(
            [
                Change(EventType.CHANGE, "db.host", None, "new"),
                Change(EventType.CHANGE, "app.name", None, "x"),
            ],
            {},
        )
        assert fired == ["db.host"]

    def test_aggregate_handler(self):
        """Handler with path_pattern='@global' fires only on aggregate event."""
        pipe = EventPipeline()
        fired = []

        def handler(**kw):
            fired.append(kw["path"])

        pipe.register(handler, EventType.CHANGE, path_pattern="@global")
        pipe.dispatch(
            [
                Change(EventType.CHANGE, None, {}, {"a": 1}),  # aggregate
                Change(EventType.CHANGE, "a", None, 1),  # per-path
            ],
            {},
        )
        assert fired == [None]

    def test_none_pattern_matches_all(self):
        """Handler with path_pattern=None fires for every event."""
        pipe = EventPipeline()
        fired = []

        def handler(**kw):
            fired.append(kw["path"])

        pipe.register(handler, EventType.CHANGE, path_pattern=None)
        pipe.dispatch(
            [
                Change(EventType.CHANGE, None, {}, {"a": 1}),
                Change(EventType.CHANGE, "a", None, 1),
            ],
            {},
        )
        assert None in fired
        assert "a" in fired

    def test_async_handler(self):
        pipe = EventPipeline()
        received = []

        async def async_handler(**kw):
            received.append(kw["path"])

        pipe.register(async_handler, EventType.CHANGE)
        change = Change(EventType.CHANGE, "x", None, 1)
        # Async handler in sync context → asyncio.run() is used
        pipe.dispatch([change], {})
        # Give the coroutine a chance to run
        assert "x" in received

    def test_unregister(self):
        pipe = EventPipeline()
        fired = []

        def handler(**kw):
            fired.append(True)

        h = pipe.register(handler, EventType.CHANGE)
        pipe.unregister(h)
        pipe.dispatch([Change(EventType.CHANGE, "x", None, 1)], {})
        assert fired == []

    def test_handler_exception_does_not_propagate(self):
        pipe = EventPipeline()
        second_fired = []

        def bad(**kw):
            raise RuntimeError("oops")

        def good(**kw):
            second_fired.append(True)

        pipe.register(bad, EventType.CHANGE, priority=1)
        pipe.register(good, EventType.CHANGE, priority=2)
        pipe.dispatch([Change(EventType.CHANGE, "x", None, 1)], {})
        # second handler still fires
        assert second_fired == [True]

    def test_handlers_receive_isolated_config_snapshots(self):
        pipe = EventPipeline()
        observed = []

        def mutating_handler(config_data, new_value, **kw):
            config_data["x"] = "mutated"
            new_value["nested"] = "mutated"

        def observing_handler(config_data, new_value, **kw):
            observed.append((config_data["x"], new_value["nested"]))

        pipe.register(mutating_handler, EventType.CHANGE, priority=1)
        pipe.register(observing_handler, EventType.CHANGE, priority=2)
        pipe.dispatch(
            [Change(EventType.CHANGE, "x", {"nested": "old"}, {"nested": "new"})],
            {"x": "original"},
        )

        assert observed == [("original", "new")]


class TestDecorators:
    def test_on_change_decorator(self):
        pipe = EventPipeline()
        fired = []

        @on_change(pipe, "db.*")
        def handler(path, **kw):
            fired.append(path)

        pipe.dispatch([Change(EventType.CHANGE, "db.host", None, "x")], {})
        assert "db.host" in fired

    def test_on_event_decorator(self):
        pipe = EventPipeline()
        fired = []

        @on_event(pipe, EventType.DELETE)
        def handler(path, **kw):
            fired.append(path)

        pipe.dispatch(
            [
                Change(EventType.DELETE, "x", 1, None),
                Change(EventType.CREATE, "y", None, 2),
            ],
            {},
        )
        assert fired == ["x"]


class TestEventPipelineEdgeCases:
    def test_unregister_unknown_handler_returns_false(self):
        from nacho.event import EventHandler

        orphan = EventHandler(lambda **k: None, {EventType.UPDATE}, None, 100)
        assert EventPipeline().unregister(orphan) is False

    def test_match_path_rejects_length_mismatch(self):
        assert _match_path("a.b", "a") is False

    def test_transaction_get_reads_pending_state(self):
        from nacho import Nacho

        config = Nacho({"a": 1})
        with config.transaction() as txn:
            txn.set("a", 2)
            assert txn.get("a") == 2
            assert txn.get()["a"] == 2


@pytest.mark.asyncio
async def test_async_handler_dispatched_on_running_loop():
    import asyncio

    from nacho import Nacho

    config = Nacho({"x": 1}, events=True)
    seen = []

    @config.on_change("x")
    async def handler(**kwargs):
        seen.append(kwargs.get("new_value"))

    config.set("x", 2)
    for _ in range(500):  # bounded wait for the scheduled task, no fixed sleep
        if 2 in seen:
            break
        await asyncio.sleep(0.01)
    assert 2 in seen
