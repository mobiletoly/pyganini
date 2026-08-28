"""HTTP and application-boundary proof for the Starlette host."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlencode

import pytest
from pyganini import TemplateInspectionMode, browser, csrf
from starlette.testclient import TestClient

from app._pyganini.urls import urls
from app.contacts import ContactRepository
from app.dependencies import Dependencies
from app.main import create_app, create_development_app
from assets import pyganini_assets_gen as assets

from .client import ExampleClient, as_example_client


def test_cache_policy_import_boundary_has_no_pyganini_dependency() -> None:
    example_root = Path(__file__).parents[1]
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(example_root)
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; import app.security; "
                "assert not any(name == 'pyganini' or name.startswith('pyganini.') "
                "for name in sys.modules)"
            ),
        ],
        cwd=example_root,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_example_uses_current_pyganini_terminology() -> None:
    users_route_source = (
        Path(__file__).parents[1] / "app" / "routes" / "users" / "route.py"
    ).read_text(encoding="ascii")
    settings_route_source = (
        Path(__file__).parents[1] / "app" / "routes" / "settings" / "users" / "route.py"
    ).read_text(encoding="ascii")
    source_route_source = (
        Path(__file__).parents[1] / "app" / "mounts" / "contact_directory" / "route.py"
    ).read_text(encoding="ascii")
    create_route_source = (
        Path(__file__).parents[1]
        / "app"
        / "mounts"
        / "contact_directory"
        / "create"
        / "route.py"
    ).read_text(encoding="ascii")
    assert (
        "from pyganini import RouteNav, mount_route, nav, route_mount, to"
        in users_route_source
    )
    assert "Route = route_mount(" in users_route_source
    assert 'mount="contact_directory"' in users_route_source
    assert 'mount_route(\n            "/",' in users_route_source
    assert 'mount_route("/create")' in users_route_source
    assert 'mount_route("/{id}")' in users_route_source
    assert 'nav=RouteNav(label="Contacts")' in users_route_source
    assert 'trail_key="from-contacts"' in users_route_source
    assert "from pyganini import mount_route, route_mount" in settings_route_source
    assert 'routes=(mount_route("/"),)' in settings_route_source
    assert (
        "from pyganini import RouteNav, kit_fragment_route, route_kit"
        in source_route_source
    )
    assert "kit_fragment_route(" in source_route_source
    assert "from pyganini import kit_action, route_kit" in create_route_source
    assert "app/shared" not in users_route_source
    assert "template_root" not in users_route_source
    assert "template_root" not in source_route_source
    assert "mounted_route" not in users_route_source
    assert "mount_kit" not in users_route_source
    assert "ROUTE" not in users_route_source
    assert "Route = route(" not in users_route_source


def _csrf_token(response_text: str) -> str:
    match = re.search(r'name="csrf_token" value="([^"]+)"', response_text)
    assert match is not None
    return match.group(1)


def _multipart_fields(
    token: str, name: str = "", status: str = "Active"
) -> dict[str, str]:
    return {"csrf_token": token, "name": name, "status": status}


def test_pages_layouts_dynamic_routes_and_asset_ownership(
    client: ExampleClient,
) -> None:
    root = client.get("/")
    assert root.status_code == 200
    assert "Pyganini Directory" in root.text
    assert "Contact Directory" in root.text
    assert 'href="/users"' in root.text
    assert "<title>Pyganini Contact Directory</title>" in root.text
    assert (
        '<meta name="description" content="A server-rendered contact directory '
        'built with Pyganini.">' in root.text
    )
    assert root.headers["x-content-type-options"] == "nosniff"
    assert client.get("/settings").status_code == 200
    settings = client.get("/settings")
    assert 'data-page="settings"' in settings.text
    assert 'href="/settings" aria-current="page"' in settings.text

    users = client.get("/users")
    assert users.status_code == 200
    assert 'data-layout="root"' in users.text
    assert 'data-layout="users"' in users.text
    assert 'data-route-policy="users"' in users.text
    assert 'data-layout="mounted-contact-directory"' in users.text
    assert 'href="/users" aria-current="page"' in users.text
    assert 'hx-post="/users/create"' in users.text
    assert 'hx-get="/users/table?status=active"' in users.text
    assert users.text.index("Ada Lovelace") < users.text.index("Grace Hopper")
    assert users.text.index("Grace Hopper") < users.text.index("Katherine Johnson")
    app_script = client.get(assets.path("app.js"))
    assert app_script.status_code == 200
    assert app_script.headers["cache-control"] == (
        "public, max-age=31536000, immutable"
    )
    assert "pyganiniJs" in app_script.text
    assert "noSwap" in app_script.text
    assert "responseHandling" not in app_script.text
    assert client.get("/assets/missing.js").status_code == 404
    assert "cache-control" not in client.get("/assets/missing.js").headers

    bound_urls = urls.with_base_path("")
    assert bound_urls.users.by_id("42").path == "/users/42"

    settings_users = client.get("/settings/users")
    assert settings_users.status_code == 200
    assert "Settings Contacts - Pyganini Contact Directory" in settings_users.text
    assert 'data-layout="root"' in settings_users.text
    assert 'data-layout="settings-users"' in settings_users.text
    assert 'data-route-policy="settings-users"' in settings_users.text
    assert 'data-layout="mounted-contact-directory"' in settings_users.text
    assert 'href="/settings" aria-current="page"' in settings_users.text
    assert "Ada Lovelace" in settings_users.text
    assert "Katherine Johnson" not in settings_users.text
    assert 'hx-post="/settings/users/create"' not in settings_users.text
    assert 'hx-get="/settings/users/table?status=active"' in settings_users.text
    assert "/settings/users/42" not in settings_users.text
    assert client.post("/settings/users/create").status_code == 404
    assert client.get("/settings/users/table?status=inactive").status_code == 200
    settings_table = client.get("/settings/users/table?status=inactive")
    assert "No contacts match this filter." in settings_table.text
    assert "Katherine Johnson" not in settings_table.text
    assert "Ada Lovelace" not in settings_table.text
    assert 'data-layout="root"' not in settings_table.text

    detail = client.get("/users/42")
    assert detail.status_code == 200
    assert "Ada Lovelace" in detail.text
    assert detail.text.index('data-layout="root"') < detail.text.index(
        'data-layout="users"'
    )
    assert detail.text.index('data-layout="users"') < detail.text.index(
        'data-layout="mounted-contact-directory"'
    )
    assert client.get("/users/missing").status_code == 404


def test_application_owned_sse_host_route() -> None:
    application = create_app()
    with TestClient(application) as client:
        initial = client.get("/events")
        reconnect = client.get("/events", headers={"Last-Event-ID": "42"})
        helper = client.get("/pyganini/pyganini-sse-event.js")
        not_modified = client.get(
            "/pyganini/pyganini-sse-event.js",
            headers={"If-None-Match": helper.headers["etag"]},
        )
        root = client.get("/")

    expected_prefix = (
        b': connected\n\nid: 42\nevent: audit\ndata: <span data-sse-event="ignored">'
        b"Ignored SSE event</span>\n\nid: 43\nevent: contact\nretry: 2000\n"
    )
    assert initial.status_code == 200
    assert initial.headers["content-type"] == "text/event-stream; charset=utf-8"
    assert initial.headers["cache-control"] == "no-cache"
    assert initial.content == (
        expected_prefix + b'data: <span data-sse-event="contact">Named SSE contact; '
        b"last-event-id: start</span>\n\n"
    )
    assert reconnect.content == (
        expected_prefix + b'data: <span data-sse-event="contact">Named SSE contact; '
        b"last-event-id: 42</span>\n\n"
    )
    assert helper.status_code == 200
    assert helper.content.startswith(b"(function () {")
    assert helper.headers["cache-control"] == "no-cache"
    assert not_modified.status_code == 304
    assert not_modified.content == b""
    assert root.status_code == 200
    assert "Pyganini Directory" in root.text
    assert 'hx-sse:connect="/events"' in root.text
    assert f'src="/pyganini{browser.SSE_EVENT_HELPER_PATH}"' in root.text
    assert 'pyganini-sse-event="contact"' in root.text
    assert browser.TEMPLATE_INSPECTOR_HELPER_PATH not in root.text
    assert "<!--pyganini:start" not in root.text


def test_application_owned_template_inspection_modes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with TestClient(
        create_app(template_inspection=TemplateInspectionMode.COMMENTS)
    ) as client:
        comments = client.get("/users")
        fragment = client.get("/users/table")
        token = _csrf_token(comments.text)
        action_page = client.post("/users/create", data=_multipart_fields(token))
        action_fragment = client.post(
            "/users/create",
            data=_multipart_fields(token),
            headers={"HX-Request": "true"},
        )
        root_error = client.get("/missing")
        root_error_fragment = client.get("/missing", headers={"HX-Request": "true"})
        matched_error = client.get(
            "/users", headers={"X-Example-Route-Error": "matched"}
        )
        head = client.head("/users")
    assert comments.status_code == 200
    assert "<!--pyganini:start" in comments.text
    assert "kind=component surface=component" in comments.text
    assert "surface=embedded%2Dfragment" in comments.text
    assert browser.TEMPLATE_INSPECTOR_HELPER_PATH not in comments.text
    assert "kind=fragment surface=fragment route=/users/table" in fragment.text
    assert "kind=page surface=action%2Dpage route=/users/create" in action_page.text
    assert (
        "kind=fragment surface=action%2Dfragment route=/users/create"
        in action_fragment.text
    )
    assert "kind=page surface=root%2Derror%2Dpage route=/" in root_error.text
    assert (
        "kind=fragment surface=root%2Derror%2Dfragment route=/"
        in root_error_fragment.text
    )
    assert "kind=page surface=matched%2Derror%2Dpage route=/users" in matched_error.text
    assert head.content == b""

    monkeypatch.setenv("PYGANINI_TEMPLATE_INSPECTION", "overlay")
    with TestClient(create_development_app()) as client:
        overlay = client.get("/users")
        helper = client.get(f"/pyganini{browser.TEMPLATE_INSPECTOR_HELPER_PATH}")
    assert "<!--pyganini:start" in overlay.text
    assert f'src="/pyganini{browser.TEMPLATE_INSPECTOR_HELPER_PATH}"' in overlay.text
    assert helper.status_code == 200

    monkeypatch.setenv("PYGANINI_TEMPLATE_INSPECTION", "invalid")
    with pytest.raises(
        RuntimeError,
        match="PYGANINI_TEMPLATE_INSPECTION must be off, comments, or overlay",
    ):
        create_development_app()


@pytest.mark.parametrize(
    ("root_path", "external_prefix"),
    [
        ("/tenant?blue", "/tenant%3Fblue"),
        ("/tenant#blue", "/tenant%23blue"),
        ("/tenant%blue", "/tenant%25blue"),
    ],
)
def test_application_owned_sse_urls_bind_decoded_root_path(
    root_path: str,
    external_prefix: str,
) -> None:
    application = create_app()
    with TestClient(application, root_path=root_path) as client:
        response = client.get(f"{external_prefix}/")

    assert response.status_code == 200
    assert f'hx-sse:connect="{external_prefix}/events"' in response.text
    assert (
        f'src="{external_prefix}/pyganini{browser.SSE_EVENT_HELPER_PATH}"'
        in response.text
    )
    assert f'src="{external_prefix}/assets/vendor/hx-sse.min.' in response.text

    with TestClient(
        create_app(template_inspection=TemplateInspectionMode.OVERLAY),
        root_path=root_path,
    ) as client:
        inspected = client.get(f"{external_prefix}/users")
    with TestClient(
        create_app(template_inspection=TemplateInspectionMode.OVERLAY)
    ) as client:
        baseline = client.get("/users")
    assert (
        f'src="{external_prefix}/pyganini'
        f'{browser.TEMPLATE_INSPECTOR_HELPER_PATH}"' in inspected.text
    )
    assert "route=/users" in inspected.text
    assert root_path not in inspected.text
    marker = re.compile(r"<!--pyganini:(?:start|end) [^>]+-->")
    assert marker.findall(inspected.text) == marker.findall(baseline.text)


def test_application_owned_generated_error_presentation() -> None:
    application = create_app()
    with TestClient(application, raise_server_exceptions=False) as client:
        not_found = client.get("/missing")
        fragment = client.get("/missing", headers={"HX-Request": "true"})
        method_not_allowed = client.post("/users")
        problem = client.get("/problem")
        matched = client.get("/users", headers={"X-Example-Route-Error": "matched"})
        matched_head = client.head(
            "/users", headers={"X-Example-Route-Error": "matched"}
        )
        direct = client.get("/missing", headers={"X-Error-Presentation": "direct"})
        delegated = client.get("/missing", headers={"X-Error-Presentation": "delegate"})

    assert not_found.status_code == 404
    assert "Page not found" in not_found.text
    assert 'data-layout="root"' in not_found.text
    assert 'data-presentation="page"' in not_found.text
    assert fragment.status_code == 404
    assert 'data-presentation="fragment"' in fragment.text
    assert 'data-layout="root"' not in fragment.text
    assert fragment.headers["hx-retarget"] == "#global-error"
    assert fragment.headers["hx-reswap"] == "outerHTML"
    assert method_not_allowed.status_code == 405
    assert method_not_allowed.headers["allow"] == "GET, HEAD"
    assert "Method not allowed" in method_not_allowed.text
    assert 'data-layout="root"' in method_not_allowed.text
    assert problem.status_code == 500
    assert "Request failed" in problem.text
    assert 'data-layout="root"' in problem.text
    assert matched.status_code == 418
    assert "Matched route failed" in matched.text
    assert matched.text.index('data-layout="root"') < matched.text.index(
        'data-layout="users"'
    )
    assert matched.text.index('data-layout="users"') < matched.text.index(
        'data-layout="mounted-contact-directory"'
    )
    assert matched_head.status_code == 418
    assert matched_head.content == b""
    assert matched_head.headers["content-length"] == str(len(matched.content))
    assert direct.status_code == 404
    assert direct.text == "Direct application error"
    assert delegated.status_code == 404
    assert delegated.text == "Not Found"


def test_navigation_is_explicit_dynamic_and_return_safe(client: ExampleClient) -> None:
    users = client.get("/users")
    assert users.status_code == 200
    assert 'aria-label="Breadcrumb"' in users.text
    assert "Contacts" in users.text
    assert 'aria-current="page"' in users.text
    assert (
        'href="/users/42?_pyganini_nav_trail_key=from-contacts&amp;'
        '_pyganini_return_to=%2Fusers"'
    ) in users.text

    detail = client.get(
        "/users/42?_pyganini_nav_trail_key=from-contacts&"
        "_pyganini_return_to=%2Fusers%2Ftable%3Fstatus%3Dactive"
    )
    assert detail.status_code == 200
    assert "Ada Lovelace" in detail.text
    assert 'aria-label="Breadcrumb"' in detail.text
    assert 'aria-current="page">Ada Lovelace</' in detail.text
    assert ('href="/users/table?status=active">Back to Contacts</a>') in detail.text


def test_fragment_has_table_and_no_layouts(client: ExampleClient) -> None:
    response = client.get("/users/table?status=inactive")
    assert response.status_code == 200
    assert "Katherine Johnson" in response.text
    assert "Ada Lovelace" not in response.text
    assert 'data-layout="root"' not in response.text
    assert 'data-layout="users"' not in response.text


def test_csrf_cookie_hidden_field_and_rejection_without_mutation() -> None:
    application = create_app()
    with TestClient(application) as raw_client:
        client = as_example_client(raw_client)
        page = client.get("/users")
        token = _csrf_token(page.text)
        before = client.get("/users/table").text

        rejected = client.post(
            "/users/create",
            data=_multipart_fields("wrong-token", "Blocked"),
        )
        assert rejected.status_code == 403
        assert client.get("/users/table").text == before
        assert "set-cookie" not in rejected.headers

        missing = client.post(
            "/users/create",
            data=_multipart_fields("", "Blocked"),
        )
        assert missing.status_code == 403
        assert client.get("/users/table").text == before
        assert token in page.text


def test_duplicate_csrf_form_values_are_rejected_without_mutation() -> None:
    application = create_app()
    with TestClient(application) as client:
        token = _csrf_token(client.get("/users").text)
        before = client.get("/users/table").text
        response = client.post(
            "/users/create",
            content=urlencode(
                [
                    ("csrf_token", token),
                    ("csrf_token", token),
                    ("name", "Duplicate Evidence"),
                    ("status", "Active"),
                ]
            ),
            headers={"content-type": "application/x-www-form-urlencoded"},
        )

        assert response.status_code == 403
        assert client.get("/users/table").text == before


def test_invalid_htmx_and_ordinary_forms_redisplay_without_mutation() -> None:
    application = create_app()
    with TestClient(application) as raw_client:
        client = as_example_client(raw_client)
        token = _csrf_token(client.get("/users").text)
        before = client.get("/users/table").text
        fields = _multipart_fields(token, "", "Unknown")

        htmx = client.post(
            "/users/create",
            data=fields,
            headers={"HX-Request": "true"},
        )
        assert htmx.status_code == 422
        assert htmx.headers["hx-retarget"] == "#users-directory"
        assert htmx.headers["hx-reswap"] == "outerHTML"
        assert "Name is required." in htmx.text
        assert "Choose a valid status." in htmx.text
        assert 'id="users-directory"' in htmx.text
        assert 'data-layout="root"' not in htmx.text
        assert "hx-trigger" not in {key.lower() for key in htmx.headers}

        ordinary = client.post("/users/create", data=fields)
        assert ordinary.status_code == 422
        assert 'data-layout="root"' in ordinary.text
        assert 'data-layout="users"' in ordinary.text
        assert "Name is required." in ordinary.text
        assert client.get("/users/table").text == before


def test_successful_htmx_creation_captures_upload_and_headers() -> None:
    application = create_app()
    with TestClient(application) as raw_client:
        client = as_example_client(raw_client)
        token = _csrf_token(client.get("/users").text)
        response = client.post(
            "/users/create",
            data=_multipart_fields(token, "Lin Example"),
            files={"avatar": ("lin.txt", b"avatar", "text/plain")},
            headers={"HX-Request": "true"},
        )
        assert response.status_code == 200
        assert response.headers["hx-retarget"] == "#users-directory"
        assert response.headers["hx-reswap"] == "outerHTML"
        assert response.headers["hx-trigger"] == "contact:created"
        assert "Lin Example" in response.text
        assert "lin.txt" in response.text
        assert client.get("/users/table").text.count("Lin Example") == 1


def test_ordinary_success_redirect_and_isolated_dependencies() -> None:
    first_repository = ContactRepository()
    first = create_app(
        dependencies=Dependencies(
            first_repository,
            csrf.Guard(secret=b"first-secret-" + b"1" * 20),
        )
    )
    second = create_app(
        dependencies=Dependencies(
            ContactRepository(),
            csrf.Guard(secret=b"second-secret-" + b"2" * 20),
        )
    )
    with TestClient(first) as first_raw, TestClient(second) as second_raw:
        first_client = as_example_client(first_raw)
        second_client = as_example_client(second_raw)
        token = _csrf_token(first_client.get("/users").text)
        response = first_client.post(
            "/users/create",
            data=_multipart_fields(token, "Ordinary Contact"),
            follow_redirects=False,
        )
        assert response.status_code == 303
        assert response.headers["location"] == "/users"
        assert "Ordinary Contact" in first_client.get("/users").text
        assert "Ordinary Contact" not in second_client.get("/users").text


def test_upload_size_policy_rejects_without_mutation() -> None:
    application = create_app()
    with TestClient(application) as raw_client:
        client = as_example_client(raw_client)
        token = _csrf_token(client.get("/users").text)
        before = client.get("/users/table").text
        response = client.post(
            "/users/create",
            data=_multipart_fields(token, "Too Large"),
            files={"avatar": ("large.bin", b"x" * 65_537, "application/octet-stream")},
        )
        assert response.status_code == 413
        assert client.get("/users/table").text == before
