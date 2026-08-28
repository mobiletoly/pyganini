# pyright: reportPrivateUsage=false

import os
import re
import subprocess
import sys
from collections.abc import Callable
from contextlib import suppress
from dataclasses import FrozenInstanceError
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

import pyganini._route_graph as route_graph_module
from pyganini._paths import select_project_paths
from pyganini._route_graph import (
    RouteDiagnostic,
    RouteGraph,
    RouteGraphError,
    build_route_graph,
    iter_endpoints,
)
from pyganini.request_data import FormCapture


def _package(root: Path, relative: str) -> Path:
    package = root / "app" / "routes" / relative
    package.mkdir(parents=True, exist_ok=True)
    (package / "__init__.py").write_text("", encoding="ascii")
    return package


def _route(package: Path, source: str) -> None:
    (package / "route.py").write_text(source, encoding="ascii")


def _graph(application: Path) -> RouteGraph:
    paths = select_project_paths(explicit=application)
    return build_route_graph(paths)


def _diagnostics(application: Path) -> tuple[RouteDiagnostic, ...]:
    with pytest.raises(RouteGraphError) as raised:
        _graph(application)
    return raised.value.diagnostics


def test_root_error_templates_are_graph_facts_without_an_endpoint(
    tmp_path: Path, make_app: Callable[..., Path]
) -> None:
    application = make_app(tmp_path / "application")
    routes = application / "app" / "routes"
    (routes / "error_page.jinja").write_text("error page\n", encoding="ascii")
    (routes / "error_fragment.jinja").write_text("error fragment\n", encoding="ascii")
    _route(
        routes,
        "from pyganini import route\n"
        "Route = route(\n"
        "    error_page_template='error_page.jinja',\n"
        "    error_fragment_template='error_fragment.jinja',\n"
        ")\n",
    )

    graph = _graph(application)
    root = graph.nodes[0]

    assert tuple(iter_endpoints(graph)) == ()
    assert root.error_page_template is not None
    assert root.error_page_template.environment_name == "routes/error_page.jinja"
    assert root.error_fragment_template is not None
    assert (
        root.error_fragment_template.environment_name == "routes/error_fragment.jinja"
    )


def test_static_route_metadata_is_source_positioned_and_inherited_by_mounts(
    tmp_path: Path, make_app: Callable[..., Path]
) -> None:
    application = make_app(tmp_path / "application")
    users = _package(application, "users")
    _route(
        users,
        "from pyganini import RouteMeta, route\n"
        "def page(request): return request\n"
        "Route = route(\n"
        "    page=page, name='users.index', title='Users',\n"
        "    meta=RouteMeta(labels={'zeta': 'last', 'alpha': 'first'}),\n"
        ")\n",
    )
    owner = _package(application, "directory")
    _route(
        owner,
        "from pyganini import route_mount\n"
        "def create(request): return object()\n"
        "Route = route_mount(create=create, mount='directory')\n",
    )
    mounts = application / "app" / "mounts"
    mounts.mkdir()
    (mounts / "__init__.py").write_text("", encoding="ascii")
    source = mounts / "directory"
    source.mkdir()
    (source / "__init__.py").write_text("", encoding="ascii")
    _route(
        source,
        "from pyganini import RouteMeta, route_kit\n"
        "def page(kit, request): return request\n"
        "Route = route_kit(\n"
        "    page=page, name='directory.index', title='Directory',\n"
        "    meta=RouteMeta(labels={'area': 'contacts'}),\n"
        ")\n",
    )

    graph = _graph(application)
    ordinary = next(node for node in graph.nodes if node.route_path == "/users")
    mounted = next(node for node in graph.nodes if node.mount == "directory")

    assert ordinary.declaration is not None
    assert ordinary.declaration.metadata is not None
    assert ordinary.declaration.metadata.name == "users.index"
    assert ordinary.declaration.metadata.title == "Users"
    assert [label.key for label in ordinary.declaration.metadata.labels] == [
        "alpha",
        "zeta",
    ]
    assert all(
        label.source.path.as_posix() == "app/routes/users/route.py"
        for label in ordinary.declaration.metadata.labels
    )
    assert mounted.declaration is not None
    assert mounted.declaration.metadata is not None
    assert mounted.declaration.metadata.name == "directory.index"
    assert mounted.declaration.metadata.labels[0].value == "contacts"
    assert graph.mounted_candidates[0].included is True
    assert graph.mounted_candidates[0].declaration.metadata is not None


@pytest.mark.parametrize(
    ("metadata", "field"),
    [
        ("name=''", "name"),
        ("title='Users' ' page'", "title"),
        ("meta=RouteMeta({'area': 'admin'})", "meta"),
        ("meta=RouteMeta(labels=dict(area='admin'))", "meta"),
        ("meta=RouteMeta(labels={**labels})", "meta"),
        ("meta=RouteMeta(labels={'': 'admin'})", "meta"),
        ("meta=RouteMeta(labels={'area': 1})", "meta"),
        ("meta=RouteMeta(labels={'area': 'one', 'area': 'two'})", "meta"),
    ],
)
def test_static_route_metadata_grammar_fails_closed(
    tmp_path: Path,
    make_app: Callable[..., Path],
    metadata: str,
    field: str,
) -> None:
    application = make_app(tmp_path / "application")
    users = _package(application, "users")
    _route(
        users,
        "from pyganini import RouteMeta, route\n"
        "labels = {'area': 'admin'}\n"
        "def page(request): return request\n"
        f"Route = route(page=page, {metadata})\n",
    )

    diagnostic = _diagnostics(application)[0]

    assert diagnostic.code == "PYGANINI010"
    assert diagnostic.field == field


def test_static_route_metadata_rejects_endpoint_free_error_root(
    tmp_path: Path, make_app: Callable[..., Path]
) -> None:
    application = make_app(tmp_path / "application")
    routes = application / "app" / "routes"
    (routes / "error_page.jinja").write_text("error\n", encoding="ascii")
    _route(
        routes,
        "from pyganini import route\n"
        "Route = route(name='errors', error_page_template='error_page.jinja')\n",
    )

    diagnostic = _diagnostics(application)[0]

    assert diagnostic.code == "PYGANINI010"
    assert diagnostic.field == "Route"
    assert "metadata requires" in diagnostic.message


@pytest.mark.parametrize("owner_kind", ["kit", "mount"])
def test_kit_and_mounted_live_roots_retain_error_graph_facts(
    tmp_path: Path, make_app: Callable[..., Path], owner_kind: str
) -> None:
    application = make_app(tmp_path / "application")
    routes = application / "app" / "routes"
    (routes / "error_page.jinja").write_text("error page\n", encoding="ascii")
    (routes / "error_fragment.jinja").write_text("error fragment\n", encoding="ascii")
    if owner_kind == "kit":
        _route(
            routes,
            "from pyganini import route_kit\n"
            "def create(request): return object()\n"
            "def page(kit, request): return request\n"
            "Route = route_kit(\n"
            "    create=create, page=page,\n"
            "    error_page_template='error_page.jinja',\n"
            "    error_fragment_template='error_fragment.jinja',\n"
            ")\n",
        )
    else:
        mounts = application / "app" / "mounts"
        mounts.mkdir()
        (mounts / "__init__.py").write_text("", encoding="ascii")
        source = mounts / "source"
        source.mkdir()
        (source / "__init__.py").write_text("", encoding="ascii")
        _route(
            source,
            "from pyganini import route_kit\n"
            "def page(kit, request): return request\n"
            "Route = route_kit(page=page)\n",
        )
        _route(
            routes,
            "from pyganini import route_mount\n"
            "def create(request): return object()\n"
            "Route = route_mount(\n"
            "    create=create, mount='source',\n"
            "    error_page_template='error_page.jinja',\n"
            "    error_fragment_template='error_fragment.jinja',\n"
            ")\n",
        )

    graph = _graph(application)
    root = next(
        node
        for node in graph.nodes
        if node.mount is None
        and node.owner is not None
        and node.owner.path.as_posix() == "app/routes/route.py"
    )

    assert root.error_page_template is not None
    assert root.error_page_template.environment_name == "routes/error_page.jinja"
    assert root.error_fragment_template is not None
    assert (
        root.error_fragment_template.environment_name == "routes/error_fragment.jinja"
    )


@pytest.mark.parametrize("context", ["descendant", "mounted"])
def test_error_templates_outside_the_live_root_fail_closed(
    tmp_path: Path, make_app: Callable[..., Path], context: str
) -> None:
    application = make_app(tmp_path / "application")
    if context == "descendant":
        package = _package(application, "users")
    else:
        mounts = application / "app" / "mounts"
        mounts.mkdir()
        (mounts / "__init__.py").write_text("", encoding="ascii")
        package = mounts / "source"
        package.mkdir()
        (package / "__init__.py").write_text("", encoding="ascii")
        owner = application / "app" / "routes"
        _route(
            owner,
            "from pyganini import route_mount\n"
            "def create(request): return object()\n"
            "Route = route_mount(create=create, mount='source')\n",
        )
    (package / "error_page.jinja").write_text("error\n", encoding="ascii")
    _route(
        package,
        "from pyganini import route_kit\n"
        "def create(request): return object()\n"
        "def page(kit, request): return request\n"
        "Route = route_kit(\n"
        + ("    create=create,\n" if context == "descendant" else "")
        + "    page=page,\n"
        "    error_page_template='error_page.jinja',\n"
        ")\n",
    )

    diagnostic = next(
        item
        for item in _diagnostics(application)
        if item.field == "error_page_template"
    )

    assert diagnostic.code == "PYGANINI010"
    assert diagnostic.message.startswith(
        "error templates may be declared only by app/routes/route.py"
    )


def test_live_middleware_markers_are_recorded_in_root_to_owner_order(
    tmp_path: Path, make_app: Callable[..., Path]
) -> None:
    application = make_app(tmp_path / "application")
    routes = application / "app" / "routes"
    (routes / "middleware.py").write_text(
        "MIDDLEWARE = (outer, outer_two)\n", encoding="ascii"
    )
    _route(
        routes,
        "from pyganini import route\n"
        "def page(request): return request\n"
        "Route = route(page=page)\n",
    )
    users = _package(application, "users")
    (users / "middleware.py").write_text("MIDDLEWARE = (inner,)\n", encoding="ascii")
    _route(
        users,
        "from pyganini import route\n"
        "def page(request): return request\n"
        "Route = route(page=page)\n",
    )

    graph = _graph(application)

    root = next(node for node in graph.nodes if node.route_path == "/")
    users_node = next(node for node in graph.nodes if node.route_path == "/users")
    assert root.middleware is not None
    assert users_node.middleware is not None
    assert [item.source.path.as_posix() for item in root.middleware_chain] == [
        "app/routes/middleware.py"
    ]
    assert [item.source.path.as_posix() for item in users_node.middleware_chain] == [
        "app/routes/middleware.py",
        "app/routes/users/middleware.py",
    ]
    assert [
        item.source.path.as_posix() for item in users_node.middleware_chain[0].entries
    ] == [
        "app/routes/middleware.py",
        "app/routes/middleware.py",
    ]


@pytest.mark.parametrize(
    "middleware_source",
    [
        "MIDDLEWARE = ()\n",
        "MIDDLEWARE = (*items,)\n",
        "if enabled:\n    MIDDLEWARE = (item,)\n",
        "MIDDLEWARE = (item,)\nMIDDLEWARE = (other,)\n",
        "MIDDLEWARE = (item,)\ndel MIDDLEWARE\n",
    ],
)
def test_live_middleware_binding_grammar_fails_closed(
    tmp_path: Path,
    make_app: Callable[..., Path],
    middleware_source: str,
) -> None:
    application = make_app(tmp_path / "application")
    routes = application / "app" / "routes"
    (routes / "middleware.py").write_text(middleware_source, encoding="ascii")

    diagnostic = _diagnostics(application)[0]

    assert diagnostic.code == "PYGANINI010"
    assert diagnostic.field == "MIDDLEWARE"


def test_same_path_methods_with_different_middleware_chains_fail_closed(
    tmp_path: Path, make_app: Callable[..., Path]
) -> None:
    application = make_app(tmp_path / "application")
    routes = application / "app" / "routes"
    (routes / "middleware.py").write_text("MIDDLEWARE = (outer,)\n", encoding="ascii")
    _route(
        routes,
        "from pyganini import action, route\n"
        "def save(request): return request\n"
        "Route = route(actions=(action('POST', '/users', save),))\n",
    )
    users = _package(application, "users")
    (users / "middleware.py").write_text("MIDDLEWARE = (inner,)\n", encoding="ascii")
    _route(
        users,
        "from pyganini import route\n"
        "def page(request): return request\n"
        "Route = route(page=page)\n",
    )

    diagnostics = _diagnostics(application)

    middleware = next(item for item in diagnostics if item.field == "middleware")
    assert middleware.code == "PYGANINI011"
    assert middleware.phase == "route-collision"
    assert "normalized path: /users" in middleware.message
    assert "POST" in middleware.message
    assert "GET" in middleware.message
    assert "app/routes/middleware.py" in middleware.message
    assert "app/routes/users/middleware.py" in middleware.message


def test_mounted_endpoint_uses_only_the_live_owner_middleware_chain(
    tmp_path: Path, make_app: Callable[..., Path]
) -> None:
    application = make_app(tmp_path / "application")
    routes = application / "app" / "routes"
    (routes / "middleware.py").write_text("MIDDLEWARE = (outer,)\n", encoding="ascii")
    owner = _package(application, "users")
    (owner / "middleware.py").write_text("MIDDLEWARE = (owner,)\n", encoding="ascii")
    _route(
        owner,
        "from pyganini import route_mount\n"
        "def create(request): return object()\n"
        "Route = route_mount(create=create, mount='directory')\n",
    )
    source = application / "app" / "mounts" / "directory"
    source.mkdir(parents=True)
    (application / "app" / "mounts" / "__init__.py").write_text("", encoding="ascii")
    (source / "__init__.py").write_text("", encoding="ascii")
    (source / "page.jinja").write_text("{{ child }}\n", encoding="ascii")
    _route(
        source,
        "from pyganini import route_kit\n"
        "def page(kit, request): return kit\n"
        "Route = route_kit(page=page, template='page.jinja')\n",
    )

    graph = _graph(application)
    endpoint = next(iter(iter_endpoints(graph)))
    node = next(item for item in graph.nodes if item.mount is not None)

    assert endpoint.path == "/users"
    assert [marker.source.path.as_posix() for marker in node.middleware_chain] == [
        "app/routes/middleware.py",
        "app/routes/users/middleware.py",
    ]


def test_action_request_data_is_normalized_on_the_canonical_endpoint(
    tmp_path: Path, make_app: Callable[..., Path]
) -> None:
    application = make_app(tmp_path / "application")
    package = _package(application, "users")
    _route(
        package,
        "from pyganini import action, route\n"
        "from pyganini.request_data import capture_form\n"
        "def save(request, form): return object()\n"
        "Route = route(actions=(action(\n"
        "    'POST', '/save', save,\n"
        "    request_data=capture_form(\n"
        "        max_files=1, max_fields=2, max_part_size=64,\n"
        "        max_upload_size=128),\n"
        "),))\n",
    )

    endpoint = next(iter(iter_endpoints(_graph(application))))

    assert endpoint.request_data == FormCapture(1, 2, 64, 128)
    assert endpoint.request_data_source is not None
    assert endpoint.request_data_source.path.as_posix() == "app/routes/users/route.py"


@pytest.mark.parametrize(
    "request_data",
    [
        "capture_body(10)",
        "capture_body(max_bytes=limit)",
        "capture_body(max_bytes=True)",
        "request_data.capture_body(max_bytes=10)",
        (
            "capture_form(max_files=1, max_fields=1, max_part_size=1, "
            "max_upload_size=1, extra=1)"
        ),
    ],
)
def test_action_request_data_static_grammar_fails_closed(
    tmp_path: Path, make_app: Callable[..., Path], request_data: str
) -> None:
    application = make_app(tmp_path / "application")
    package = _package(application, "users")
    _route(
        package,
        "from pyganini import action, route\n"
        "from pyganini.request_data import capture_body, capture_form\n"
        "limit = 10\n"
        "def save(request, data): return object()\n"
        "Route = route(actions=(action(\n"
        "    'POST', '/save', save, request_data=" + request_data + "),))\n",
    )

    diagnostic = _diagnostics(application)[0]

    assert diagnostic.code == "PYGANINI010"
    assert diagnostic.field == "request_data"


@pytest.mark.parametrize("definition", ["def", "async def"])
def test_capture_constructor_shadowing_fails_closed(
    tmp_path: Path, make_app: Callable[..., Path], definition: str
) -> None:
    application = make_app(tmp_path / "application")
    package = _package(application, "users")
    _route(
        package,
        "from pyganini import action, route\n"
        "from pyganini.request_data import BodyCapture, capture_body\n"
        f"{definition} capture_body(*, max_bytes):\n"
        "    return BodyCapture(max_bytes)\n"
        "def save(request, data): return object()\n"
        "Route = route(actions=(action(\n"
        "    'POST', '/save', save,\n"
        "    request_data=capture_body(max_bytes=4)),))\n",
    )

    diagnostics = _diagnostics(application)

    assert diagnostics
    assert diagnostics[0].code == "PYGANINI010"
    assert diagnostics[0].field == "request_data"


@pytest.mark.parametrize(
    "route_source",
    [
        (
            "from pyganini import route_mount\n"
            "def create(request): return object()\n"
            "Route = route_mount(create=create, mount='contact_' 'directory')\n"
        ),
        (
            "from pyganini import mount_route, route_mount\n"
            "def create(request): return object()\n"
            "Route = route_mount(\n"
            "    create=create, mount='contact_directory',\n"
            "    routes=(mount_route('/' 'create'),),\n"
            ")\n"
        ),
    ],
)
def test_mounted_static_grammar_rejects_adjacent_string_literals(
    tmp_path: Path,
    make_app: Callable[..., Path],
    route_source: str,
) -> None:
    application = make_app(tmp_path / "application")
    owner = _package(application, "users")
    _route(owner, route_source)

    diagnostic = _diagnostics(application)[0]

    assert diagnostic.code == "PYGANINI010"
    assert "one direct string literal" in diagnostic.message
    assert "concatenation is unsupported" in diagnostic.message


def test_mounted_source_expands_only_selected_declarations_with_owner_evidence(
    tmp_path: Path, make_app: Callable[..., Path]
) -> None:
    application = make_app(tmp_path / "application")
    mount_root = application / "app" / "mounts" / "directory"
    mount_root.mkdir(parents=True)
    (application / "app" / "mounts" / "__init__.py").write_text("", encoding="ascii")
    (mount_root / "__init__.py").write_text("", encoding="ascii")
    (mount_root / "page.jinja").write_text(
        "<main>{{ child }}</main>\n", encoding="ascii"
    )
    _route(
        mount_root,
        "from pyganini import route_kit\n"
        "def page(kit, request): return kit\n"
        "Route = route_kit(page=page, template='page.jinja')\n",
    )
    selected = _package(application, "users")
    _route(
        selected,
        "from pyganini import mount_route, route_mount\n"
        "def create(request): return object()\n"
        "Route = route_mount(\n"
        "    create=create, mount='directory', routes=(mount_route('/'),)\n"
        ")\n",
    )

    graph = _graph(application)

    assert [node.route_path for node in graph.nodes] == ["/", "/users", "/users"]
    assert graph.nodes[2].declaration is None
    assert graph.mount_owners[0].mount == "directory"
    assert graph.mounted_bindings[0].source_path == "/"
    assert graph.mounted_bindings[0].final_path == "/users"
    assert next(iter(iter_endpoints(graph))).path == "/users"


def test_mounted_selection_excludes_source_declarations_and_ignores_unreferenced(
    tmp_path: Path, make_app: Callable[..., Path]
) -> None:
    application = make_app(tmp_path / "application")
    mounts = application / "app" / "mounts"
    mount_root = mounts / "directory"
    mount_root.mkdir(parents=True)
    (mounts / "__init__.py").write_text("", encoding="ascii")
    (mount_root / "__init__.py").write_text("", encoding="ascii")
    (mount_root / "page.jinja").write_text("{{ child }}\n", encoding="ascii")
    _route(
        mount_root,
        "from pyganini import kit_action, route_kit\n"
        "def page(kit, request): return kit\n"
        "Route = route_kit(page=page, template='page.jinja')\n",
    )
    create = mount_root / "create"
    create.mkdir()
    (create / "__init__.py").write_text("", encoding="ascii")
    _route(
        create,
        "from pyganini import kit_action, route_kit\n"
        "def save(kit, request): return kit\n"
        "Route = route_kit(actions=(kit_action('POST', '/', save),))\n",
    )
    unused = mounts / "unused"
    unused.mkdir()
    (unused / "route.py").write_text("not valid route source\n", encoding="ascii")
    owner = _package(application, "users")
    _route(
        owner,
        "from pyganini import mount_route, route_mount\n"
        "def create(request): return object()\n"
        "Route = route_mount(\n"
        "    create=create, mount='directory', routes=(mount_route('/'),)\n"
        ")\n",
    )

    graph = _graph(application)

    endpoints = list(iter_endpoints(graph))
    assert [endpoint.path for endpoint in endpoints] == ["/users"]
    assert all(endpoint.source_path == "/" for endpoint in endpoints)
    assert graph.mounted_bindings[0].source_path == "/"


def test_mounted_navigation_excluded_destination_reports_mount_evidence(
    tmp_path: Path,
    make_app: Callable[..., Path],
) -> None:
    application = make_app(tmp_path / "application")
    mounts = application / "app" / "mounts"
    mount_root = mounts / "directory"
    details = mount_root / "details"
    details.mkdir(parents=True)
    (mounts / "__init__.py").write_text("", encoding="ascii")
    (mount_root / "__init__.py").write_text("", encoding="ascii")
    (details / "__init__.py").write_text("", encoding="ascii")
    _route(
        mount_root,
        "from pyganini import route_kit\n"
        "def page(kit, request): return kit\n"
        "Route = route_kit(page=page)\n",
    )
    _route(
        details,
        "from pyganini import route_kit\n"
        "def page(kit, request): return kit\n"
        "Route = route_kit(page=page)\n",
    )
    owner = _package(application, "users")
    _route(
        owner,
        "from app._pyganini.urls import urls\n"
        "from pyganini import mount_route, route_mount, to\n"
        "def create(request): return object()\n"
        "Route = route_mount(\n"
        "    create=create, mount='directory',\n"
        "    routes=(mount_route(\n"
        "        '/', destinations=(to(\n"
        "            'details', urls.details, trail_key='from-directory'\n"
        "        ),)\n"
        "    ),),\n"
        ")\n",
    )

    diagnostics = _diagnostics(application)
    diagnostic = next(
        item for item in diagnostics if "destination 'details'" in item.message
    )

    assert diagnostic.mount == "directory"
    assert diagnostic.source_path == "app/mounts/directory/route.py"
    assert diagnostic.final_path == "/users"
    assert diagnostic.owners[0].path.as_posix() == "app/routes/users/route.py"
    assert "mount identity: directory" in diagnostic.message
    assert "mounted source: app/mounts/directory/route.py" in diagnostic.message
    assert "selector: /" in diagnostic.message
    assert "final path: /users" in diagnostic.message
    assert "trail_key='from-directory'" in diagnostic.message


def test_mounted_navigation_duplicate_key_reports_mount_evidence(
    tmp_path: Path,
    make_app: Callable[..., Path],
) -> None:
    application = make_app(tmp_path / "application")
    mounts = application / "app" / "mounts"
    mount_root = mounts / "directory"
    details = mount_root / "details"
    details.mkdir(parents=True)
    (mounts / "__init__.py").write_text("", encoding="ascii")
    (mount_root / "__init__.py").write_text("", encoding="ascii")
    (details / "__init__.py").write_text("", encoding="ascii")
    _route(
        mount_root,
        "from pyganini import route_kit\n"
        "def page(kit, request): return kit\n"
        "Route = route_kit(page=page)\n",
    )
    _route(
        details,
        "from pyganini import RouteNav, route_kit\n"
        "def page(kit, request): return kit\n"
        "Route = route_kit(page=page, nav=RouteNav(key='section'))\n",
    )
    owner = _package(application, "users")
    _route(
        owner,
        "from pyganini import RouteNav, mount_route, route_mount\n"
        "def create(request): return object()\n"
        "Route = route_mount(\n"
        "    create=create, mount='directory',\n"
        "    routes=(mount_route('/', nav=RouteNav(key='section')),\n"
        "             mount_route('/details'))\n"
        ")\n",
    )

    diagnostics = _diagnostics(application)
    diagnostic = next(
        item
        for item in diagnostics
        if "dynamic navigation key 'section'" in item.message
        and item.final_path == "/users/details"
    )

    assert diagnostic.mount == "directory"
    assert diagnostic.source_path == "app/mounts/directory/details/route.py"
    assert diagnostic.final_path == "/users/details"
    assert diagnostic.owners[0].path.as_posix() == "app/routes/users/route.py"
    assert "mount identity: directory" in diagnostic.message
    assert "mounted source: app/mounts/directory/details/route.py" in diagnostic.message
    assert "selector: /details" in diagnostic.message
    assert "final path: /users/details" in diagnostic.message
    assert re.search(
        r"canonical trail at app/routes/users/route.py:\d+:\d+ and "
        r"app/mounts/directory/details/route.py:\d+:\d+",
        diagnostic.message,
    )


def test_mounted_source_rebases_parameters_and_layouts(
    tmp_path: Path, make_app: Callable[..., Path]
) -> None:
    application = make_app(tmp_path / "application")
    live = _package(application, "users")
    _route(
        live,
        "from pyganini import route_mount\n"
        "def create(request): return object()\n"
        "Route = route_mount(create=create, mount='directory')\n",
    )
    (live / "layout.py").write_text("VALUE = 1\n", encoding="ascii")
    (live / "layout.jinja").write_text("{{ child }}\n", encoding="ascii")

    mounts = application / "app" / "mounts"
    mount_root = mounts / "directory"
    mount_root.mkdir(parents=True)
    (mounts / "__init__.py").write_text("", encoding="ascii")
    (mount_root / "__init__.py").write_text("", encoding="ascii")
    (mount_root / "layout.py").write_text("VALUE = 1\n", encoding="ascii")
    (mount_root / "layout.jinja").write_text("{{ child }}\n", encoding="ascii")
    detail = mount_root / "by_contact_id"
    detail.mkdir()
    (detail / "__init__.py").write_text("", encoding="ascii")
    (detail / "layout.py").write_text("VALUE = 1\n", encoding="ascii")
    (detail / "layout.jinja").write_text("{{ child }}\n", encoding="ascii")
    (detail / "page.jinja").write_text("{{ child }}\n", encoding="ascii")
    _route(
        detail,
        "from pyganini import route_kit\n"
        "def page(kit, request): return kit\n"
        "Route = route_kit(page=page, template='page.jinja')\n",
    )

    graph = _graph(application)
    endpoint = next(item for item in iter_endpoints(graph) if item.mount)
    mounted_node = next(node for node in graph.nodes if node.mount == "directory")

    assert endpoint.path == "/users/{contact_id}"
    assert endpoint.parameters == ("contact_id",)
    assert endpoint.source_path == "/{contact_id}"
    assert endpoint.owner is not None
    assert endpoint.owner.path.as_posix() == "app/routes/users/route.py"
    assert endpoint.template is not None
    assert endpoint.template.environment_name == (
        "mounts/directory/by_contact_id/page.jinja"
    )
    assert [layout.template.environment_name for layout in mounted_node.layouts] == [
        "routes/users/layout.jinja",
        "mounts/directory/layout.jinja",
        "mounts/directory/by_contact_id/layout.jinja",
    ]


def test_repeated_mounted_parameters_include_evidence_and_sort_by_live_owner(
    tmp_path: Path, make_app: Callable[..., Path]
) -> None:
    application = make_app(tmp_path / "application")
    mounts = application / "app" / "mounts"
    mounts.mkdir()
    (mounts / "__init__.py").write_text("", encoding="ascii")
    cases = (
        ("alpha", "z_source"),
        ("zeta", "a_source"),
    )
    for owner_parent, mount in cases:
        _package(application, owner_parent)
        owner = _package(application, f"{owner_parent}/by_shared_id")
        _route(
            owner,
            "from pyganini import route_mount\n"
            "def create(request): return object()\n"
            f"Route = route_mount(create=create, mount={mount!r})\n",
        )
        source = mounts / mount
        source.mkdir()
        (source / "__init__.py").write_text("", encoding="ascii")
        dynamic = source / "by_shared_id"
        dynamic.mkdir()
        (dynamic / "__init__.py").write_text("", encoding="ascii")
        _route(
            dynamic,
            "from pyganini import route_kit\n"
            "def page(kit, request): return kit\n"
            "Route = route_kit(page=page)\n",
        )

    diagnostics = tuple(
        item for item in _diagnostics(application) if "repeats" in item.message
    )

    assert len(diagnostics) == 2
    assert [item.code for item in diagnostics] == ["PYGANINI011", "PYGANINI011"]
    assert [item.phase for item in diagnostics] == [
        "route-collision",
        "route-collision",
    ]
    assert [
        "app/routes/alpha/by_shared_id/route.py" in item.message for item in diagnostics
    ] == [True, False]
    assert [
        "app/routes/zeta/by_shared_id/route.py" in item.message for item in diagnostics
    ] == [False, True]
    for item, (owner_parent, mount) in zip(diagnostics, cases, strict=True):
        assert item.owners[0].path.as_posix() == (
            f"app/routes/{owner_parent}/by_shared_id/route.py"
        )
        assert item.mount == mount
        assert item.source_path == f"app/mounts/{mount}/by_shared_id/route.py"
        assert item.final_path == (f"/{owner_parent}/{{shared_id}}/{{shared_id}}")
        assert f"mount identity: {mount}" in item.message
        assert (
            f"mounted source: app/mounts/{mount}/by_shared_id/route.py" in item.message
        )
        assert "selector: /{shared_id}" in item.message
        assert (
            f"final path: /{owner_parent}/{{shared_id}}/{{shared_id}}" in item.message
        )
        assert "evidence phase: static route collision" in item.message


def test_mounted_same_shape_dynamic_final_paths_fail_closed(
    tmp_path: Path,
    make_app: Callable[..., Path],
) -> None:
    application = make_app(tmp_path / "application")
    owner = _package(application, "users")
    _route(
        owner,
        "from pyganini import route_mount\n"
        "def create(request): return object()\n"
        "Route = route_mount(create=create, mount='directory')\n",
    )
    ordinary = _package(application, "users/by_user_id")
    _route(
        ordinary,
        "from pyganini import route\n"
        "def page(request): return request\n"
        "Route = route(page=page)\n",
    )
    mounts = application / "app" / "mounts"
    source = mounts / "directory"
    source.mkdir(parents=True)
    (mounts / "__init__.py").write_text("", encoding="ascii")
    (source / "__init__.py").write_text("", encoding="ascii")
    mounted = source / "by_contact_id"
    mounted.mkdir()
    (mounted / "__init__.py").write_text("", encoding="ascii")
    _route(
        mounted,
        "from pyganini import route_kit\n"
        "def page(kit, request): return kit\n"
        "Route = route_kit(page=page)\n",
    )

    collisions = [
        item for item in _diagnostics(application) if item.code == "PYGANINI011"
    ]

    assert collisions
    assert all("overlaps" in item.message for item in collisions)
    assert all("owner app/routes/users/route.py" in item.message for item in collisions)
    assert all("mount directory" in item.message for item in collisions)
    assert all("source route '/{contact_id}'" in item.message for item in collisions)
    assert all(
        "evidence phase: static route collision" in item.message for item in collisions
    )


def test_static_final_path_precedes_mounted_dynamic_final_path(
    tmp_path: Path, make_app: Callable[..., Path]
) -> None:
    application = make_app(tmp_path / "application")
    owner = _package(application, "users")
    _route(
        owner,
        "from pyganini import route_mount\n"
        "def create(request): return object()\n"
        "Route = route_mount(create=create, mount='directory')\n",
    )
    ordinary = _package(application, "users/new")
    _route(
        ordinary,
        "from pyganini import route\n"
        "def page(request): return request\n"
        "Route = route(page=page)\n",
    )
    mounts = application / "app" / "mounts"
    source = mounts / "directory"
    source.mkdir(parents=True)
    (mounts / "__init__.py").write_text("", encoding="ascii")
    (source / "__init__.py").write_text("", encoding="ascii")
    mounted = source / "by_contact_id"
    mounted.mkdir()
    (mounted / "__init__.py").write_text("", encoding="ascii")
    _route(
        mounted,
        "from pyganini import route_kit\n"
        "def page(kit, request): return kit\n"
        "Route = route_kit(page=page)\n",
    )

    endpoints = list(iter_endpoints(_graph(application)))

    assert [endpoint.path for endpoint in endpoints] == [
        "/users/new",
        "/users/{contact_id}",
    ]
    assert endpoints[0].mount is None
    assert endpoints[1].mount == "directory"


def test_mounted_action_collides_with_ordinary_child_action(
    tmp_path: Path, make_app: Callable[..., Path]
) -> None:
    application = make_app(tmp_path / "application")
    owner = _package(application, "users")
    _route(
        owner,
        "from pyganini import route_mount\n"
        "def create(request): return object()\n"
        "Route = route_mount(create=create, mount='directory')\n",
    )
    ordinary = _package(application, "users/save")
    _route(
        ordinary,
        "from pyganini import action, route\n"
        "def save(request): return request\n"
        "Route = route(actions=(action('POST', '/', save),))\n",
    )
    mounts = application / "app" / "mounts"
    source = mounts / "directory"
    source.mkdir(parents=True)
    (mounts / "__init__.py").write_text("", encoding="ascii")
    (source / "__init__.py").write_text("", encoding="ascii")
    mounted = source / "save"
    mounted.mkdir()
    (mounted / "__init__.py").write_text("", encoding="ascii")
    _route(
        mounted,
        "from pyganini import kit_action, route_kit\n"
        "def save(kit, request): return kit\n"
        "Route = route_kit(actions=(kit_action('POST', '/', save),))\n",
    )

    collisions = [
        item for item in _diagnostics(application) if item.code == "PYGANINI011"
    ]

    assert len(collisions) == 1
    assert "POST /users/save" in collisions[0].message
    assert "owner app/routes/users/route.py" in collisions[0].message
    assert "mount directory" in collisions[0].message
    assert "source route '/save'" in collisions[0].message
    assert collisions[0].method == "POST"


def test_mounted_source_containment_and_middleware_fail_closed(
    tmp_path: Path, make_app: Callable[..., Path]
) -> None:
    application = make_app(tmp_path / "application")
    mounts = application / "app" / "mounts"
    mount_root = mounts / "directory"
    mount_root.mkdir(parents=True)
    (mounts / "__init__.py").write_text("", encoding="ascii")
    (mount_root / "__init__.py").write_text("", encoding="ascii")
    (mount_root / "middleware.py").write_text("VALUE = 1\n", encoding="ascii")
    (mount_root / "route.py").write_text(
        "from pyganini import route_kit\n"
        "def page(kit, request): return kit\n"
        "Route = route_kit(page=page, template='page.jinja')\n",
        encoding="ascii",
    )
    outside = tmp_path / "outside.jinja"
    outside.write_text("outside\n", encoding="ascii")
    os.symlink(outside, mount_root / "page.jinja")
    owner = _package(application, "users")
    _route(
        owner,
        "from pyganini import route_mount\n"
        "def create(request): return object()\n"
        "Route = route_mount(create=create, mount='directory')\n",
    )

    diagnostics = _diagnostics(application)

    assert any(
        item.code == "PYGANINI009"
        and item.path.as_posix() == "app/mounts/directory/middleware.py"
        and "live owner: app/routes/users/route.py" in item.message
        and "mount identity: directory" in item.message
        and "mounted source: app/mounts/directory/middleware.py" in item.message
        and "evidence phase: static route-filesystem" in item.message
        for item in diagnostics
    )
    assert any(
        item.code == "PYGANINI009"
        and item.path.as_posix() == "app/mounts/directory/page.jinja"
        and "symlink" in item.message
        for item in diagnostics
    )


def test_mounted_exact_collision_reports_live_and_source_evidence(
    tmp_path: Path, make_app: Callable[..., Path]
) -> None:
    application = make_app(tmp_path / "application")
    routes = application / "app" / "routes"
    _route(
        routes,
        "from pyganini import fragment_route, route\n"
        "def users(request): return request\n"
        "Route = route(fragments=(fragment_route('/users', users),))\n",
    )
    owner = _package(application, "users")
    _route(
        owner,
        "from pyganini import route_mount\n"
        "def create(request): return object()\n"
        "Route = route_mount(create=create, mount='directory')\n",
    )
    mounts = application / "app" / "mounts"
    mount_root = mounts / "directory"
    mount_root.mkdir(parents=True)
    (mounts / "__init__.py").write_text("", encoding="ascii")
    (mount_root / "__init__.py").write_text("", encoding="ascii")
    _route(
        mount_root,
        "from pyganini import route_kit\n"
        "def page(kit, request): return kit\n"
        "Route = route_kit(page=page)\n",
    )

    diagnostics = _diagnostics(application)

    collision = next(item for item in diagnostics if item.code == "PYGANINI011")
    assert "app/routes/route.py" in collision.message
    assert "app/mounts/directory/route.py" in collision.message
    assert "source route '/'" in collision.message
    assert "evidence phase: static route collision" in collision.message


def test_discovers_normalized_packages_handlers_layouts_and_private_trees(
    tmp_path: Path, make_app: Callable[..., Path]
) -> None:
    application = make_app(tmp_path / "application")
    routes = application / "app" / "routes"
    _route(
        routes,
        "from pyganini import route\n"
        "\n"
        "def home():\n"
        "    return None\n"
        "\n"
        "Route = route(page=home)\n"
        "raise RuntimeError('route.py must not execute')\n",
    )
    (routes / "layout.py").write_text("raise RuntimeError('not imported')\n")
    (routes / "layout.jinja").write_text("<main>{{ child }}</main>\n")

    users = _package(routes.parents[1], "users")
    (users / "handlers.py").write_text(
        "raise RuntimeError('handlers must not import')\n", encoding="ascii"
    )
    _route(
        users,
        "from pyganini import action, fragment_route, route\n"
        "from .handlers import page as user_page, table\n"
        "import app.shared.users as shared_users\n"
        "Route = route(\n"
        "    page=user_page,\n"
        "    fragments=(fragment_route('/user_table', table),),\n"
        "    actions=(action('PATCH', '/profile', shared_users.update),),\n"
        ")\n",
    )
    dynamic = _package(routes.parents[1], "users/by_user_id")
    _route(
        dynamic,
        "from pyganini import route\n"
        "def detail(): return None\n"
        "Route = route(page=detail)\n",
    )
    build_info = _package(routes.parents[1], "build_info")
    (build_info / "layout.py").write_text("VALUE = 1\n", encoding="ascii")
    (build_info / "layout.jinja").write_text("{{ child }}\n", encoding="ascii")
    private = routes / "_helpers"
    private.mkdir()
    (private / "route.py").write_text("this is not python", encoding="ascii")
    cache = routes / "__pycache__"
    cache.mkdir()
    (cache / "route.py").write_bytes(b"\xff")

    graph = _graph(application)
    assert [node.route_path for node in graph.nodes] == [
        "/",
        "/build-info",
        "/users",
        "/users/{user_id}",
    ]
    assert [node.module for node in graph.nodes] == [
        "app.routes",
        "app.routes.build_info",
        "app.routes.users",
        "app.routes.users.by_user_id",
    ]
    assert graph.nodes[0].layout is not None
    assert graph.nodes[1].layout is not None
    assert graph.nodes[0].layout.template.environment_name == "routes/layout.jinja"
    assert graph.nodes[3].parameters == ("user_id",)

    declaration = graph.nodes[2].declaration
    assert declaration is not None
    assert declaration.page is not None
    assert declaration.page_template is None
    assert (
        declaration.page.module,
        declaration.page.symbol,
        declaration.page.binding,
    ) == ("app.routes.users.handlers", "page", "user_page")
    assert declaration.fragments[0].path == "/user-table"
    assert declaration.fragments[0].handler.symbol == "table"
    assert declaration.actions[0].handler.module == "app.shared.users"
    assert declaration.actions[0].handler.symbol == "update"
    assert declaration.actions[0].handler.binding == "shared_users"

    endpoints = list(iter_endpoints(graph))
    assert [
        (endpoint.kind, endpoint.methods, endpoint.path) for endpoint in endpoints
    ] == [
        ("page", ("GET", "HEAD"), "/"),
        ("page", ("GET", "HEAD"), "/users"),
        ("fragment", ("GET", "HEAD"), "/users/user-table"),
        ("action", ("PATCH",), "/users/profile"),
        ("page", ("GET", "HEAD"), "/users/{user_id}"),
    ]
    with pytest.raises(FrozenInstanceError):
        graph.nodes[0].route_path = "/changed"  # type: ignore[misc]


def test_discovers_kit_routes_and_shared_template_evidence_without_importing_app(
    tmp_path: Path, make_app: Callable[..., Path]
) -> None:
    application = make_app(tmp_path / "application")
    shared = application / "app" / "shared" / "reports"
    shared.mkdir(parents=True)
    (application / "app" / "shared" / "__init__.py").write_text("", encoding="ascii")
    (shared / "__init__.py").write_text("", encoding="ascii")
    (shared / "page.jinja").write_text("<h1>{{ title }}</h1>\n", encoding="ascii")
    (shared / "table.jinja").write_text("<p>{{ rows }}</p>\n", encoding="ascii")
    (shared / "handlers.py").write_text(
        "raise RuntimeError('shared module must not import')\n", encoding="ascii"
    )

    users = _package(application, "users")
    _route(
        users,
        "from pyganini import kit_action, kit_fragment_route, route_kit\n"
        "import app.shared.reports as reports\n"
        "def create(request): return reports.Kit()\n"
        "Route = route_kit(\n"
        " create=create,\n"
        " template_root='shared/reports',\n"
        " page=reports.page,\n"
        " template='page.jinja',\n"
        " fragments=(\n"
        "  kit_fragment_route('/table', reports.table, template='table.jinja'),\n"
        " ),\n"
        " actions=(kit_action('POST', '/refresh', reports.refresh),),\n"
        ")\n",
    )

    graph = _graph(application)
    declaration = graph.nodes[1].declaration
    assert declaration is not None
    assert declaration.kit is not None
    assert declaration.kit.creator is not None
    assert declaration.kit.creator.symbol == "create"
    assert declaration.kit.template_root == "shared/reports"
    assert declaration.page_template is not None
    assert declaration.page_template.environment_name == "shared/reports/page.jinja"
    assert declaration.page_template.source.path.as_posix() == (
        "app/shared/reports/page.jinja"
    )
    assert declaration.page_template.source.line == 1
    assert declaration.page_template.declaration is not None
    assert declaration.page_template.declaration.path.as_posix() == (
        "app/routes/users/route.py"
    )
    assert declaration.fragments[0].template is not None
    assert (
        declaration.fragments[0].template.environment_name
        == "shared/reports/table.jinja"
    )
    assert declaration.fragments[0].template.source.path.as_posix() == (
        "app/shared/reports/table.jinja"
    )
    assert declaration.fragments[0].template.template_root == "shared/reports"
    endpoints = list(iter_endpoints(graph))
    assert [(endpoint.kind, endpoint.path) for endpoint in endpoints] == [
        ("page", "/users"),
        ("fragment", "/users/table"),
        ("action", "/users/refresh"),
    ]
    assert all(endpoint.creator is not None for endpoint in endpoints)


def test_kit_declaration_grammar_and_shared_template_containment_fail_closed(
    tmp_path: Path, make_app: Callable[..., Path]
) -> None:
    application = make_app(tmp_path / "application")
    shared = application / "app" / "shared"
    shared.mkdir()
    (shared / "__init__.py").write_text("", encoding="ascii")
    package = _package(application, "reports")
    _route(
        package,
        "from pyganini import route_kit\n"
        "from .handlers import create, page\n"
        "Route = route_kit(\n"
        " create=create, template_root='shared/reports', page=page,\n"
        " template='page.jinja',\n"
        ")\n",
    )
    diagnostics = _diagnostics(application)
    assert diagnostics[0].code == "PYGANINI009"
    assert diagnostics[0].path.as_posix() == "app/shared/reports"
    assert "shared" in diagnostics[0].message

    _route(
        package,
        "from pyganini import route_kit as make_route\n"
        "from .handlers import create, page\n"
        "Route = make_route(create=create, page=page)\n",
    )
    diagnostic = _diagnostics(application)[0]
    assert diagnostic.code == "PYGANINI010"
    assert diagnostic.field == "Route"
    assert "route_kit(...)" in diagnostic.message


def test_graph_is_equal_across_creation_order_and_ignores_declaration_order(
    tmp_path: Path, make_app: Callable[..., Path]
) -> None:
    applications = [
        make_app(tmp_path / "first"),
        make_app(tmp_path / "second"),
    ]
    orders = [("zeta", "alpha"), ("alpha", "zeta")]
    for index, (application, order) in enumerate(
        zip(applications, orders, strict=True)
    ):
        routes = application / "app" / "routes"
        for name in order:
            package = _package(routes.parents[1], name)
            fragments = (
                "fragment_route('/beta', beta), fragment_route('/alpha', alpha)"
                if index == 0
                else "fragment_route('/alpha', alpha), fragment_route('/beta', beta)"
            )
            actions = (
                "action('DELETE', '/beta', beta), action('POST', '/alpha', alpha)"
                if index == 0
                else "action('POST', '/alpha', alpha), action('DELETE', '/beta', beta)"
            )
            _route(
                package,
                "from pyganini import action, fragment_route, route\n"
                "from .handlers import alpha, beta\n"
                "Route = route(\n"
                f" fragments=({fragments}),\n"
                f" actions=({actions}),\n"
                ")\n",
            )
    assert _graph(applications[0]) == _graph(applications[1])
    declaration = _graph(applications[0]).nodes[1].declaration
    assert declaration is not None
    assert [surface.path for surface in declaration.fragments] == ["/alpha", "/beta"]
    assert [(surface.path, surface.method) for surface in declaration.actions] == [
        ("/alpha", "POST"),
        ("/beta", "DELETE"),
    ]


def test_graph_repr_is_independent_of_cwd_and_hash_seed(
    tmp_path: Path, make_app: Callable[..., Path]
) -> None:
    application = make_app(tmp_path / "application")
    package = _package(application, "users")
    _route(
        package,
        "from pyganini import route\n"
        "from .handlers import page\n"
        "Route = route(page=page)\n",
    )
    script = (
        "from pathlib import Path; "
        "from pyganini._paths import select_project_paths; "
        "from pyganini._route_graph import build_route_graph; "
        f"paths = select_project_paths(explicit=Path({str(application)!r})); "
        "print(repr(build_route_graph(paths)))"
    )
    outputs: list[str] = []
    for seed, cwd in (("1", application), ("731", tmp_path)):
        environment = os.environ.copy()
        environment["PYTHONHASHSEED"] = seed
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=cwd,
            env=environment,
            check=True,
            capture_output=True,
            text=True,
        )
        outputs.append(result.stdout)
    assert outputs[0] == outputs[1]


def test_static_sibling_precedes_one_dynamic_sibling(
    tmp_path: Path, make_app: Callable[..., Path]
) -> None:
    application = make_app(tmp_path / "application")
    root = application / "app" / "routes"
    _package(root.parents[1], "by_user_id")
    _package(root.parents[1], "new_user")
    graph = _graph(application)
    assert [node.route_path for node in graph.nodes] == [
        "/",
        "/new-user",
        "/{user_id}",
    ]


def test_aggregates_sorted_filesystem_and_syntax_diagnostics(
    tmp_path: Path, make_app: Callable[..., Path]
) -> None:
    application = make_app(tmp_path / "application")
    root = application / "app" / "routes"
    (root / "Bad-Name").mkdir()
    missing = root / "missing_marker"
    missing.mkdir()
    invalid_utf8 = _package(root.parents[1], "invalid_utf8")
    (invalid_utf8 / "route.py").write_bytes(b"\xff")
    invalid_syntax = _package(root.parents[1], "invalid_syntax")
    (invalid_syntax / "layout.py").write_text("if:\n", encoding="ascii")
    (invalid_syntax / "layout.jinja").write_text("{{ child }}\n", encoding="ascii")

    diagnostics = _diagnostics(application)
    assert [
        (diagnostic.code, diagnostic.path.as_posix()) for diagnostic in diagnostics
    ] == sorted(
        (diagnostic.code, diagnostic.path.as_posix()) for diagnostic in diagnostics
    )
    assert [diagnostic.code for diagnostic in diagnostics] == [
        "PYGANINI009",
        "PYGANINI009",
        "PYGANINI009",
        "PYGANINI010",
    ]
    assert "lowercase ASCII" in diagnostics[0].message
    assert diagnostics[1].field is None
    assert "valid UTF-8" in diagnostics[1].message
    assert "__init__.py" in diagnostics[2].message
    assert "invalid Python syntax" in diagnostics[3].message


def test_rejects_live_directory_and_convention_symlinks(
    tmp_path: Path, make_app: Callable[..., Path]
) -> None:
    application = make_app(tmp_path / "application")
    root = application / "app" / "routes"
    outside = tmp_path / "outside"
    outside.mkdir()
    os.symlink(outside, root / "users")
    package = _package(root.parents[1], "settings")
    target = tmp_path / "route.py"
    target.write_text("", encoding="ascii")
    os.symlink(target, package / "route.py")

    diagnostics = _diagnostics(application)
    assert len(diagnostics) == 2
    assert all(diagnostic.code == "PYGANINI009" for diagnostic in diagnostics)
    assert all("symlink" in diagnostic.message for diagnostic in diagnostics)


def test_ignores_nonconvention_file_symlinks(
    tmp_path: Path, make_app: Callable[..., Path]
) -> None:
    application = make_app(tmp_path / "application")
    target = tmp_path / "handlers.py"
    target.write_text("VALUE = 1\n", encoding="ascii")
    os.symlink(target, application / "app" / "routes" / "handlers.py")

    graph = _graph(application)
    assert [node.route_path for node in graph.nodes] == ["/"]


def test_ignores_by_prefixed_nonconvention_file_symlinks(
    tmp_path: Path, make_app: Callable[..., Path]
) -> None:
    application = make_app(tmp_path / "application")
    target = tmp_path / "handlers.py"
    target.write_text("VALUE = 1\n", encoding="ascii")
    routes = application / "app" / "routes"
    for name in ("by_", "by_Bad", "by_notes.py"):
        os.symlink(target, routes / name)

    graph = _graph(application)
    assert [node.route_path for node in graph.nodes] == ["/"]


def test_convention_open_stays_anchored_when_parent_path_is_replaced(
    tmp_path: Path,
    make_app: Callable[..., Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    application = make_app(tmp_path / "application")
    package = _package(application, "users")
    _route(
        package,
        "from pyganini import route\n"
        "from .handlers import original\n"
        "Route = route(page=original)\n",
    )
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "__init__.py").write_text("", encoding="ascii")
    _route(
        outside,
        "from pyganini import route\n"
        "from .handlers import outside\n"
        "Route = route(page=outside)\n",
    )
    saved = tmp_path / "saved-users"
    route_file = package / "route.py"
    real_open = os.open
    swapped = False

    def replace_parent_before_open(
        path: str | os.PathLike[str],
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        nonlocal swapped
        if not swapped and (Path(path) == route_file or os.fspath(path) == "route.py"):
            package.rename(saved)
            os.symlink(outside, package)
            swapped = True
        return real_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr("pyganini._route_graph.os.open", replace_parent_before_open)
    try:
        declaration = _graph(application).nodes[1].declaration
    finally:
        if package.is_symlink():
            package.unlink()
        if saved.exists():
            saved.rename(package)

    assert swapped
    assert declaration is not None
    assert declaration.page is not None
    assert declaration.page.symbol == "original"


@pytest.mark.skipif(os.name == "nt", reason="POSIX descriptor regression")
def test_child_descriptor_close_failure_is_localized_and_scanning_continues(
    tmp_path: Path,
    make_app: Callable[..., Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    application = make_app(tmp_path / "application")
    _package(application, "alpha")
    (application / "app" / "routes" / "zeta").mkdir()
    real_open = os.open
    real_close = os.close
    child_descriptor: int | None = None
    failed = False

    def track_open(
        path: str | os.PathLike[str],
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        nonlocal child_descriptor
        descriptor = real_open(path, flags, mode, dir_fd=dir_fd)
        if os.fspath(path) == "alpha":
            child_descriptor = descriptor
        return descriptor

    def fail_child_close(descriptor: int) -> None:
        nonlocal failed
        real_close(descriptor)
        if descriptor == child_descriptor and not failed:
            failed = True
            raise OSError("injected child close failure")

    monkeypatch.setattr("pyganini._route_graph.os.open", track_open)
    monkeypatch.setattr("pyganini._route_graph.os.close", fail_child_close)
    diagnostics = _diagnostics(application)

    assert failed
    assert [diagnostic.path.as_posix() for diagnostic in diagnostics] == [
        "app/routes/alpha",
        "app/routes/zeta/__init__.py",
    ]
    assert "injected child close failure" in diagnostics[0].message
    assert "__init__.py" in diagnostics[1].message


@pytest.mark.skipif(os.name == "nt", reason="POSIX descriptor regression")
def test_root_descriptor_close_failure_does_not_skip_remaining_closes(
    tmp_path: Path,
    make_app: Callable[..., Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    application = make_app(tmp_path / "application")
    real_open = os.open
    real_close = os.close
    opened: list[int] = []
    closed: list[int] = []
    failed = False

    def track_open(
        path: str | os.PathLike[str],
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        descriptor = real_open(path, flags, mode, dir_fd=dir_fd)
        opened.append(descriptor)
        return descriptor

    def fail_routes_close(descriptor: int) -> None:
        nonlocal failed
        real_close(descriptor)
        closed.append(descriptor)
        if len(opened) >= 3 and descriptor == opened[2] and not failed:
            failed = True
            raise OSError("injected root-chain close failure")

    monkeypatch.setattr("pyganini._route_graph.os.open", track_open)
    monkeypatch.setattr("pyganini._route_graph.os.close", fail_routes_close)
    try:
        diagnostic = _diagnostics(application)[0]
    finally:
        for descriptor in opened:
            with suppress(OSError):
                real_close(descriptor)

    assert failed
    assert closed == list(reversed(opened[:3]))
    assert diagnostic.path.as_posix() == "app/routes"
    assert "injected root-chain close failure" in diagnostic.message


def _void_pointer(_: int) -> SimpleNamespace:
    return SimpleNamespace(value=-1)


def _win_error(code: int) -> OSError:
    return OSError(f"winerror {code}")


def test_win32_route_directory_handle_uses_no_delete_share_and_reparse_flags() -> None:
    calls: list[tuple[Any, ...]] = []

    class Kernel:
        def CreateFileW(self, *args: Any) -> int:
            calls.append(args)
            return 17

        def GetFileAttributesW(self, _: str) -> int:
            return route_graph_module._FILE_ATTRIBUTE_DIRECTORY

        def CloseHandle(self, _: int) -> None:
            raise AssertionError("valid handle must remain held")

    api = route_graph_module._Win32RouteApi.__new__(route_graph_module._Win32RouteApi)
    api._kernel32 = Kernel()
    api._ctypes = SimpleNamespace(
        get_last_error=lambda: 0,
        WinError=OSError,
        c_void_p=_void_pointer,
    )
    assert api.open_directory(Path("C:/application/app/routes")) == 17
    call = calls[0]
    assert call[2] == (
        route_graph_module._FILE_SHARE_READ | route_graph_module._FILE_SHARE_WRITE
    )
    assert call[5] & route_graph_module._FILE_FLAG_BACKUP_SEMANTICS
    assert call[5] & route_graph_module._FILE_FLAG_OPEN_REPARSE_POINT


def test_win32_attribute_failure_preserves_primary_and_exposes_close_failure() -> None:
    state = {"last_error": 5}

    class Kernel:
        def CreateFileW(self, *_: Any) -> int:
            return 17

        def GetFileAttributesW(self, _: str) -> int:
            return route_graph_module._INVALID_FILE_ATTRIBUTES

        def CloseHandle(self, _: int) -> int:
            state["last_error"] = 99
            return 0

    api = route_graph_module._Win32RouteApi.__new__(route_graph_module._Win32RouteApi)
    api._kernel32 = Kernel()
    api._ctypes = SimpleNamespace(
        get_last_error=lambda: state["last_error"],
        WinError=_win_error,
        c_void_p=_void_pointer,
    )

    with pytest.raises(OSError) as raised:
        api.open_directory(Path("C:/application/app/routes"))

    assert str(raised.value) == (
        "winerror 5; additionally failed to close route handle: winerror 99"
    )
    assert isinstance(raised.value.__cause__, OSError)
    assert str(raised.value.__cause__) == "winerror 5"


def test_win32_invalid_handle_preserves_create_error_without_cleanup() -> None:
    closed: list[int] = []

    class Kernel:
        def CreateFileW(self, *_: Any) -> int:
            return -1

        def GetFileAttributesW(self, _: str) -> int:
            raise AssertionError("invalid handles must fail before attribute lookup")

        def CloseHandle(self, handle: int) -> int:
            closed.append(handle)
            return 1

    api = route_graph_module._Win32RouteApi.__new__(route_graph_module._Win32RouteApi)
    api._kernel32 = Kernel()
    api._ctypes = SimpleNamespace(
        get_last_error=lambda: 2,
        WinError=_win_error,
        c_void_p=_void_pointer,
    )

    with pytest.raises(OSError, match="winerror 2"):
        api.open_directory(Path("C:/missing"))

    assert closed == []


@pytest.mark.parametrize(
    ("attributes", "message"),
    [
        (
            route_graph_module._FILE_ATTRIBUTE_DIRECTORY
            | route_graph_module._FILE_ATTRIBUTE_REPARSE_POINT,
            "route path is a reparse point",
        ),
        (0, "route path must be a directory"),
    ],
)
def test_win32_directory_rejection_exposes_close_failure(
    attributes: int, message: str
) -> None:
    state = {"last_error": 0}

    class Kernel:
        def CreateFileW(self, *_: Any) -> int:
            return 17

        def GetFileAttributesW(self, _: str) -> int:
            return attributes

        def CloseHandle(self, _: int) -> int:
            state["last_error"] = 99
            return 0

    api = route_graph_module._Win32RouteApi.__new__(route_graph_module._Win32RouteApi)
    api._kernel32 = Kernel()
    api._ctypes = SimpleNamespace(
        get_last_error=lambda: state["last_error"],
        WinError=_win_error,
        c_void_p=_void_pointer,
    )

    with pytest.raises(OSError) as raised:
        api.open_directory(Path("C:/application/app/routes"))

    assert str(raised.value) == (
        f"{message}; additionally failed to close route handle: winerror 99"
    )


def test_win32_descriptor_conversion_failure_exposes_close_failure() -> None:
    state = {"last_error": 0}

    class Kernel:
        def CreateFileW(self, *_: Any) -> int:
            return 17

        def GetFileAttributesW(self, _: str) -> int:
            return 0

        def CloseHandle(self, _: int) -> int:
            state["last_error"] = 99
            return 0

    def fail_conversion(_: int, __: int) -> int:
        raise OSError("descriptor conversion failed")

    api = route_graph_module._Win32RouteApi.__new__(route_graph_module._Win32RouteApi)
    api._kernel32 = Kernel()
    api._ctypes = SimpleNamespace(
        get_last_error=lambda: state["last_error"],
        WinError=_win_error,
        c_void_p=_void_pointer,
    )
    api._msvcrt = SimpleNamespace(open_osfhandle=fail_conversion)

    with pytest.raises(OSError) as raised:
        api.read_regular(Path("C:/application/app/routes/route.py"))

    assert str(raised.value) == (
        "descriptor conversion failed; additionally failed to close route handle: "
        "winerror 99"
    )
    assert isinstance(raised.value.__cause__, OSError)
    assert str(raised.value.__cause__) == "descriptor conversion failed"


def test_win32_descriptor_transfer_closes_only_the_os_descriptor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[tuple[str, int]] = []

    class Kernel:
        def CreateFileW(self, *_: Any) -> int:
            return 17

        def GetFileAttributesW(self, _: str) -> int:
            return 0

        def CloseHandle(self, handle: int) -> int:
            events.append(("handle-close", handle))
            return 1

    api = route_graph_module._Win32RouteApi.__new__(route_graph_module._Win32RouteApi)
    api._kernel32 = Kernel()
    api._ctypes = SimpleNamespace(
        get_last_error=lambda: 0,
        WinError=_win_error,
        c_void_p=_void_pointer,
    )

    def transfer(handle: int, _: int) -> int:
        events.append(("transfer", handle))
        return 23

    def fake_fstat(_: int) -> SimpleNamespace:
        return SimpleNamespace(
            st_mode=0o100644,
            st_file_attributes=0,
        )

    def fake_fdopen(_: int, __: str, *, closefd: bool) -> BytesIO:
        assert closefd is False
        return BytesIO(b"Route = value\n")

    def fake_close(descriptor: int) -> None:
        events.append(("descriptor-close", descriptor))

    api._msvcrt = SimpleNamespace(open_osfhandle=transfer)
    monkeypatch.setattr("pyganini._route_graph.os.fstat", fake_fstat)
    monkeypatch.setattr("pyganini._route_graph.os.fdopen", fake_fdopen)
    monkeypatch.setattr("pyganini._route_graph.os.close", fake_close)

    assert api.read_regular(Path("C:/application/app/routes/route.py")) == (
        b"Route = value\n"
    )
    assert events == [("transfer", 17), ("descriptor-close", 23)]


def test_win32_non_oserror_survives_failed_pretransfer_cleanup() -> None:
    state = {"last_error": 0}

    class Kernel:
        def CreateFileW(self, *_: Any) -> int:
            return 17

        def GetFileAttributesW(self, _: str) -> int:
            return 0

        def CloseHandle(self, _: int) -> int:
            state["last_error"] = 99
            return 0

    def fail_conversion(_: int, __: int) -> int:
        raise RuntimeError("unexpected conversion failure")

    api = route_graph_module._Win32RouteApi.__new__(route_graph_module._Win32RouteApi)
    api._kernel32 = Kernel()
    api._ctypes = SimpleNamespace(
        get_last_error=lambda: state["last_error"],
        WinError=_win_error,
        c_void_p=_void_pointer,
    )
    api._msvcrt = SimpleNamespace(open_osfhandle=fail_conversion)

    with pytest.raises(RuntimeError) as raised:
        api.read_regular(Path("C:/application/app/routes/route.py"))

    assert str(raised.value) == "unexpected conversion failure"
    assert raised.value.__notes__ == [
        "additionally failed to close route handle: winerror 99"
    ]


def test_mocked_windows_backend_builds_graph_without_posix_descriptors(
    tmp_path: Path,
    make_app: Callable[..., Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    application = make_app(tmp_path / "application")
    users = _package(application, "users")
    _route(
        users,
        "from pyganini import route\n"
        "from .handlers import page\n"
        "Route = route(page=page, template='page.jinja')\n",
    )
    (users / "page.jinja").write_text("{{ value }}\n", encoding="ascii")
    (users / "layout.py").write_text("VALUE = 1\n", encoding="ascii")
    (users / "layout.jinja").write_text("{{ child }}\n", encoding="ascii")

    class Api:
        def __init__(self) -> None:
            self.held: list[Path] = []
            self.read: list[Path] = []
            self.closed: list[Path] = []

        def open_directory(self, path: Path) -> Path:
            self.held.append(path)
            return path

        def read_regular(self, path: Path) -> bytes:
            self.read.append(path)
            return path.read_bytes()

        def close(self, handle: Path) -> None:
            self.closed.append(handle)

    api = Api()
    monkeypatch.setattr(route_graph_module, "_IS_WINDOWS", True)
    monkeypatch.setattr(route_graph_module, "_Win32RouteApi", lambda: cast(Any, api))

    graph = _graph(application)

    assert [node.route_path for node in graph.nodes] == ["/", "/users"]
    assert api.held == [
        application,
        application / "app",
        application / "app" / "routes",
        users,
    ]
    assert api.read == [
        users / "route.py",
        users / "page.jinja",
        users / "layout.py",
        users / "layout.jinja",
    ]
    assert api.closed == list(reversed(api.held))


def test_mocked_windows_backend_rejects_reparse_endpoint_template(
    tmp_path: Path,
    make_app: Callable[..., Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    application = make_app(tmp_path / "application")
    routes = application / "app" / "routes"
    _route(
        routes,
        "from pyganini import route\n"
        "def page(request): return request\n"
        "Route = route(page=page, template='page.jinja')\n",
    )
    template = routes / "page.jinja"
    template.write_text("{{ value }}\n", encoding="ascii")

    class Api:
        def open_directory(self, path: Path) -> Path:
            return path

        def read_regular(self, path: Path) -> bytes:
            if path == template:
                raise AssertionError("reparse template must not be opened")
            return path.read_bytes()

        def close(self, handle: Path) -> None:
            assert handle.exists()

    real_lstat = Path.lstat

    def reparse_lstat(path: Path) -> Any:
        info = real_lstat(path)
        if path == template:
            return SimpleNamespace(
                st_mode=info.st_mode,
                st_file_attributes=route_graph_module._FILE_ATTRIBUTE_REPARSE_POINT,
            )
        return info

    monkeypatch.setattr(route_graph_module, "_IS_WINDOWS", True)
    monkeypatch.setattr(route_graph_module, "_Win32RouteApi", lambda: cast(Any, Api()))
    monkeypatch.setattr(Path, "lstat", reparse_lstat)

    diagnostic = _diagnostics(application)[0]
    assert diagnostic.code == "PYGANINI009"
    assert diagnostic.path.as_posix() == "app/routes/page.jinja"
    assert "symlink" in diagnostic.message


def test_rejects_every_unsupported_live_directory_form(
    tmp_path: Path, make_app: Callable[..., Path]
) -> None:
    application = make_app(tmp_path / "application")
    root = application / "app" / "routes"
    names = [
        "Upper",
        "has-hyphen",
        "has.dot",
        "has space",
        "1start",
        "by_",
        "by_Bad",
        "_Bad",
        "caf" + chr(233),
    ]
    for name in names:
        (root / name).mkdir()
    diagnostics = _diagnostics(application)
    assert len(diagnostics) == len(names)
    assert all(diagnostic.code == "PYGANINI009" for diagnostic in diagnostics)
    assert all("ASCII" in diagnostic.message for diagnostic in diagnostics)


def test_rejects_nonregular_package_and_convention_files(
    tmp_path: Path, make_app: Callable[..., Path]
) -> None:
    application = make_app(tmp_path / "application")
    root = application / "app" / "routes"
    package = root / "users"
    package.mkdir()
    marker_target = tmp_path / "marker.py"
    marker_target.write_text("", encoding="ascii")
    os.symlink(marker_target, package / "__init__.py")
    (root / "route.py").mkdir()
    diagnostics = _diagnostics(application)
    assert len(diagnostics) == 2
    assert all(diagnostic.code == "PYGANINI009" for diagnostic in diagnostics)
    assert any("package marker" in diagnostic.message for diagnostic in diagnostics)
    assert any("regular file" in diagnostic.message for diagnostic in diagnostics)


def test_rejects_fifo_convention_without_opening_it(
    tmp_path: Path, make_app: Callable[..., Path]
) -> None:
    if not hasattr(os, "mkfifo"):
        pytest.skip("host does not provide FIFO creation")
    application = make_app(tmp_path / "application")
    route_file = application / "app" / "routes" / "route.py"
    os.mkfifo(route_file)
    diagnostic = _diagnostics(application)[0]
    assert diagnostic.code == "PYGANINI009"
    assert "regular file" in diagnostic.message


def test_localizes_convention_read_failures(
    tmp_path: Path,
    make_app: Callable[..., Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    application = make_app(tmp_path / "application")
    route_file = application / "app" / "routes" / "route.py"
    route_file.write_text("from pyganini import route\n", encoding="ascii")
    real_open = os.open

    def deny(
        path: str | os.PathLike[str],
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        if Path(path) == route_file or os.fspath(path) == "route.py":
            raise PermissionError("read denied")
        return real_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr("pyganini._route_graph.os.open", deny)
    diagnostic = _diagnostics(application)[0]
    assert diagnostic.code == "PYGANINI009"
    assert "cannot read convention file" in diagnostic.message
    assert "read denied" in diagnostic.message


def test_localizes_unreadable_route_directory(
    tmp_path: Path, make_app: Callable[..., Path]
) -> None:
    application = make_app(tmp_path / "application")
    blocked = _package(application, "blocked")
    blocked.chmod(0)
    try:
        if os.access(blocked, os.R_OK | os.X_OK):
            pytest.skip("host cannot prove route-directory permissions")
        diagnostic = _diagnostics(application)[0]
    finally:
        blocked.chmod(0o700)

    assert diagnostic.path.as_posix() == "app/routes/blocked"
    assert diagnostic.code == "PYGANINI009"
    assert "cannot read route directory" in diagnostic.message


def test_localizes_route_directory_without_search_permission(
    tmp_path: Path, make_app: Callable[..., Path]
) -> None:
    application = make_app(tmp_path / "application")
    blocked = _package(application, "blocked")
    blocked.chmod(0o400)
    try:
        if not os.access(blocked, os.R_OK) or os.access(blocked, os.X_OK):
            pytest.skip("host cannot prove separate route-directory permissions")
        diagnostic = _diagnostics(application)[0]
    finally:
        blocked.chmod(0o700)

    assert diagnostic.path.as_posix() == "app/routes/blocked"
    assert diagnostic.code == "PYGANINI009"
    assert "cannot access route directory" in diagnostic.message


@pytest.mark.parametrize(
    ("source", "field", "message"),
    [
        ("Route = object()\n", "Route", "route(...)"),
        (
            "from pyganini import route as make_route\nRoute = make_route()\n",
            "Route",
            "route(...)",
        ),
        ("from pyganini import route\nRoute: object = route()\n", "Route", "annotated"),
        ("from pyganini import route\nRoute = other = route()\n", "Route", "direct"),
        ("from pyganini import *\nRoute = route()\n", "imports", "star import"),
        (
            "from pyganini import route\nRoute = route(unknown=None)\n",
            "Route",
            "unknown",
        ),
        ("from pyganini import route\nRoute = route(*())\n", "Route", "positional"),
        (
            "from pyganini import route\nRoute = route(**{})\n",
            "Route",
            "keyword expansion",
        ),
        (
            "from pyganini import route\nRoute = route(page=page)\ndef page(): pass\n",
            "page",
            "missing handler",
        ),
        (
            "from pyganini import route\npage = object()\nRoute = route(page=page)\n",
            "page",
            "rebound",
        ),
        (
            "from pyganini import fragment_route, route\n"
            "from .h import page\n"
            "Route = route(fragments=[fragment_route('/', page)])\n",
            "fragments",
            "literal tuple",
        ),
        (
            "from pyganini import fragment_route, route\n"
            "from .h import page\n"
            "Route = route(fragments=(page,))\n",
            "fragments",
            "fragment",
        ),
        (
            "from pyganini import action, route\n"
            "from .h import page\n"
            "Route = route(actions=(action('GET', '/', page),))\n",
            "method",
            "POST",
        ),
        (
            "from pyganini import route\nRoute = route(page=lambda: None)\n",
            "page",
            "named",
        ),
    ],
)
def test_declaration_syntax_fails_closed(
    tmp_path: Path,
    make_app: Callable[..., Path],
    source: str,
    field: str,
    message: str,
) -> None:
    application = make_app(tmp_path / "application")
    _route(application / "app" / "routes", source)
    diagnostic = _diagnostics(application)[0]
    assert diagnostic.code == "PYGANINI010"
    assert diagnostic.phase == "route-declaration"
    assert diagnostic.path.as_posix() == "app/routes/route.py"
    assert diagnostic.line is not None
    assert diagnostic.column is not None
    assert diagnostic.field == field
    assert message in diagnostic.message


@pytest.mark.parametrize(
    "source",
    [
        "from pyganini import route\n"
        "from .handlers import page\n"
        "ROUTE = route(page=page)\n",
        "from pyganini import fragment, route\n"
        "from .handlers import page\n"
        "Route = route(fragments=(fragment('/', page),))\n",
    ],
)
def test_removed_declaration_spellings_are_rejected(
    tmp_path: Path,
    make_app: Callable[..., Path],
    source: str,
) -> None:
    application = make_app(tmp_path / "application")
    _route(application / "app" / "routes", source)
    diagnostic = _diagnostics(application)[0]
    assert diagnostic.code == "PYGANINI010"
    assert diagnostic.field in {"Route", "fragments"}


@pytest.mark.parametrize(
    "binding",
    [
        "def Route(): pass",
        "class Route: pass",
        "from app.handlers import page as Route",
        "import app.handlers as Route",
        "Route: object",
        "Route += 1",
        "for Route in (): pass",
        "with context() as Route: pass",
        "try:\n pass\nexcept Exception as Route:\n pass",
        "match value:\n case Route:\n  pass",
        "del Route",
        "(Route := value)",
        "type Route = int",
        "if condition: Route = value",
    ],
)
def test_every_module_scope_route_binding_form_is_rejected(
    tmp_path: Path,
    make_app: Callable[..., Path],
    binding: str,
) -> None:
    application = make_app(tmp_path / "application")
    _route(
        application / "app" / "routes",
        "from pyganini import route\n"
        "from app.handlers import page\n"
        "Route = route(page=page)\n"
        f"{binding}\n",
    )
    diagnostic = _diagnostics(application)[0]
    assert diagnostic.code == "PYGANINI010"
    assert diagnostic.field == "Route"
    assert "unsupported" in diagnostic.message or "direct" in diagnostic.message


def test_nested_scope_bindings_do_not_compete_with_route_and_later_handler_rebinds(
    tmp_path: Path, make_app: Callable[..., Path]
) -> None:
    application = make_app(tmp_path / "application")
    _route(
        application / "app" / "routes",
        "from typing import TYPE_CHECKING\n"
        "from pyganini import route\n"
        "from .handlers import first as page\n"
        "if TYPE_CHECKING:\n"
        "    Route = object()\n"
        "def nested():\n"
        "    Route = object()\n"
        "    values = [Route for Route in ()]\n"
        "Route = route(page=page)\n"
        "page = object()\n",
    )
    declaration = _graph(application).nodes[0].declaration
    assert declaration is not None
    assert declaration.page is not None
    assert declaration.page.module == "app.routes.handlers"
    assert declaration.page.symbol == "first"
    assert declaration.page.binding == "page"


def test_rebound_type_checking_sentinel_does_not_hide_handler_rebinding(
    tmp_path: Path, make_app: Callable[..., Path]
) -> None:
    application = make_app(tmp_path / "application")
    _route(
        application / "app" / "routes",
        "from typing import TYPE_CHECKING\n"
        "from pyganini import route\n"
        "from .handlers import first as page\n"
        "def replacement(): pass\n"
        "TYPE_CHECKING = True\n"
        "if TYPE_CHECKING:\n"
        "    page = replacement\n"
        "Route = route(page=page)\n",
    )
    diagnostic = _diagnostics(application)[0]
    assert diagnostic.code == "PYGANINI010"
    assert diagnostic.field == "page"
    assert "conditional assignment" in diagnostic.message


def test_constructor_shadowing_before_route_fails_closed(
    tmp_path: Path, make_app: Callable[..., Path]
) -> None:
    application = make_app(tmp_path / "application")
    _route(
        application / "app" / "routes",
        "from pyganini import fragment_route, route\n"
        "from .handlers import page\n"
        "fragment_route = object()\n"
        "Route = route(fragments=(fragment_route('/', page),))\n",
    )
    diagnostic = _diagnostics(application)[0]
    assert diagnostic.field == "fragments"
    assert "exact imported fragment" in diagnostic.message


def test_decorated_local_handler_and_relative_import_outside_routes_are_static(
    tmp_path: Path, make_app: Callable[..., Path]
) -> None:
    application = make_app(tmp_path / "application")
    package = _package(application, "users")
    _route(
        package,
        "from pyganini import route\n"
        "from ...shared import decorate\n"
        "@decorate\n"
        "def page(): return None\n"
        "Route = route(page=page)\n",
    )
    declaration = _graph(application).nodes[1].declaration
    assert declaration is not None
    assert declaration.page is not None
    assert declaration.page.module == "app.routes.users.route"


def test_relative_import_cannot_escape_the_application_package(
    tmp_path: Path, make_app: Callable[..., Path]
) -> None:
    application = make_app(tmp_path / "application")
    package = _package(application, "users")
    _route(
        package,
        "from pyganini import route\n"
        "from ....shared import page\n"
        "Route = route(page=page)\n",
    )
    diagnostic = _diagnostics(application)[0]
    assert diagnostic.field == "imports"
    assert "escapes" in diagnostic.message


def test_dynamic_sibling_and_repeated_parameter_collisions(
    tmp_path: Path, make_app: Callable[..., Path]
) -> None:
    application = make_app(tmp_path / "application")
    _package(application, "by_user_id")
    _package(application, "by_account_id")
    _package(application, "by_user_id/children")
    _package(application, "by_user_id/children/by_user_id")
    diagnostics = _diagnostics(application)
    assert all(diagnostic.code == "PYGANINI011" for diagnostic in diagnostics)
    assert any("dynamic siblings" in diagnostic.message for diagnostic in diagnostics)
    assert any(
        "repeats an ancestor" in diagnostic.message for diagnostic in diagnostics
    )


def test_dynamic_sibling_collision_names_sources_and_canonical_parent_route(
    tmp_path: Path, make_app: Callable[..., Path]
) -> None:
    application = make_app(tmp_path / "application")
    _package(application, "build_info")
    _package(application, "build_info/by_user_id")
    _package(application, "build_info/by_account_id")

    diagnostic = _diagnostics(application)[0]
    assert diagnostic.code == "PYGANINI011"
    assert "app/routes/build_info/by_account_id" in diagnostic.message
    assert "app/routes/build_info/by_user_id" in diagnostic.message
    assert "shared parent route '/build-info'" in diagnostic.message


@pytest.mark.parametrize(
    "surface",
    [
        "fragments=(fragment_route('/user_name', first), "
        "fragment_route('/user-name', second))",
        "actions=(action('POST', '/save_item', first), "
        "action('POST', '/save-item', second))",
    ],
)
def test_normalized_local_path_collisions_name_both_owners(
    tmp_path: Path,
    make_app: Callable[..., Path],
    surface: str,
) -> None:
    application = make_app(tmp_path / "application")
    _route(
        application / "app" / "routes",
        "from pyganini import action, fragment_route, route\n"
        "from .handlers import first, second\n"
        f"Route = route({surface})\n",
    )
    diagnostic = _diagnostics(application)[0]
    assert diagnostic.code == "PYGANINI011"
    assert "owned by" in diagnostic.message
    assert diagnostic.message.count("app/routes/route.py") == 2


def test_parent_surface_and_child_page_exact_collision_names_both_owners(
    tmp_path: Path, make_app: Callable[..., Path]
) -> None:
    application = make_app(tmp_path / "application")
    root = application / "app" / "routes"
    _route(
        root,
        "from pyganini import fragment_route, route\n"
        "from .handlers import users\n"
        "Route = route(fragments=(fragment_route('/users', users),))\n",
    )
    users = _package(application, "users")
    _route(
        users,
        "from pyganini import route\n"
        "from .handlers import page\n"
        "Route = route(page=page)\n",
    )
    diagnostics = _diagnostics(application)
    assert [diagnostic.code for diagnostic in diagnostics] == [
        "PYGANINI011",
        "PYGANINI011",
    ]
    assert {"GET", "HEAD"} == {
        diagnostic.message.split(" ", 1)[0] for diagnostic in diagnostics
    }
    assert all("fragment" in diagnostic.message for diagnostic in diagnostics)
    assert all("page" in diagnostic.message for diagnostic in diagnostics)


def test_page_fragment_and_actions_may_share_paths_across_reserved_methods(
    tmp_path: Path, make_app: Callable[..., Path]
) -> None:
    application = make_app(tmp_path / "application")
    _route(
        application / "app" / "routes",
        "from pyganini import action, fragment_route, route\n"
        "from .handlers import page, fragment_handler, post, patch\n"
        "Route = route(\n"
        " page=page,\n"
        " fragments=(fragment_route('/shared', fragment_handler),),\n"
        " actions=(action('POST', '/', post), action('PATCH', '/shared', patch)),\n"
        ")\n",
    )
    assert len(list(iter_endpoints(_graph(application)))) == 4


def test_page_and_index_fragment_is_a_declaration_failure(
    tmp_path: Path, make_app: Callable[..., Path]
) -> None:
    application = make_app(tmp_path / "application")
    _route(
        application / "app" / "routes",
        "from pyganini import fragment_route, route\n"
        "from .handlers import page, index\n"
        "Route = route(page=page, fragments=(fragment_route('/', index),))\n",
    )
    diagnostic = _diagnostics(application)[0]
    assert diagnostic.code == "PYGANINI010"
    assert "index fragment" in diagnostic.message


def test_records_endpoint_and_layout_template_evidence(
    tmp_path: Path, make_app: Callable[..., Path]
) -> None:
    application = make_app(tmp_path / "application")
    routes = application / "app" / "routes"
    (routes / "layout.py").write_text("VALUE = 1\n", encoding="ascii")
    (routes / "layout.jinja").write_text("<main>{{ child }}</main>\n")
    _route(
        routes,
        "from pyganini import action, fragment_route, route\n"
        "def page(request): return request\n"
        "def table(request): return request\n"
        "def save(request): return request\n"
        "Route = route(\n"
        " page=page, template='page.jinja',\n"
        " fragments=(fragment_route('/table', table, template='table.jinja'),),\n"
        " actions=(action('POST', '/save', save, template='form.jinja'),),\n"
        ")\n",
    )
    for name in ("page.jinja", "table.jinja", "form.jinja"):
        (routes / name).write_text("{{ value }}\n", encoding="ascii")

    graph = _graph(application)
    declaration = graph.nodes[0].declaration
    assert declaration is not None
    assert declaration.page_template is not None
    assert declaration.page_template.environment_name == "routes/page.jinja"
    assert declaration.page_template.source.path.as_posix() == "app/routes/page.jinja"
    assert declaration.page_template.source.line == 1
    assert declaration.page_template.declaration is not None
    assert declaration.page_template.declaration.path.as_posix() == (
        "app/routes/route.py"
    )
    assert declaration.page_template.declaration.line == 6
    assert declaration.fragments[0].template is not None
    assert declaration.fragments[0].template.environment_name == "routes/table.jinja"
    assert declaration.actions[0].template is not None
    assert declaration.actions[0].template.environment_name == "routes/form.jinja"
    assert graph.nodes[0].layout is not None
    assert graph.nodes[0].layout.template.source.path.as_posix() == (
        "app/routes/layout.jinja"
    )
    assert [
        cast(Any, endpoint.template).environment_name
        for endpoint in iter_endpoints(graph)
    ] == [
        "routes/page.jinja",
        "routes/table.jinja",
        "routes/form.jinja",
    ]


@pytest.mark.parametrize(
    ("template_expression", "message"),
    [
        ("PAGE_TEMPLATE", "string literal"),
        ("'page' + '.jinja'", "string literal"),
        ("'page' '.jinja'", "concatenation is unsupported"),
        ("f'page.jinja'", "string literal"),
        ("'Page.jinja'", "template must match"),
        ("'page-name.jinja'", "template must match"),
    ],
)
def test_template_declaration_expressions_fail_closed(
    tmp_path: Path,
    make_app: Callable[..., Path],
    template_expression: str,
    message: str,
) -> None:
    application = make_app(tmp_path / "application")
    _route(
        application / "app" / "routes",
        "from pyganini import route\n"
        "def page(request): return request\n"
        "PAGE_TEMPLATE = 'page.jinja'\n"
        f"Route = route(page=page, template={template_expression})\n",
    )
    diagnostic = _diagnostics(application)[0]
    assert diagnostic.code == "PYGANINI010"
    assert diagnostic.field == "template"
    assert message in diagnostic.message


def test_page_template_without_page_fails_before_filesystem_validation(
    tmp_path: Path, make_app: Callable[..., Path]
) -> None:
    application = make_app(tmp_path / "application")
    _route(
        application / "app" / "routes",
        "from pyganini import action, route\n"
        "def save(request): return request\n"
        "Route = route(template='missing.jinja', "
        "actions=(action('POST', '/', save),))\n",
    )
    diagnostics = _diagnostics(application)
    assert len(diagnostics) == 1
    assert diagnostics[0].code == "PYGANINI010"
    assert "page template requires a page handler" in diagnostics[0].message


@pytest.mark.parametrize("entry_kind", ["missing", "directory", "invalid-utf8"])
def test_required_endpoint_templates_fail_as_route_filesystem_diagnostics(
    tmp_path: Path,
    make_app: Callable[..., Path],
    entry_kind: str,
) -> None:
    application = make_app(tmp_path / "application")
    routes = application / "app" / "routes"
    _route(
        routes,
        "from pyganini import route\n"
        "def page(request): return request\n"
        "Route = route(page=page, template='page.jinja')\n",
    )
    template = routes / "page.jinja"
    if entry_kind == "directory":
        template.mkdir()
    elif entry_kind == "invalid-utf8":
        template.write_bytes(b"\xff")

    diagnostics = _diagnostics(application)
    diagnostic = next(item for item in diagnostics if "template" in item.message)
    assert diagnostic.code == "PYGANINI009"
    assert diagnostic.phase == "route-filesystem"
    assert diagnostic.path.as_posix() == "app/routes/page.jinja"


@pytest.mark.parametrize("entry_kind", ["missing", "symlink"])
def test_root_error_templates_use_held_filesystem_validation(
    tmp_path: Path,
    make_app: Callable[..., Path],
    entry_kind: str,
) -> None:
    application = make_app(tmp_path / "application")
    routes = application / "app" / "routes"
    _route(
        routes,
        "from pyganini import route\n"
        "Route = route(error_page_template='error_page.jinja')\n",
    )
    if entry_kind == "symlink":
        outside = tmp_path / "outside-error.jinja"
        outside.write_text("outside\n", encoding="ascii")
        os.symlink(outside, routes / "error_page.jinja")

    diagnostic = next(
        item for item in _diagnostics(application) if "template" in item.message
    )

    assert diagnostic.code == "PYGANINI009"
    assert diagnostic.phase == "route-filesystem"
    assert diagnostic.path.as_posix() == "app/routes/error_page.jinja"
    if entry_kind == "symlink":
        assert "symlink" in diagnostic.message


def test_required_templates_reject_symlinks_and_layouts_require_fixed_template(
    tmp_path: Path, make_app: Callable[..., Path]
) -> None:
    application = make_app(tmp_path / "application")
    routes = application / "app" / "routes"
    _route(
        routes,
        "from pyganini import route\n"
        "def page(request): return request\n"
        "Route = route(page=page, template='page.jinja')\n",
    )
    target = tmp_path / "outside.jinja"
    target.write_text("outside\n", encoding="ascii")
    os.symlink(target, routes / "page.jinja")
    (routes / "layout.py").write_text("VALUE = 1\n", encoding="ascii")

    diagnostics = _diagnostics(application)
    assert [item.path.as_posix() for item in diagnostics] == [
        "app/routes/layout.jinja",
        "app/routes/page.jinja",
    ]
    assert all(item.code == "PYGANINI009" for item in diagnostics)
    assert "symlink" in diagnostics[1].message


def test_template_content_does_not_change_graph_identity_but_name_does(
    tmp_path: Path, make_app: Callable[..., Path]
) -> None:
    application = make_app(tmp_path / "application")
    routes = application / "app" / "routes"
    route_file = routes / "route.py"
    route_file.write_text(
        "from pyganini import route\n"
        "def page(request): return request\n"
        "Route = route(page=page, template='page.jinja')\n",
        encoding="ascii",
    )
    template = routes / "page.jinja"
    template.write_text("first\n", encoding="ascii")
    first = _graph(application)
    template.write_text("second product text\n", encoding="ascii")
    assert _graph(application) == first

    route_file.write_text(
        route_file.read_text(encoding="ascii").replace("page.jinja", "other.jinja"),
        encoding="ascii",
    )
    (routes / "other.jinja").write_text("second product text\n", encoding="ascii")
    assert _graph(application) != first


def test_required_template_fifo_is_rejected_without_opening(
    tmp_path: Path, make_app: Callable[..., Path]
) -> None:
    if not hasattr(os, "mkfifo"):
        pytest.skip("host does not provide FIFO creation")
    application = make_app(tmp_path / "application")
    routes = application / "app" / "routes"
    _route(
        routes,
        "from pyganini import route\n"
        "def page(request): return request\n"
        "Route = route(page=page, template='page.jinja')\n",
    )
    os.mkfifo(routes / "page.jinja")
    diagnostic = next(
        item for item in _diagnostics(application) if "template" in item.message
    )
    assert diagnostic.code == "PYGANINI009"
    assert "regular file" in diagnostic.message


def test_template_read_stays_on_held_directory_after_ancestor_replacement(
    tmp_path: Path,
    make_app: Callable[..., Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    application = make_app(tmp_path / "application")
    package = _package(application, "users")
    _route(
        package,
        "from pyganini import route\n"
        "def page(request): return request\n"
        "Route = route(page=page, template='page.jinja')\n",
    )
    (package / "page.jinja").write_text("inside\n", encoding="ascii")
    outside = tmp_path / "outside-users"
    outside.mkdir()
    (outside / "__init__.py").write_text("", encoding="ascii")
    (outside / "route.py").write_text("outside is not route source", encoding="ascii")
    (outside / "page.jinja").write_bytes(b"\xff")
    saved = tmp_path / "saved-users"
    real_open = os.open
    swapped = False

    def replace_parent_before_template_open(
        path: str | os.PathLike[str],
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        nonlocal swapped
        if not swapped and os.fspath(path) == "page.jinja":
            package.rename(saved)
            os.symlink(outside, package)
            swapped = True
        return real_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(
        "pyganini._route_graph.os.open", replace_parent_before_template_open
    )
    try:
        graph = _graph(application)
    finally:
        if package.is_symlink():
            package.unlink()
        if saved.exists():
            saved.rename(package)

    assert swapped
    assert graph.nodes[1].declaration is not None
