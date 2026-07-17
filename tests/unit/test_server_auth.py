"""Tests for the AuthGuard token/cookie/header verification logic."""

import types

from nacho.server.auth import ROLE_ADMIN, ROLE_READ, AuthGuard


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


class TestReadOnlyKey:
    def test_roles_for_each_key(self):
        guard = AuthGuard(api_key="admin-key", read_only_api_key="ro-key")
        assert guard.role_for_token("admin-key") == ROLE_ADMIN
        assert guard.role_for_token("Bearer ro-key") == ROLE_READ
        assert guard.role_for_token("wrong") is None
        assert guard.role_for_token(None) is None

    def test_read_only_key_alone_enables_auth_but_never_admin(self):
        guard = AuthGuard(read_only_api_key="ro-key")
        assert guard.enabled is True
        assert guard.role_for_token("ro-key") == ROLE_READ
        assert guard.verify_token("ro-key") is False  # not full access

    def test_request_role_prefers_admin_across_credential_sources(self):
        guard = AuthGuard(api_key="admin-key", read_only_api_key="ro-key")
        request = _request(
            cookies={"NACHO_api_key": "ro-key"},
            headers={"Authorization": "Bearer admin-key"},
        )
        assert guard.role_for_request(request) == ROLE_ADMIN

    def test_websocket_accepts_read_only_key(self):
        guard = AuthGuard(api_key="admin-key", read_only_api_key="ro-key")
        assert guard.verify_websocket(_request(cookies={"NACHO_api_key": "ro-key"})) is True
