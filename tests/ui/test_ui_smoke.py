"""Browser-driven smoke tests for the bundled management UI (/ui).

Each test starts a real Nacho server subprocess (via ``make_live_server``)
and drives the SPA with Playwright/Chromium. Chromium is launched once per
module; every test gets a fresh browser context (clean localStorage/cookies)
and a fresh server (clean app state).

Run with:  uv run pytest -m ui --no-cov -q
"""

import json
import urllib.error
import urllib.request

import pytest
from playwright.sync_api import expect, sync_playwright

# Generous polling window: these tests exercise WS round trips and a real
# server subprocess, so never rely on tight timing.
TIMEOUT_MS = 15_000
expect.set_options(timeout=TIMEOUT_MS)

EDITOR = "#config-host textarea.code-input"


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        yield browser
        browser.close()


@pytest.fixture
def new_page(browser):
    """Factory for pages, each in its own fresh browser context."""
    contexts = []

    def make():
        ctx = browser.new_context()
        ctx.set_default_timeout(TIMEOUT_MS)
        contexts.append(ctx)
        return ctx.new_page()

    yield make
    for ctx in contexts:
        ctx.close()


# --------------------------------------------------------------------------- #
# REST helpers (external writer, bypassing the UI)
# --------------------------------------------------------------------------- #
def rest(url, method="GET", body=None, api_key=None):
    """Minimal JSON-over-HTTP helper; returns the parsed response body."""
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    if api_key:
        req.add_header("Authorization", "Bearer " + api_key)
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode())


def put_config(server_url, data, api_key=None):
    """External config write to the auto-created 'default' app."""
    return rest(
        server_url + "/api/apps/default/config",
        method="PUT",
        body={"data": data},
        api_key=api_key,
    )


def get_config(server_url, api_key=None):
    return rest(server_url + "/api/apps/default/config", api_key=api_key)


# --------------------------------------------------------------------------- #
# UI helpers
# --------------------------------------------------------------------------- #
def open_app_view(page, server_url):
    """Load /ui on an unauthenticated server and wait for the app shell."""
    page.goto(server_url + "/ui")
    expect(page.locator("#app-view")).to_be_visible()
    expect(page.locator("#app-list .app-item .app-name")).to_have_text("default")


def select_default_app(page):
    """Open the 'default' app and wait until its WS watcher is live."""
    page.locator("#app-list .app-item", has_text="default").click()
    expect(page.locator(EDITOR)).to_be_visible()
    # The live-update tests require the WebSocket to be connected before an
    # external write happens, otherwise the broadcast is missed.
    expect(page.locator("#live-label")).to_have_text("Live")


# --------------------------------------------------------------------------- #
# Tests
# --------------------------------------------------------------------------- #
def test_ui_loads_without_auth(make_live_server, new_page):
    """/ui renders the app shell; no api key -> straight to the app list."""
    server = make_live_server()
    page = new_page()
    page.goto(server.url + "/ui")
    expect(page).to_have_title("Nacho — Configuration Manager")
    expect(page.locator("#app-view")).to_be_visible()
    expect(page.locator("#connect-view")).to_be_hidden()
    expect(page.locator("#app-list .app-item .app-name")).to_have_text("default")
    # An open server has no session to end; sending users to the API-key form
    # here would be a dead end. API docs remain directly available.
    expect(page.locator("#disconnect-btn")).to_be_hidden()
    expect(page.locator("#docs-link")).to_have_attribute("href", "docs")


def test_desktop_app_navigation_collapses_and_persists(make_live_server, new_page):
    """The app index can get out of the way for wide configuration editing."""
    server = make_live_server()
    page = new_page()
    open_app_view(page, server.url)

    expect(page.locator("#nav-toggle")).to_have_attribute("aria-expanded", "true")
    page.click("#nav-toggle")
    expect(page.locator("#nav-toggle")).to_have_attribute("aria-expanded", "false")
    expect(page.locator("#app-index")).to_have_css("visibility", "hidden")

    page.reload()
    expect(page.locator("#app-view")).to_be_visible()
    expect(page.locator("#nav-toggle")).to_have_attribute("aria-expanded", "false")
    expect(page.locator("#app-index")).to_have_css("visibility", "hidden")


def test_auth_flow_wrong_then_right_key(make_live_server, new_page):
    """Keyed server shows sign-in; wrong key errors, right key proceeds."""
    server = make_live_server(api_key="s3cret-ui-key")
    page = new_page()
    page.goto(server.url + "/ui")
    expect(page.locator("#connect-view")).to_be_visible()
    expect(page.locator("#app-view")).to_be_hidden()

    page.fill("#key-input", "definitely-wrong")
    page.click("#connect-btn")
    expect(page.locator("#connect-error")).to_have_text("Invalid API key.")
    expect(page.locator("#app-view")).to_be_hidden()

    page.fill("#key-input", "s3cret-ui-key")
    page.click("#connect-btn")
    expect(page.locator("#app-view")).to_be_visible()
    expect(page.locator("#app-list .app-item .app-name")).to_have_text("default")
    expect(page.locator("#disconnect-btn")).to_be_visible()


def test_auth_key_with_cookie_hostile_chars(make_live_server, new_page):
    """A key containing `;` and spaces survives the cookie round-trip.

    The WS handshake can only authenticate via the cookie (browsers cannot
    set an Authorization header on WebSockets), so this fails if the UI does
    not URL-encode the cookie value or the server does not decode it.
    """
    key = "se;cret ui,key"
    server = make_live_server(api_key=key)
    page = new_page()
    page.goto(server.url + "/ui")
    page.fill("#key-input", key)
    page.click("#connect-btn")
    expect(page.locator("#app-view")).to_be_visible()

    # "live" proves the WebSocket authenticated through the encoded cookie.
    select_default_app(page)

    put_config(server.url, {"guarded": True}, api_key=key)
    expect(page.locator(EDITOR)).to_have_value(json.dumps({"guarded": True}, indent=2))


def test_preauthenticated_embedding_contract(make_live_server, new_page):
    """Seeding localStorage + cookie signs the UI in with no login form.

    This pins the documented embedding contract (README: "Pre-authenticating
    an embedded UI"). Host apps that mount the orchestrator behind their own
    session auth depend on these exact names; renaming either would silently
    regress every embedder to a double login.
    """
    key = "embedded-host-key"
    server = make_live_server(api_key=key)
    page = new_page()

    # Seed both stores from the origin, as a host login page would, before
    # the UI ever loads. /ui is public, so this can run on the page itself.
    page.goto(server.url + "/ui")
    page.evaluate(
        """(key) => {
            localStorage.setItem("nacho_api_key", key);
            document.cookie = "NACHO_api_key=" + encodeURIComponent(key) +
                "; path=/; SameSite=Strict";
        }""",
        key,
    )
    page.reload()

    # No sign-in screen, and the WebSocket authenticated from the cookie.
    expect(page.locator("#connect-view")).to_be_hidden()
    expect(page.locator("#app-view")).to_be_visible()
    select_default_app(page)

    put_config(server.url, {"preauth": True}, api_key=key)
    expect(page.locator(EDITOR)).to_have_value(json.dumps({"preauth": True}, indent=2))


def test_edit_and_save_round_trip(make_live_server, new_page):
    """Type a config, Save, see success feedback, verify via REST."""
    server = make_live_server()
    page = new_page()
    open_app_view(page, server.url)
    select_default_app(page)

    page.fill(EDITOR, '{"greeting": "hello", "count": 3}')
    expect(page.locator("#editor-status")).to_have_text("● Unsaved changes")
    page.click("#save-btn")

    # Success feedback: revision bumps, editor returns to a clean state.
    expect(page.locator("#rev-label")).to_have_text("2")
    expect(page.locator("#editor-status")).to_have_text("Saved")

    assert get_config(server.url) == {"greeting": "hello", "count": 3}


def test_live_update_reaches_clean_editor(make_live_server, new_page):
    """External REST write is pushed over WS into a clean editor, no reload."""
    server = make_live_server()
    page = new_page()
    open_app_view(page, server.url)
    select_default_app(page)

    put_config(server.url, {"pushed": "from-rest", "n": 1})

    expect(page.locator("#rev-label")).to_have_text("2")
    expect(page.locator(EDITOR)).to_have_value(
        json.dumps({"pushed": "from-rest", "n": 1}, indent=2)
    )
    # The pushed content is adopted as the new pristine state, not as an edit.
    expect(page.locator("#editor-status")).to_have_text("Saved")


def test_remote_schema_and_metadata_updates_refresh_open_app(make_live_server, new_page):
    """WS state frames keep schema and app details fresh, not only config text."""
    server = make_live_server()
    page = new_page()
    open_app_view(page, server.url)
    select_default_app(page)

    rest(
        server.url + "/api/apps/default/metadata",
        method="PATCH",
        body={"description": "Changed elsewhere", "revision": 1},
    )
    expect(page.locator("#app-description")).to_have_text("Changed elsewhere")
    expect(page.locator("#rev-label")).to_have_text("2")

    schema = {"type": "object", "properties": {"enabled": {"type": "boolean"}}}
    rest(
        server.url + "/api/apps/default/schema",
        method="PUT",
        body={"schema": schema, "revision": 2},
    )
    expect(page.locator("#schema-flag")).to_have_text("Schema attached")
    expect(page.locator("#rev-label")).to_have_text("3")

    page.click('.tab[data-tab="schema"]')
    expect(page.locator("#schema-host textarea.code-input")).to_have_value(
        json.dumps(schema, indent=2)
    )

    rest(
        server.url + "/api/apps/default/schema",
        method="PUT",
        body={"schema": None, "revision": 3},
    )
    expect(page.locator("#schema-flag")).to_have_text("No schema")
    expect(page.locator("#schema-host textarea.code-input")).to_have_value("")


def test_dirty_editor_survives_remote_update_then_conflicts(make_live_server, new_page):
    """A WS update over a dirty editor warns, and Save then hits the 409 flow."""
    server = make_live_server()
    page = new_page()
    open_app_view(page, server.url)
    select_default_app(page)

    page.fill(EDITOR, '{"mine": "local-edit"}')
    expect(page.locator("#editor-status")).to_have_text("● Unsaved changes")

    put_config(server.url, {"external": "writer-won"})

    # The UI must warn but keep the local edits and the OLD revision.
    warn = page.locator("#config-notice .notice.warn")
    expect(warn).to_contain_text("Someone else just saved this app")
    expect(page.locator(EDITOR)).to_have_value('{"mine": "local-edit"}')
    expect(page.locator("#rev-label")).to_have_text("1")

    # Saving now must surface a revision conflict, not silently overwrite.
    page.click("#save-btn")
    expect(warn).to_contain_text("Someone else saved first")
    expect(page.locator("#conflict-reload")).to_be_visible()

    # The external writer's value survived on the server.
    assert get_config(server.url) == {"external": "writer-won"}


def test_active_tab_reclick_keeps_edits(make_live_server, new_page):
    """Re-clicking the already-active tab must not discard unsaved edits."""
    server = make_live_server()
    page = new_page()
    open_app_view(page, server.url)
    select_default_app(page)

    page.fill(EDITOR, '{"keep": "me"}')
    expect(page.locator("#editor-status")).to_have_text("● Unsaved changes")

    page.click('.tab[data-tab="config"]')  # already active

    expect(page.locator(EDITOR)).to_have_value('{"keep": "me"}')
    expect(page.locator("#editor-status")).to_have_text("● Unsaved changes")
    # A no-op re-click must not raise the discard-confirm dialog.
    expect(page.locator("#confirm-dialog")).to_have_count(0)


def test_create_and_delete_app_via_ui(make_live_server, new_page):
    """The New-app modal creates a real app; Delete removes it server-side."""
    server = make_live_server()
    page = new_page()
    open_app_view(page, server.url)

    page.click("#new-app-btn")
    page.fill("#m-name", "svc")
    page.fill("#m-config", '{"port": 8080}')
    page.click("#m-create")

    expect(page.locator("#app-list .app-item", has_text="svc")).to_be_visible()
    assert rest(server.url + "/api/apps/svc/config") == {"port": 8080}

    page.locator("#app-list .app-item", has_text="svc").click()
    expect(page.locator(EDITOR)).to_be_visible()
    page.click("#delete-btn")
    expect(page.locator("#confirm-dialog")).to_be_visible()
    page.click("#confirm-accept")

    expect(page.locator("#app-list .app-item", has_text="svc")).to_have_count(0)
    with pytest.raises(urllib.error.HTTPError) as exc:
        rest(server.url + "/api/apps/svc/config")
    assert exc.value.code == 404


def test_ui_reconnects_after_server_restart(make_live_server, new_page):
    """The UI watcher backs off, reconnects, and resumes live updates."""
    server = make_live_server()
    page = new_page()
    open_app_view(page, server.url)
    select_default_app(page)

    server.stop()
    expect(page.locator("#live-label")).to_have_text("Reconnecting…")

    make_live_server(port=server.port, data_dir=server.data_dir)
    expect(page.locator("#live-label")).to_have_text("Live")

    # Live updates work again after the reconnect, not just the status dot.
    put_config(server.url, {"revived": True})
    expect(page.locator(EDITOR)).to_have_value(json.dumps({"revived": True}, indent=2))


def test_history_lists_revisions_and_restore(make_live_server, new_page):
    """History shows past revisions; restoring one rolls the config back."""
    server = make_live_server()
    # r1 = {} (auto-created), r2 and r3 via external writes.
    put_config(server.url, {"step": 1})
    put_config(server.url, {"step": 2})

    page = new_page()
    open_app_view(page, server.url)
    select_default_app(page)
    expect(page.locator("#rev-label")).to_have_text("3")

    page.click('.tab[data-tab="history"]')
    rows = page.locator("#history-body .history-table tbody tr")
    expect(rows).to_have_count(3)
    expect(page.locator("#history-body")).to_contain_text("r3 (current)")

    # Restore revision 2 ({"step": 1}) via the styled confirm dialog.
    page.click('#history-body [data-restore="2"]')
    expect(page.locator("#confirm-dialog")).to_be_visible()
    page.click("#confirm-accept")

    # A rollback is a NEW revision (r4) that becomes current.
    expect(page.locator("#history-body")).to_contain_text("r4 (current)")
    assert get_config(server.url) == {"step": 1}
