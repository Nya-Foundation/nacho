"""Tests for the AuthGuard token/cookie/header verification logic."""

import types

import pytest

from nacho.server.auth import AuthGuard


def _request(cookies=None, headers=None):
    return types.SimpleNamespace(cookies=cookies or {}, headers=headers or {})


class TestAuthGuard:
    def test_disabled_guard_allows_everything(self):
        guard = AuthGuard(api_key=None)
        assert guard.enabled is False
        assert guard.verify_token("anything") is True
        assert guard.verify_request(_request()) is True
        assert guard.verify_websocket(_request()) is True

    def test_set_api_key_rejects_empty(self):
        guard = AuthGuard()
        with pytest.raises(ValueError):
            guard.set_api_key("")

    def test_set_api_key_enables_the_guard(self):
        guard = AuthGuard()
        guard.set_api_key("k")
        assert guard.enabled is True

    def test_verify_token_matches_with_and_without_bearer_prefix(self):
        guard = AuthGuard(api_key="secret")
        assert guard.verify_token("secret") is True
        assert guard.verify_token("Bearer secret") is True
        assert guard.verify_token("wrong") is False
        assert guard.verify_token(None) is False

    def test_verify_request_accepts_cookie(self):
        guard = AuthGuard(api_key="secret")
        assert guard.verify_request(_request(cookies={"NACHO_api_key": "secret"})) is True

    def test_verify_request_falls_back_to_header(self):
        guard = AuthGuard(api_key="secret")
        req = _request(headers={"Authorization": "Bearer secret"})
        assert guard.verify_request(req) is True

    def test_verify_request_rejects_bad_credentials(self):
        guard = AuthGuard(api_key="secret")
        assert guard.verify_request(_request(cookies={"NACHO_api_key": "nope"})) is False

    def test_verify_websocket_accepts_cookie_then_header(self):
        guard = AuthGuard(api_key="secret")
        assert guard.verify_websocket(_request(cookies={"NACHO_api_key": "secret"})) is True
        assert guard.verify_websocket(
            _request(headers={"Authorization": "Bearer secret"})) is True
        assert guard.verify_websocket(_request()) is False
