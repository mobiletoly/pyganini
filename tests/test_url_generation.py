# pyright: reportPrivateUsage=false

import dataclasses
import importlib
import os
import subprocess
import sys
from collections.abc import Callable, Generator
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from types import ModuleType
from typing import Any, cast

import pytest
from fastapi import FastAPI
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import PlainTextResponse
from starlette.routing import Mount, Route
from starlette.testclient import TestClient

from pyganini._cli import main
from pyganini._generation import GenerationError
from pyganini._paths import select_project_paths
from pyganini._route_graph import (
    ActionSurface,
    HandlerReference,
    NormalizedRoute,
    RouteGraph,
    RouteNode,
    SourcePosition,
    build_route_graph,
)
from pyganini._url_binding import bind_external_pattern, normalize_base_path
from pyganini._url_generation import _url_helper_projection, url_plan


def _package(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "__init__.py").write_text("", encoding="ascii")


def _route(directory: Path, source: str) -> None:
    _package(directory)
    (directory / "route.py").write_text(source, encoding="ascii")


def _write_url_tree(application: Path) -> None:
    routes = application / "app" / "routes"
    _route(
        routes,
        "from pyganini import action, route\n"
        "from starlette.responses import PlainTextResponse\n"
        "def page(request): return PlainTextResponse('root')\n"
        "def save(request): return PlainTextResponse('saved')\n"
        "Route = route(page=page, actions=(action('POST', '/', save),))\n",
    )
    users = routes / "users"
    _route(
        users,
        "from pyganini import action, fragment_route, route\n"
        "from starlette.responses import PlainTextResponse\n"
        "def page(request): return PlainTextResponse('users')\n"
        "def table(request): return PlainTextResponse('table')\n"
        "def save(request): return PlainTextResponse('saved')\n"
        "Route = route(\n"
        " page=page,\n"
        " fragments=(fragment_route('/table', table),),\n"
        " actions=(action('POST', '/', save), action('PATCH', '/save', save)),\n"
        ")\n",
    )
    _route(
        users / "by_user_id",
        "from pyganini import fragment_route, route\n"
        "from starlette.responses import PlainTextResponse\n"
        "def page(request): return PlainTextResponse('user')\n"
        "def profile(request): return PlainTextResponse('profile')\n"
        "Route = route(page=page, fragments=(fragment_route('/profile', profile),))\n",
    )
    _route(
        routes / "status_options",
        "from pyganini import route\n"
        "from starlette.responses import PlainTextResponse\n"
        "def page(request): return PlainTextResponse('status')\n"
        "Route = route(page=page)\n",
    )
    _route(
        routes / "reports",
        "from pyganini import kit_fragment_route, route_kit\n"
        "from starlette.responses import PlainTextResponse\n"
        "def create(request): return object()\n"
        "def page(kit, request): return PlainTextResponse('reports')\n"
        "def table(kit, request): return PlainTextResponse('table')\n"
        "Route = route_kit(\n"
        " create=create, page=page,\n"
        " fragments=(kit_fragment_route('/table', table),),\n"
        ")\n",
    )
    _route(
        routes / "indexed",
        "from pyganini import fragment_route, route\n"
        "from starlette.responses import PlainTextResponse\n"
        "def index(request): return PlainTextResponse('index')\n"
        "Route = route(fragments=(fragment_route('/', index),))\n",
    )

    organizations = routes / "organizations"
    organization = organizations / "by_organization_id"
    nested = organization / "users"
    _package(organizations)
    _package(organization)
    _package(nested)
    _route(
        nested / "by_user_id",
        "from pyganini import route\n"
        "from starlette.responses import PlainTextResponse\n"
        "def page(request): return PlainTextResponse('nested')\n"
        "Route = route(page=page)\n",
    )


def _write_self_parameter_tree(application: Path) -> None:
    routes = application / "app" / "routes"
    _route(
        routes,
        "from pyganini import route\n"
        "from starlette.responses import PlainTextResponse\n"
        "def page(request): return PlainTextResponse('root')\n"
        "Route = route(page=page)\n",
    )
    _route(
        routes / "by_self",
        "from pyganini import route\n"
        "from starlette.responses import PlainTextResponse\n"
        "def page(request): return PlainTextResponse('self')\n"
        "Route = route(page=page)\n",
    )


def _purge_application_modules() -> None:
    for name in tuple(sys.modules):
        if name == "app" or name.startswith("app."):
            del sys.modules[name]


@contextmanager
def _generated_urls(application: Path) -> Generator[ModuleType]:
    _purge_application_modules()
    sys.path.insert(0, str(application))
    importlib.invalidate_caches()
    try:
        yield importlib.import_module("app._pyganini.urls")
    finally:
        _purge_application_modules()
        sys.path.remove(str(application))
        importlib.invalidate_caches()


def _snapshot(root: Path) -> tuple[tuple[str, bytes | None, int], ...]:
    return tuple(
        (
            path.relative_to(root).as_posix(),
            path.read_bytes() if path.is_file() else None,
            path.stat().st_mtime_ns,
        )
        for path in sorted(root.rglob("*"))
    )


def test_url_plan_is_deterministic_ascii_and_stdlib_only(
    tmp_path: Path, make_app: Callable[..., Path]
) -> None:
    application = make_app(tmp_path / "application")
    _write_url_tree(application)
    paths = select_project_paths(explicit=application, start=application)
    graph = build_route_graph(paths)

    first = url_plan(graph)
    second = url_plan(graph)

    assert len(first) == 1
    assert first == second
    assert first[0].relative_path == PurePosixPath("app/_pyganini/urls.py")
    source = first[0].content
    assert source.decode("ascii").endswith("\n")
    assert b"\r" not in source
    assert b'__all__ = ("mount_urls", "urls")' in source
    assert b"from dataclasses import dataclass as _dataclass" in source
    assert b"from urllib.parse import quote as _quote" in source
    assert b"from app" not in source
    assert b"from pyganini" not in source
    assert b"from starlette" not in source
    assert b"from jinja2" not in source
    assert b"def _quote_segment(label: str, value: object) -> str:" in source
    assert b"def _normalize_base_path(base_path: object) -> str:" in source
    assert b"def by_user_id(self, user_id: str)" in source


def test_static_unmounted_urls_omit_unused_overload_import(
    tmp_path: Path, make_app: Callable[..., Path]
) -> None:
    application = make_app(tmp_path / "application")
    routes = application / "app" / "routes"
    _route(
        routes,
        "from pyganini import route\n"
        "def page(request): return None\n"
        "Route = route(page=page)\n",
    )

    graph = build_route_graph(select_project_paths(explicit=application))
    source = url_plan(graph)[0].content.decode("ascii")

    assert "overload as _overload" not in source


def test_shared_url_helper_projection_matches_generated_surface(
    tmp_path: Path, make_app: Callable[..., Path]
) -> None:
    application = make_app(tmp_path / "application")
    _write_url_tree(application)
    graph = build_route_graph(select_project_paths(explicit=application))

    projection = _url_helper_projection(graph)
    expressions = dict(projection.expressions)

    assert expressions["/"] == "urls.root.path"
    assert expressions["/users"] == "urls.users.path"
    assert expressions["/users/table"] == "urls.users.table.path"
    assert expressions["/users/{user_id}"] == "urls.users.by_user_id(user_id).path"
    assert expressions["/organizations/{organization_id}/users/{user_id}"] == (
        "urls.organizations.by_organization_id(organization_id).users."
        "by_user_id(user_id).path"
    )
    assert url_plan(graph)[0].content.endswith(b"\n")


def test_generated_urls_expose_route_shaped_paths_and_typed_base_surface(
    tmp_path: Path, make_app: Callable[..., Path]
) -> None:
    application = make_app(tmp_path / "application")
    _write_url_tree(application)
    assert main(["generate", "--app-root", str(application)]) == 0

    with _generated_urls(application) as generated:
        urls = generated.urls
        assert generated.__all__ == ("mount_urls", "urls")
        assert urls.root.path == "/"
        assert urls.users.path == "/users"
        assert urls.users.table.path == "/users/table"
        assert urls.users.by_user_id("42").path == "/users/42"
        assert urls.users.by_user_id(user_id="42").profile.path == ("/users/42/profile")
        assert urls.status_options.path == "/status-options"
        assert urls.indexed.path == "/indexed"
        assert (
            urls.organizations.by_organization_id("acme").users.by_user_id("42").path
            == "/organizations/acme/users/42"
        )
        assert not hasattr(urls.organizations, "path")
        assert not hasattr(urls.organizations.by_organization_id("acme"), "path")

        mounted = urls.with_base_path("/webapp")
        assert mounted.root.path == "/webapp/"
        assert mounted.users.path == "/webapp/users"
        assert mounted.users.by_user_id("42").profile.path == (
            "/webapp/users/42/profile"
        )
        assert urls.users.path == "/users"
        assert urls.with_base_path("").users.path == "/users"
        assert urls.with_base_path("/").users.path == "/users"
        assert urls.with_base_path("/webapp///").users.path == "/webapp/users"
        assert urls.with_base_path("team space").users.path == ("/team%20space/users")
        assert urls.with_base_path("/api/v1").users.path == "/api/v1/users"


def test_mounted_url_catalog_is_selection_filtered_and_owner_bound(
    tmp_path: Path, make_app: Callable[..., Path]
) -> None:
    application = make_app(tmp_path / "application")
    mounts = application / "app" / "mounts"
    _package(mounts)
    _route(
        mounts / "directory",
        "from pyganini import kit_fragment_route, route_kit\n"
        "from starlette.responses import PlainTextResponse\n"
        "def page(kit, request): return PlainTextResponse('page')\n"
        "def table(kit, request): return PlainTextResponse('table')\n"
        "Route = route_kit(\n"
        " page=page, fragments=(kit_fragment_route('/table', table),)\n"
        ")\n",
    )
    _route(
        mounts / "directory" / "create",
        "from pyganini import kit_action, route_kit\n"
        "from starlette.responses import PlainTextResponse\n"
        "def save(kit, request): return PlainTextResponse('saved')\n"
        "Route = route_kit(actions=(kit_action('POST', '/', save),))\n",
    )
    _route(
        application / "app" / "routes" / "users",
        "from pyganini import mount_route, route_mount\n"
        "def create(request): return object()\n"
        "Route = route_mount(\n"
        " create=create, mount='directory'\n"
        ")\n",
    )
    _package(application / "app" / "routes" / "settings")
    _route(
        application / "app" / "routes" / "settings" / "users",
        "from pyganini import mount_route, route_mount\n"
        "def create(request): return object()\n"
        "Route = route_mount(\n"
        " create=create, mount='directory', routes=(mount_route('/'),)\n"
        ")\n",
    )
    assert main(["generate", "--app-root", str(application)]) == 0

    with _generated_urls(application) as generated:
        users = generated.urls.users
        settings_users = generated.urls.settings.users
        directory = generated.mount_urls.directory.bind(users)
        settings_directory = generated.mount_urls.directory.bind(settings_users)
        assert directory.path == "/users"
        assert directory.table.path == "/users/table"
        assert directory.create.path == "/users/create"
        assert settings_directory.path == "/settings/users"
        assert settings_directory.table.path == "/settings/users/table"
        assert not hasattr(settings_directory, "create")
        with pytest.raises(ValueError):
            generated.mount_urls.directory.bind(generated.urls.settings)
        mounted = generated.urls.with_base_path("/proxy")
        assert generated.mount_urls.directory.bind(mounted.users).create.path == (
            "/proxy/users/create"
        )


def test_nested_mount_urls_bind_child_only_dynamic_owner_and_source_paths(
    tmp_path: Path, make_app: Callable[..., Path]
) -> None:
    application = make_app(tmp_path / "application")
    mounts = application / "app" / "mounts"
    _package(mounts)
    _package(mounts / "reports")
    source = mounts / "reports" / "audit"
    _package(source)
    _route(
        source,
        "from pyganini import route_kit\n"
        "def page(kit, request): return kit\n"
        "Route = route_kit(page=page)\n",
    )
    _route(
        source / "by_contact_id",
        "from pyganini import route_kit\n"
        "def page(kit, request): return kit\n"
        "Route = route_kit(page=page)\n",
    )
    live = application / "app" / "routes"
    _package(live / "organizations")
    _package(live / "organizations" / "by_org_id")
    owner = live / "organizations" / "by_org_id" / "users"
    _route(
        owner,
        "from pyganini import mount_route, route_mount\n"
        "def create(request): return object()\n"
        "Route = route_mount(\n"
        "    create=create, mount='reports/audit',\n"
        "    routes=(mount_route('/{contact_id}'),),\n"
        ")\n",
    )
    assert main(["generate", "--app-root", str(application)]) == 0

    with _generated_urls(application) as generated:
        live_owner = generated.urls.organizations.by_org_id("acme").users
        bound = generated.mount_urls.reports.audit.bind(live_owner)
        assert not hasattr(bound, "path")
        assert bound.by_contact_id("42").path == ("/organizations/acme/users/42")
        prefixed_owner = (
            generated.urls.with_base_path("/proxy")
            .organizations.by_org_id("acme")
            .users
        )
        assert (
            generated.mount_urls.reports.audit.bind(prefixed_owner)
            .by_contact_id("42")
            .path
            == "/proxy/organizations/acme/users/42"
        )
        with pytest.raises(ValueError, match="must not contain"):
            generated.urls.organizations.by_org_id("a/b")
        with pytest.raises(ValueError, match="must not contain"):
            bound.by_contact_id("a\\b")


@pytest.mark.parametrize("checker", ["mypy", "pyright"])
def test_mount_url_overloads_reject_wrong_owner_and_excluded_members(
    tmp_path: Path,
    make_app: Callable[..., Path],
    checker: str,
) -> None:
    application = make_app(tmp_path / "application")
    mounts = application / "app" / "mounts"
    _package(mounts)
    _route(
        mounts / "directory",
        "from pyganini import route_kit\n"
        "def page(kit, request): return kit\n"
        "Route = route_kit(page=page)\n",
    )
    _route(
        mounts / "directory" / "create",
        "from pyganini import kit_action, route_kit\n"
        "def save(kit, request): return kit\n"
        "Route = route_kit(actions=(kit_action('POST', '/', save),))\n",
    )
    _route(
        application / "app" / "routes" / "users",
        "from pyganini import mount_route, route_mount\n"
        "def create(request): return object()\n"
        "Route = route_mount(\n"
        " create=create, mount='directory', routes=(mount_route('/'),)\n"
        ")\n",
    )
    _route(
        application / "app" / "routes" / "administrators",
        "from pyganini import mount_route, route_mount\n"
        "def create(request): return object()\n"
        "Route = route_mount(\n"
        " create=create, mount='directory', routes=(mount_route('/create'),)\n"
        ")\n",
    )
    assert main(["generate", "--app-root", str(application)]) == 0
    generated = (application / "app" / "_pyganini" / "urls.py").read_text(
        encoding="ascii"
    )
    assert generated.count("    @_overload\n    def bind(self, owner:") == 2
    (application / "consumer.py").write_text(
        "from app._pyganini.urls import mount_urls, urls\n"
        "selected = mount_urls.directory.bind(urls.users)\n"
        "creator = mount_urls.directory.bind(urls.administrators)\n"
        "good: str = selected.path\n"
        "create_path: str = creator.create.path\n",
        encoding="ascii",
    )
    command = (
        [sys.executable, "-m", "mypy", "--strict", "consumer.py"]
        if checker == "mypy"
        else [str(Path(sys.executable).parent / "pyright"), "consumer.py"]
    )

    compatible = subprocess.run(
        command,
        cwd=application,
        check=False,
        capture_output=True,
        text=True,
    )

    assert compatible.returncode == 0, compatible.stdout + compatible.stderr

    (application / "consumer.py").write_text(
        "from app._pyganini.urls import mount_urls, urls\n"
        "selected = mount_urls.directory.bind(urls.users)\n"
        "bad = selected.create.path\n"
        "wrong = mount_urls.directory.bind(urls)\n",
        encoding="ascii",
    )
    result = subprocess.run(
        command,
        cwd=application,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    output = result.stdout + result.stderr
    assert "create" in output
    assert "bind" in output


def test_mounted_catalog_collision_reports_complete_pyganini016_evidence(
    tmp_path: Path, make_app: Callable[..., Path]
) -> None:
    application = make_app(tmp_path / "application")
    mounts = application / "app" / "mounts"
    _package(mounts)
    _route(
        mounts / "bind",
        "from pyganini import route_kit\n"
        "def page(kit, request): return kit\n"
        "Route = route_kit(page=page)\n",
    )
    _route(
        application / "app" / "routes" / "users",
        "from pyganini import route_mount\n"
        "def create(request): return object()\n"
        "Route = route_mount(create=create, mount='bind')\n",
    )
    graph = build_route_graph(select_project_paths(explicit=application))

    with pytest.raises(GenerationError) as raised:
        url_plan(graph)

    error = raised.value
    assert error.code == "PYGANINI016"
    assert error.phase == "url-interface"
    assert "evidence phase: url-interface" in error.details
    assert "live owner: app/routes/users/route.py" in error.details
    assert "mount identity: bind" in error.details
    assert "mounted source: app/mounts/bind/route.py" in error.details
    assert "selector: /" in error.details
    assert "final path: /users" in error.details


def test_kit_endpoints_use_the_same_route_shaped_url_helpers(
    tmp_path: Path, make_app: Callable[..., Path]
) -> None:
    application = make_app(tmp_path / "application")
    _write_url_tree(application)
    assert main(["generate", "--app-root", str(application)]) == 0

    with _generated_urls(application) as generated:
        assert generated.urls.reports.path == "/reports"
        assert generated.urls.reports.table.path == "/reports/table"
        assert type(generated.urls.reports.path) is type(generated.urls.users.path)
        assert not hasattr(generated.urls.reports, "create")


def test_self_dynamic_parameter_generates_importable_url_method(
    tmp_path: Path, make_app: Callable[..., Path]
) -> None:
    application = make_app(tmp_path / "application")
    _write_self_parameter_tree(application)
    assert main(["generate", "--app-root", str(application)]) == 0

    with _generated_urls(application) as generated:
        assert generated.urls.by_self(self="42").path == "/42"


@pytest.mark.parametrize(
    ("value", "error_type", "message"),
    [
        (cast(Any, 42), TypeError, "parameter 'user_id' must be str"),
        ("", ValueError, "parameter 'user_id' must not be empty"),
        (".", ValueError, "parameter 'user_id' must not be '.' or '..'"),
        ("..", ValueError, "parameter 'user_id' must not be '.' or '..'"),
        (
            "a/b",
            ValueError,
            "parameter 'user_id' must not contain '/' or '\\'",
        ),
        (
            "a\\b",
            ValueError,
            "parameter 'user_id' must not contain '/' or '\\'",
        ),
        (
            "a\x00b",
            ValueError,
            "parameter 'user_id' must not contain ASCII control characters",
        ),
        (
            "a\x7fb",
            ValueError,
            "parameter 'user_id' must not contain ASCII control characters",
        ),
        (
            "\ud800",
            ValueError,
            "parameter 'user_id' must contain valid Unicode text",
        ),
    ],
)
def test_dynamic_parameter_validation_messages(
    tmp_path: Path,
    make_app: Callable[..., Path],
    value: Any,
    error_type: type[Exception],
    message: str,
) -> None:
    application = make_app(tmp_path / "application")
    _write_url_tree(application)
    assert main(["generate", "--app-root", str(application)]) == 0

    with _generated_urls(application) as generated:
        with pytest.raises(error_type) as captured:
            generated.urls.users.by_user_id(value)
        assert str(captured.value) == message
        if "valid Unicode" in message:
            assert isinstance(captured.value.__cause__, UnicodeEncodeError)


def test_dynamic_quoting_and_base_path_validation(
    tmp_path: Path, make_app: Callable[..., Path]
) -> None:
    application = make_app(tmp_path / "application")
    _write_url_tree(application)
    assert main(["generate", "--app-root", str(application)]) == 0

    with _generated_urls(application) as generated:
        node = generated.urls.users.by_user_id
        assert node("42").path == "/users/42"
        assert node("a b").path == "/users/a%20b"
        assert node("a%2Fb").path == "/users/a%252Fb"
        assert node("cafe").path == "/users/cafe"
        assert node("caf\N{LATIN SMALL LETTER E WITH ACUTE}").path == (
            "/users/caf%C3%A9"
        )
        assert node("x?y#z").path == "/users/x%3Fy%23z"

        invalid_base_paths = (
            (cast(Any, 42), TypeError, "base_path must be str"),
            ("////", ValueError, "base_path must not contain empty path segments"),
            (
                "/webapp//v1",
                ValueError,
                "base_path must not contain empty path segments",
            ),
            ("/.", ValueError, "base_path segment 1 must not be '.' or '..'"),
            (
                "/webapp/..",
                ValueError,
                "base_path segment 2 must not be '.' or '..'",
            ),
            (
                "/webapp\\v1",
                ValueError,
                "base_path segment 1 must not contain '/' or '\\'",
            ),
            (
                "/webapp\x00",
                ValueError,
                "base_path segment 1 must not contain ASCII control characters",
            ),
            (
                "/\ud800",
                ValueError,
                "base_path segment 1 must contain valid Unicode text",
            ),
        )
        for value, error_type, message in invalid_base_paths:
            with pytest.raises(error_type) as captured:
                generated.urls.with_base_path(value)
            assert str(captured.value) == message
            if "valid Unicode" in message:
                assert isinstance(captured.value.__cause__, UnicodeEncodeError)

        assert generated.urls.with_base_path("/webapp/").users.path == ("/webapp/users")
        assert generated.urls.with_base_path("/webapp///").users.path == (
            "/webapp/users"
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            generated.urls._base_path = "/changed"


@pytest.mark.parametrize(
    ("base_path", "expected"),
    (
        ("", "/users/a%20b"),
        ("/", "/users/a%20b"),
        ("webapp", "/webapp/users/a%20b"),
        ("/webapp/", "/webapp/users/a%20b"),
        ("/team space", "/team%20space/users/a%20b"),
    ),
)
def test_private_external_binding_matches_generated_base_path_contract(
    tmp_path: Path,
    make_app: Callable[..., Path],
    base_path: str,
    expected: str,
) -> None:
    application = make_app(tmp_path / "application")
    _write_url_tree(application)
    assert main(["generate", "--app-root", str(application)]) == 0

    with _generated_urls(application) as generated:
        assert (
            normalize_base_path(base_path)
            == generated.urls.with_base_path(base_path)._base_path
        )
        assert (
            bind_external_pattern(
                "/users/{user_id}",
                {"user_id": "a b"},
                base_path=base_path,
            )
            == generated.urls.with_base_path(base_path).users.by_user_id("a b").path
        )
    assert expected == bind_external_pattern(
        "/users/{user_id}",
        {"user_id": "a b"},
        base_path=base_path,
    )


def _synthetic_page_node(
    directory: str, route_path: str, parameters: tuple[str, ...], line: int
) -> RouteNode:
    source_path = PurePosixPath(directory) / "route.py"
    source = SourcePosition(source_path, line, 1)
    handler = HandlerReference("app.routes.synthetic", "page", "page", source)
    declaration = NormalizedRoute(handler, None, (), ())
    return RouteNode(
        PurePosixPath(directory),
        "app.routes.synthetic",
        route_path,
        parameters,
        declaration,
        None,
    )


def _synthetic_page_action_node(directory: str, route_path: str) -> RouteNode:
    page_source = SourcePosition(PurePosixPath("app/routes/z/route.py"), 20, 1)
    action_source = SourcePosition(PurePosixPath("app/routes/a/route.py"), 4, 1)
    page = HandlerReference("app.routes.synthetic", "page", "page", page_source)
    action_handler = HandlerReference(
        "app.routes.synthetic", "save", "save", action_source
    )
    action = ActionSurface("POST", "/", action_handler, action_source, None)
    declaration = NormalizedRoute(page, None, (), (action,))
    return RouteNode(
        PurePosixPath(directory),
        "app.routes.synthetic",
        route_path,
        (),
        declaration,
        None,
    )


def test_helper_member_collision_is_pyganini016_with_owner_evidence() -> None:
    graph = RouteGraph(
        (
            _synthetic_page_node("app/routes/static", "/users/by-id", (), 4),
            _synthetic_page_node("app/routes/dynamic", "/users/{id}", ("id",), 7),
        )
    )

    with pytest.raises(GenerationError) as captured:
        url_plan(graph)

    error = captured.value
    assert error.code == "PYGANINI016"
    assert error.phase == "url-interface"
    assert "URL paths '/users/by-id' and '/users/{id}'" in error.message
    assert "both map to 'urls.users.by_id'" in error.message
    assert "app/routes/static/route.py:4:1" in error.message
    assert "app/routes/dynamic/route.py:7:1" in error.message


@pytest.mark.parametrize(
    ("route_directory", "expected"),
    [
        ("root", "reserved member 'root'"),
        ("with_base_path", "reserved member 'with_base_path'"),
        ("users/path", "reserved member 'path'"),
    ],
)
def test_reserved_url_members_are_pyganini016(
    route_directory: str,
    expected: str,
) -> None:
    graph = RouteGraph(
        (
            _synthetic_page_node(
                f"app/routes/{route_directory}",
                "/" + route_directory,
                (),
                4,
            ),
        )
    )

    with pytest.raises(GenerationError) as captured:
        url_plan(graph)

    assert captured.value.code == "PYGANINI016"
    assert expected in captured.value.message


def test_equivalent_graphs_have_equal_url_artifacts() -> None:
    nodes = (
        _synthetic_page_node("app/routes/z", "/z", (), 4),
        _synthetic_page_node("app/routes/a", "/a", (), 7),
        _synthetic_page_node("app/routes/users", "/users/{user_id}", ("user_id",), 10),
    )

    assert url_plan(RouteGraph(nodes)) == url_plan(RouteGraph(tuple(reversed(nodes))))


def test_url_diagnostics_are_ordered_independently_of_graph_input_order() -> None:
    nodes = (
        _synthetic_page_node("app/routes/users/dynamic", "/users/{id}", ("id",), 7),
        _synthetic_page_node("app/routes/class", "/class", (), 2),
        _synthetic_page_node("app/routes/users/static", "/users/by-id", (), 11),
    )

    def diagnostics(graph: RouteGraph) -> tuple[str, tuple[str, ...]]:
        with pytest.raises(GenerationError) as captured:
            url_plan(graph)
        return captured.value.message, captured.value.details

    assert diagnostics(RouteGraph(nodes)) == diagnostics(
        RouteGraph(tuple(reversed(nodes)))
    )


def test_same_path_endpoints_deduplicate_evidence_by_source_order() -> None:
    graph = RouteGraph(
        (_synthetic_page_action_node("app/routes/users/path", "/users/path"),)
    )

    with pytest.raises(GenerationError) as captured:
        url_plan(graph)

    error = captured.value
    assert error.path == "app/routes/a/route.py:4:1"
    assert "reserved member 'path'" in error.message
    assert error.details == ()


def test_reserved_descendant_ambiguity_is_reported_once() -> None:
    graph = RouteGraph(
        (
            _synthetic_page_node("app/routes/one", "/users/path/one", (), 4),
            _synthetic_page_node("app/routes/two", "/users/path/two", (), 7),
        )
    )

    with pytest.raises(GenerationError) as captured:
        url_plan(graph)

    error = captured.value
    assert error.path == "app/routes/one/route.py:4:1"
    assert "at 'urls.users'" in error.message
    assert error.details == ()


def test_descendant_static_dynamic_collision_is_reported_once() -> None:
    graph = RouteGraph(
        (
            _synthetic_page_node("app/routes/a/static", "/users/by-id/one", (), 4),
            _synthetic_page_node("app/routes/b/dynamic", "/users/{id}/one", ("id",), 7),
            _synthetic_page_node(
                "app/routes/c/dynamic", "/users/{id}/two", ("id",), 10
            ),
        )
    )

    with pytest.raises(GenerationError) as captured:
        url_plan(graph)

    error = captured.value
    assert error.path == "app/routes/a/static/route.py:4:1"
    assert "urls.users.by_id" in error.message
    assert error.details == ()


@pytest.mark.parametrize("command", ["generate", "check"])
def test_url_diagnostics_precede_generated_state_work(
    tmp_path: Path,
    make_app: Callable[..., Path],
    capsys: pytest.CaptureFixture[str],
    command: str,
) -> None:
    application = make_app(tmp_path / "application")
    assert main(["generate", "--app-root", str(application)]) == 0
    capsys.readouterr()
    bad = application / "app" / "routes" / "class"
    _route(
        bad,
        "from pyganini import route\n"
        "from starlette.responses import PlainTextResponse\n"
        "def page(request): return PlainTextResponse('bad')\n"
        "Route = route(page=page)\n",
    )
    path_bad = application / "app" / "routes" / "path"
    _route(
        path_bad,
        "from pyganini import route\n"
        "from starlette.responses import PlainTextResponse\n"
        "def page(request): return PlainTextResponse('bad')\n"
        "Route = route(page=page)\n",
    )
    dynamic_bad = application / "app" / "routes" / "by_class"
    _route(
        dynamic_bad,
        "from pyganini import route\n"
        "from starlette.responses import PlainTextResponse\n"
        "def page(request): return PlainTextResponse('bad')\n"
        "Route = route(page=page)\n",
    )
    before = _snapshot(application)

    assert main([command, "--app-root", str(application)]) == 1
    output = capsys.readouterr()
    assert output.out == ""
    assert "PYGANINI016 url-interface" in output.err
    assert "is a Python keyword" in output.err
    assert "dynamic parameter 'class'" in output.err
    assert "reserved member 'path'" in output.err
    assert _snapshot(application) == before


def _checker_run(
    checker: str, application: Path, sample: Path
) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(application)
    if checker == "pyright":
        (application / "pyrightconfig.json").write_text(
            '{"typeCheckingMode": "strict", "include": ["sample.py"]}\n',
            encoding="ascii",
        )
    command = [sys.executable, "-m", checker, str(sample)]
    if checker == "mypy":
        command.extend(["--strict", "--python-version", "3.13"])
    return subprocess.run(
        command,
        cwd=application,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )


def _sample_line(sample: Path, marker: str) -> int:
    return next(
        line_number
        for line_number, line in enumerate(
            sample.read_text(encoding="ascii").splitlines(), 1
        )
        if marker in line
    )


@pytest.mark.parametrize("checker", ["mypy", "pyright"])
def test_generated_urls_pass_both_locked_type_checkers(
    tmp_path: Path, make_app: Callable[..., Path], checker: str
) -> None:
    application = make_app(tmp_path / "application")
    _write_url_tree(application)
    assert main(["generate", "--app-root", str(application)]) == 0

    valid = application / "valid.py"
    valid.write_text(
        "from app._pyganini.urls import urls\n"
        "root_path: str = urls.root.path\n"
        "users_path: str = urls.users.path\n"
        "profile_path: str = urls.users.by_user_id(user_id='42').profile.path\n"
        "nested_path: str = (\n"
        "    urls.organizations.by_organization_id('acme')\n"
        "    .users.by_user_id('42').path\n"
        ")\n"
        "mounted_path: str = (\n"
        "    urls.with_base_path('/webapp').users.by_user_id('42').path\n"
        ")\n",
        encoding="ascii",
    )
    sys.modules.pop("valid", None)
    with _generated_urls(application) as generated:
        consumer = importlib.import_module("valid")
        try:
            assert consumer.root_path == generated.urls.root.path == "/"
            assert consumer.users_path == generated.urls.users.path == "/users"
            assert (
                consumer.profile_path
                == generated.urls.users.by_user_id("42").profile.path
                == "/users/42/profile"
            )
            nested_path = (
                generated.urls.organizations.by_organization_id("acme")
                .users.by_user_id("42")
                .path
            )
            assert (
                consumer.nested_path == nested_path == ("/organizations/acme/users/42")
            )
            mounted_path = (
                generated.urls.with_base_path("/webapp").users.by_user_id("42").path
            )
            assert consumer.mounted_path == mounted_path == "/webapp/users/42"
        finally:
            sys.modules.pop("valid", None)
    valid_result = _checker_run(checker, application, valid)
    assert valid_result.returncode == 0, valid_result.stdout + valid_result.stderr

    invalid = application / "sample.py"
    invalid.write_text(
        "from app._pyganini.urls import urls\n"
        "urls.users.by_user_id()  # MISSING_PARAMETER\n"
        "urls.users.by_user_id(extra='42')  # UNKNOWN_PARAMETER\n"
        "urls.users.by_user_id(42)  # WRONG_PARAMETER_TYPE\n"
        "urls.not_a_route  # UNKNOWN_ROUTE\n"
        "urls.organizations.path  # NAMESPACE_PATH\n",
        encoding="ascii",
    )
    invalid_result = _checker_run(checker, application, invalid)
    output = invalid_result.stdout + invalid_result.stderr
    assert invalid_result.returncode != 0
    for marker in (
        "MISSING_PARAMETER",
        "UNKNOWN_PARAMETER",
        "WRONG_PARAMETER_TYPE",
        "UNKNOWN_ROUTE",
        "NAMESPACE_PATH",
    ):
        assert f":{_sample_line(invalid, marker)}:" in output


def test_unbound_nested_dynamic_target_cannot_skip_ancestor_binding(
    tmp_path: Path,
    make_app: Callable[..., Path],
) -> None:
    application = make_app(tmp_path / "application")
    _write_url_tree(application)
    routes = application / "app" / "routes"
    (routes / "route.py").write_text(
        "from app._pyganini.urls import urls\n"
        "from pyganini import RouteNav, route, to\n"
        "from starlette.responses import PlainTextResponse\n"
        "def page(request): return PlainTextResponse('root')\n"
        "Route = route(\n"
        "    page=page,\n"
        "    nav=RouteNav(label='Home'),\n"
        "    destinations=(to(\n"
        "        'nested-user',\n"
        "        urls.organizations.by_organization_id.users.by_user_id,\n"
        "        trail_key='from-home',\n"
        "    ),),\n"
        ")\n",
        encoding="ascii",
    )
    assert main(["generate", "--app-root", str(application)]) == 0

    with _generated_urls(application) as generated, pytest.raises(TypeError):
        generated.urls.organizations.by_organization_id.users.by_user_id("42")


@pytest.mark.parametrize("checker", ["mypy", "pyright"])
def test_generated_navigation_urls_pass_both_locked_type_checkers(
    tmp_path: Path, make_app: Callable[..., Path], checker: str
) -> None:
    application = make_app(tmp_path / "application")
    routes = application / "app" / "routes"
    _route(
        routes,
        "from app._pyganini.urls import urls\n"
        "from pyganini import RouteNav, route, to\n"
        "from starlette.responses import PlainTextResponse\n"
        "def page(request): return PlainTextResponse('root')\n"
        "Route = route(\n"
        "    page=page,\n"
        "    nav=RouteNav(label='Home'),\n"
        "    destinations=(\n"
        "        to('report-detail', urls.users.by_user_id, trail_key='from-home'),\n"
        "        to('plain-user', urls.users.by_user_id),\n"
        "        to('self-instance', urls.items.by_self.by_instance),\n"
        "    ),\n"
        ")\n",
    )
    _package(routes / "users")
    _route(
        routes / "users" / "by_user_id",
        "from pyganini import RouteNav, route\n"
        "from starlette.responses import PlainTextResponse\n"
        "def page(request): return PlainTextResponse('user')\n"
        "Route = route(page=page, nav=RouteNav(key='user'))\n",
    )
    _package(routes / "organizations")
    _package(routes / "organizations" / "by_organization_id")
    _package(routes / "organizations" / "by_organization_id" / "users")
    _route(
        routes / "organizations" / "by_organization_id" / "users" / "by_user_id",
        "from pyganini import RouteNav, route\n"
        "from starlette.responses import PlainTextResponse\n"
        "def page(request): return PlainTextResponse('nested user')\n"
        "Route = route(page=page, nav=RouteNav(key='nested_user'))\n",
    )
    _package(routes / "items")
    _package(routes / "items" / "by_self")
    _route(
        routes / "items" / "by_self" / "by_instance",
        "from pyganini import route\n"
        "from starlette.responses import PlainTextResponse\n"
        "def page(request): return PlainTextResponse('item')\n"
        "Route = route(page=page)\n",
    )
    assert main(["generate", "--app-root", str(application)]) == 0

    valid = application / "navigation_valid.py"
    valid.write_text(
        "from pyganini import Navigation, RouteTarget\n"
        "from app._pyganini.urls import urls\n"
        "target: RouteTarget = urls.users.by_user_id\n"
        "pattern: str = target.route_pattern\n"
        "bound_path: str = urls.users.by_user_id(user_id='42').path\n"
        "nested_path: str = (\n"
        "    urls.organizations.by_organization_id('acme')\n"
        "    .users.by_user_id('42').path\n"
        ")\n"
        "self_instance: str = urls.destinations.self_instance(\n"
        "    'left', 'right'\n"
        ").href\n"
        "with_return: str = urls.destinations.report_detail(\n"
        "    user_id='42'\n"
        ").navigation_href(Navigation())\n"
        "plain: str = urls.destinations.plain_user(user_id='42').href\n"
        "trail_key: str = urls.users.by_user_id.trail_keys.from_home\n",
        encoding="ascii",
    )
    valid_result = _checker_run(checker, application, valid)
    assert valid_result.returncode == 0, valid_result.stdout + valid_result.stderr

    invalid = application / "navigation_invalid.py"
    invalid.write_text(
        "from pyganini import Navigation\n"
        "from app._pyganini.urls import urls\n"
        "urls.destinations.report_detail()  # MISSING_PARAMETER\n"
        "urls.destinations.report_detail(extra='42')  # UNKNOWN_PARAMETER\n"
        "urls.destinations.report_detail(42)  # WRONG_PARAMETER_TYPE\n"
        "urls.destinations.plain_user(user_id='42').navigation_href("
        "Navigation())  # NO_NAVIGATION_HREF\n"
        "urls.users.by_user_id.trail_keys.missing  # UNKNOWN_TRAIL_KEY\n"
        "urls.organizations.by_organization_id.users.by_user_id('42')  # "
        "UNBOUND_ANCESTOR\n",
        encoding="ascii",
    )
    invalid_result = _checker_run(checker, application, invalid)
    output = invalid_result.stdout + invalid_result.stderr
    assert invalid_result.returncode != 0
    for marker in (
        "MISSING_PARAMETER",
        "UNKNOWN_PARAMETER",
        "WRONG_PARAMETER_TYPE",
        "NO_NAVIGATION_HREF",
        "UNKNOWN_TRAIL_KEY",
        "UNBOUND_ANCESTOR",
    ):
        assert f":{_sample_line(invalid, marker)}:" in output


def test_empty_graph_generates_typed_empty_url_surface(
    tmp_path: Path, make_app: Callable[..., Path]
) -> None:
    application = make_app(tmp_path / "application")
    assert main(["generate", "--app-root", str(application)]) == 0

    with _generated_urls(application) as generated:
        assert generated.urls.with_base_path("/app") is not generated.urls
        assert not hasattr(generated.urls, "root")
        assert not hasattr(generated.urls, "path")


def test_check_reports_stale_and_obsolete_url_entries_without_writing(
    tmp_path: Path,
    make_app: Callable[..., Path],
    capsys: pytest.CaptureFixture[str],
) -> None:
    application = make_app(tmp_path / "application")
    _write_url_tree(application)
    assert main(["generate", "--app-root", str(application)]) == 0
    capsys.readouterr()
    generated = application / "app" / "_pyganini"
    (generated / "urls.py").write_text("stale\n", encoding="ascii")
    (generated / "urls.pyi").write_text("obsolete\n", encoding="ascii")
    before = _snapshot(application)

    assert main(["check", "--app-root", str(application)]) == 1
    output = capsys.readouterr()
    assert output.out == ""
    assert "app/_pyganini/urls.py: PYGANINI005 generated-state" in output.err
    assert "app/_pyganini/urls.pyi: PYGANINI005 generated-state" in output.err
    assert _snapshot(application) == before


def test_starlette_and_fastapi_hosts_pass_decoded_root_path_explicitly(
    tmp_path: Path, make_app: Callable[..., Path]
) -> None:
    application = make_app(tmp_path / "application")
    _write_url_tree(application)
    assert main(["generate", "--app-root", str(application)]) == 0

    with _generated_urls(application) as generated:
        urls = generated.urls

        async def show_url(request: Request) -> PlainTextResponse:
            base_path = request.scope.get("root_path", "")
            return PlainTextResponse(urls.with_base_path(base_path).users.path)

        inner = Starlette(routes=[Route("/url", show_url)])
        starlette_host = Starlette(routes=[Mount("/html", inner)])
        with TestClient(
            starlette_host,
            base_url="http://testserver/proxy",
            root_path="/proxy",
        ) as client:
            assert client.get("/html/url").text == "/proxy/html/users"

        fastapi_host = FastAPI()
        fastapi_host.mount("/html", inner)
        with TestClient(
            fastapi_host,
            base_url="http://testserver/proxy",
            root_path="/proxy",
        ) as client:
            assert client.get("/html/url").text == "/proxy/html/users"
