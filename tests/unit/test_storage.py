"""Tests for storage backends."""

from unittest import mock

import pytest

from nacho.storage.base import StorageError
from nacho.storage.file import FileStorageBackend
from nacho.storage.remote import RemoteStorageBackend


class TestFileStorageBackend:
    def test_load_yaml(self, tmp_yaml):
        backend = FileStorageBackend(tmp_yaml)
        data = backend.load()
        assert data["database"]["host"] == "localhost"

    def test_load_json(self, tmp_json):
        backend = FileStorageBackend(tmp_json)
        data = backend.load()
        assert data["app"]["name"] == "test"

    def test_load_toml(self, tmp_toml):
        backend = FileStorageBackend(tmp_toml)
        data = backend.load()
        assert data["server"]["port"] == 8080

    def test_missing_file_loads_empty_and_is_created_on_save(self, tmp_path):
        p = tmp_path / "new.yaml"
        backend = FileStorageBackend(p)
        assert not p.exists()
        assert backend.load() == {}
        backend.save({"a": 1})
        assert p.exists()

    def test_save_and_load(self, tmp_path):
        p = tmp_path / "out.json"
        backend = FileStorageBackend(p)
        data = {"key": "value", "num": 42}
        backend.save(data)
        assert backend.load() == data

    def test_save_raises_storage_error_on_io_failure(self, tmp_path):
        p = tmp_path / "out.yaml"
        backend = FileStorageBackend(p)
        import unittest.mock as mock

        # Patch at the point of use — where file.py imports save_file
        with mock.patch("nacho.storage.file.save_file", side_effect=IOError("disk full")):
            with pytest.raises(StorageError):
                backend.save({"key": "value"})

    def test_str_representation(self, tmp_yaml):
        backend = FileStorageBackend(tmp_yaml)
        assert "FileStorageBackend" in str(backend)
        assert str(tmp_yaml) in str(backend)

    def test_load_empty_file_returns_empty_dict(self, tmp_path):
        p = tmp_path / "empty.yaml"
        p.write_text("")
        backend = FileStorageBackend(p)
        assert backend.load() == {}

    def test_load_raises_storage_error_on_corrupt_file(self, tmp_path):
        p = tmp_path / "broken.yaml"
        p.write_text(": : not : valid : :")
        backend = FileStorageBackend(p)
        with pytest.raises(StorageError):
            backend.load()


class TestRemoteStorageBackend:
    def test_auto_connect_can_be_disabled(self):
        with mock.patch("nacho.client.requests.request") as request:
            backend = RemoteStorageBackend("http://example.test", auto_connect=False)

        request.assert_not_called()
        assert backend._connected is False
        assert backend._ws_thread is None
