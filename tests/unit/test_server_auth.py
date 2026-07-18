"""Tests for the AuthGuard token/cookie/header verification logic."""

import types

import pytest

from nacho.server.app import NachoOrchestrator
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

    def test_verify_token_matches_with_and_without_bearer_prefix(self):
        guard = AuthGuard(api_key="secret")
        assert guard.verify_token("secret") is True
        assert guard.verify_token("Bearer secret") is True
        assert guard.verify_token("wrong") is False
        assert guard.verify_token(None) is False

    def test_verify_token_rejects_non_ascii_without_crashing(self):
        guard = AuthGuard(api_key="secret")
        assert guard.verify_token("Bearer ключ") is False

    def test_verify_request_accepts_cookie(self):
        guard = AuthGuard(api_key="secret")
        assert guard.verify_request(_request(cookies={"NACHO_api_key": "secret"})) is True

    def test_verify_request_accepts_url_encoded_cookie(self):
        # The UI writes the cookie URL-encoded so keys with `;`/`,`/spaces
        # survive the cookie grammar; both forms must verify.
        guard = AuthGuard(api_key="se;cret key")
        assert guard.verify_request(_request(cookies={"NACHO_api_key": "se%3Bcret%20key"})) is True
        guard_plain = AuthGuard(api_key="secret")
        assert guard_plain.verify_request(_request(cookies={"NACHO_api_key": "secret"})) is True

    def test_verify_cookie_rejects_wrong_key_in_both_forms(self):
        guard = AuthGuard(api_key="secret")
        assert guard.verify_cookie("n%6Fpe") is False
        assert guard.verify_cookie("nope") is False
        assert guard.verify_cookie(None) is False

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
        assert guard.verify_websocket(_request(headers={"Authorization": "Bearer secret"})) is True
        assert guard.verify_websocket(_request()) is False


class TestKeyValidation:
    """A misconfigured key must fail at construction, not at request time."""

    @pytest.mark.parametrize("bad", [["k"], 1, True, {"k": 1}, ("k",), b"k"])
    def test_non_str_key_raises_typeerror(self, bad):
        with pytest.raises(TypeError, match="api_key must be a str"):
            AuthGuard(api_key=bad)

    def test_error_names_the_offending_type(self):
        with pytest.raises(TypeError, match="got list"):
            AuthGuard(api_key=["admin-key", "second-key"])

    def test_none_and_str_remain_valid(self):
        assert AuthGuard(api_key=None).enabled is False
        assert AuthGuard(api_key="k").enabled is True

    @pytest.mark.parametrize("falsy", [[], 0, {}])
    def test_falsy_non_str_key_cannot_silently_disable_auth(self, falsy):
        # The dangerous case: a falsy non-str key skips the orchestrator's
        # `if api_key` guard, so without validation the server would come up
        # entirely unauthenticated.
        with pytest.raises(TypeError):
            NachoOrchestrator(api_key=falsy)

    def test_orchestrator_rejects_non_str_key(self):
        with pytest.raises(TypeError, match="api_key must be a str or None, got list"):
            NachoOrchestrator(api_key=["admin-key"])


class TestSingleKeyGrantsFullAccess:
    """Access is all-or-nothing: there are no roles and no second key."""

    def test_the_key_authenticates_reads_and_writes_alike(self):
        guard = AuthGuard(api_key="the-key")
        assert guard.verify_token("the-key") is True
        assert guard.verify_token("Bearer the-key") is True
        assert guard.verify_token("some-other-key") is False

    def test_guard_exposes_no_role_api(self):
        guard = AuthGuard(api_key="the-key")
        for removed in ("role_for_token", "role_for_cookie", "role_for_request"):
            assert not hasattr(guard, removed)
        assert not hasattr(guard, "read_only_api_key")
