# pyright: reportPrivateUsage=false

import json
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path, PurePosixPath

import pytest

from pyganini._dispatch_generation import dispatch_plan
from pyganini._inspection import (
    InspectionError,
    RouteInventoryRow,
    _error_render_evidence,
    _ErrorRenderEvidence,
    _render_unit_json,
    _render_unit_rows,
    _render_unit_text,
    _RenderUnitLayout,
    _RenderUnitRow,
    filter_mount,
    inventory_rows,
    render_json,
    render_payload,
    render_text,
)
from pyganini._paths import select_project_paths
from pyganini._route_graph import (
    SourcePosition,
    TemplateSource,
    _selected_layouts,
    build_route_graph,
    iter_endpoints,
)
from pyganini._url_generation import _url_helper_projection


def _package(parent: Path, relative: str) -> Path:
    package = parent
    for component in Path(relative).parts:
        package /= component
        package.mkdir(exist_ok=True)
        (package / "__init__.py").write_text("", encoding="ascii")
    return package


def _route(package: Path, source: str) -> None:
    (package / "route.py").write_text(source, encoding="ascii")


def test_inventory_rows_include_ordinary_endpoint_and_layout_surfaces(
    tmp_path: Path, make_app: Callable[..., Path]
) -> None:
    application = make_app(tmp_path / "application")
    routes = application / "app" / "routes"
    (routes / "layout.py").write_text("VALUE = 1\n", encoding="ascii")
    (routes / "layout.jinja").write_text("{{ child }}\n", encoding="ascii")
    (routes / "route.py").write_text(
        "from pyganini import action, fragment_route, route\n"
        "def page(request): return None\n"
        "def table(request): return None\n"
        "def save(request): return None\n"
        "Route = route(\n"
        "    page=page,\n"
        "    fragments=(fragment_route('/table', table),),\n"
        "    actions=(action('POST', '/save', save),),\n"
        ")\n",
        encoding="ascii",
    )

    paths = select_project_paths(explicit=application)
    graph = build_route_graph(paths)
    rows = inventory_rows(graph, _url_helper_projection(graph))

    assert [(row.kind, row.path, row.methods) for row in rows] == [
        ("layout", "/", ()),
        ("page", "/", ("GET", "HEAD")),
        ("action", "/save", ("POST",)),
        ("fragment", "/table", ("GET", "HEAD")),
    ]
    assert rows[1].helper == "urls.root.path"
    implementations = {
        row.kind: row.declaration.implementation
        for row in rows
        if row.declaration is not None
    }
    assert implementations["page"] is not None
    assert implementations["fragment"] is not None
    assert implementations["action"] is not None
    assert implementations["page"].declaration == SourcePosition(
        PurePosixPath("app/routes/route.py"), 6, 10
    )
    assert implementations["fragment"].declaration == SourcePosition(
        PurePosixPath("app/routes/route.py"), 7, 16
    )
    assert implementations["action"].declaration == SourcePosition(
        PurePosixPath("app/routes/route.py"), 8, 14
    )


def test_inventory_projects_metadata_and_root_error_facts_into_enriched_v1(
    tmp_path: Path, make_app: Callable[..., Path]
) -> None:
    application = make_app(tmp_path / "application")
    routes = application / "app" / "routes"
    (routes / "error_page.jinja").write_text("error\n", encoding="ascii")
    (routes / "error_fragment.jinja").write_text("error\n", encoding="ascii")
    _route(
        routes,
        "from pyganini import RouteMeta, route\n"
        "def page(request): return request\n"
        "Route = route(\n"
        "    page=page, name='home', title='Home',\n"
        "    meta=RouteMeta(labels={'area': 'public'}),\n"
        "    error_page_template='error_page.jinja',\n"
        "    error_fragment_template='error_fragment.jinja',\n"
        ")\n",
    )

    graph = build_route_graph(select_project_paths(explicit=application))
    rows = inventory_rows(graph, _url_helper_projection(graph))
    payload = json.loads(
        render_payload(rows, json_output=True, graph=graph, mount_selection=False)
    )

    assert list(payload) == ["schema", "error_render", "routes"]
    assert payload["schema"] == "pyganini.routes.v1"
    assert payload["error_render"]["page_template"]["name"] == (
        "routes/error_page.jinja"
    )
    row = payload["routes"][0]
    assert list(row)[-2:] == ["selection", "declaration"]
    assert row["selection"] is None
    assert row["declaration"]["kind"] == "route"
    assert row["declaration"]["name"] == "home"
    assert row["declaration"]["title"] == "Home"
    assert row["declaration"]["labels"][0]["key"] == "area"
    assert row["declaration"]["implementation"]["handler"]["binding"] == "page"


def test_inventory_projection_requires_graph_and_root_error_authority() -> None:
    with pytest.raises(TypeError, match="graph"):
        filter_mount((), "directory")
    with pytest.raises(TypeError, match="graph"):
        render_payload((), json_output=True)
    with pytest.raises(TypeError, match="error_render"):
        render_text(())
    with pytest.raises(TypeError, match="error_render"):
        render_json(())
    with pytest.raises(InspectionError, match="RouteGraph authority"):
        filter_mount((), None, graph=None)  # type: ignore[arg-type]
    with pytest.raises(InspectionError, match="RouteGraph authority"):
        render_payload((), json_output=True, graph=None)  # type: ignore[arg-type]
    with pytest.raises(InspectionError, match="error-render authority"):
        render_text((), error_render=None)  # type: ignore[arg-type]
    with pytest.raises(InspectionError, match="error-render authority"):
        render_json((), error_render=None)  # type: ignore[arg-type]


def test_mount_inventory_includes_excluded_source_candidates(
    tmp_path: Path, make_app: Callable[..., Path]
) -> None:
    application = make_app(tmp_path / "application")
    routes = application / "app" / "routes"
    _route(
        routes,
        "from pyganini import mount_route, route_mount\n"
        "def create(request): return object()\n"
        "Route = route_mount(\n"
        "    create=create, mount='directory', routes=(mount_route('/'),)\n"
        ")\n",
    )
    mounts = application / "app" / "mounts"
    mounts.mkdir()
    (mounts / "__init__.py").write_text("", encoding="ascii")
    source = _package(mounts, "directory")
    _route(
        source,
        "from pyganini import RouteMeta, route_kit\n"
        "def page(kit, request): return request\n"
        "Route = route_kit(page=page, meta=RouteMeta(labels={'area': 'root'}))\n",
    )
    child = _package(source, "create")
    _route(
        child,
        "from pyganini import RouteMeta, kit_action, route_kit\n"
        "def save(kit, request): return request\n"
        "Route = route_kit(\n"
        "    actions=(kit_action('POST', '/', save),),\n"
        "    meta=RouteMeta(labels={'area': 'create'}),\n"
        ")\n",
    )

    graph = build_route_graph(select_project_paths(explicit=application))
    rows = inventory_rows(graph, _url_helper_projection(graph))
    selected = filter_mount(rows, "directory", graph=graph)

    assert [(row.path, row.kind, row.selection) for row in selected] == [
        ("/", "page", "included"),
        ("/create", "route", "excluded"),
    ]
    excluded = selected[1]
    assert excluded.methods == ()
    assert excluded.helper is None
    assert excluded.declaration is not None
    assert excluded.declaration.implementation is None
    assert excluded.declaration.labels[0].value == "create"

    _route(
        routes,
        "from pyganini import mount_route, route_mount\n"
        "def create(request): return object()\n"
        "Route = route_mount(\n"
        "    create=create, mount='directory', routes=(mount_route('/create'),)\n"
        ")\n",
    )
    child_graph = build_route_graph(select_project_paths(explicit=application))
    child_rows = inventory_rows(child_graph, _url_helper_projection(child_graph))
    child_selected = filter_mount(child_rows, "directory", graph=child_graph)
    assert [(row.path, row.kind, row.selection) for row in child_selected] == [
        ("/", "route", "excluded"),
        ("/create", "action", "included"),
    ]

    _route(
        routes,
        "from pyganini import route_mount\n"
        "def create(request): return object()\n"
        "Route = route_mount(create=create, mount='directory')\n",
    )
    all_graph = build_route_graph(select_project_paths(explicit=application))
    all_rows = inventory_rows(all_graph, _url_helper_projection(all_graph))
    all_selected = filter_mount(all_rows, "directory", graph=all_graph)
    assert [(row.path, row.kind, row.selection) for row in all_selected] == [
        ("/", "page", "included"),
        ("/create", "action", "included"),
    ]


def test_mount_inventory_fails_closed_on_inconsistent_candidate_rows(
    tmp_path: Path, make_app: Callable[..., Path]
) -> None:
    application = make_app(tmp_path / "application")
    routes = application / "app" / "routes"
    _route(
        routes,
        "from pyganini import route_mount\n"
        "def create(request): return object()\n"
        "Route = route_mount(create=create, mount='directory')\n",
    )
    mounts = application / "app" / "mounts"
    mounts.mkdir()
    (mounts / "__init__.py").write_text("", encoding="ascii")
    source = _package(mounts, "directory")
    _route(
        source,
        "from pyganini import route_kit\n"
        "def page(kit, request): return request\n"
        "Route = route_kit(page=page)\n",
    )

    graph = build_route_graph(select_project_paths(explicit=application))
    rows = inventory_rows(graph, _url_helper_projection(graph))
    page = next(row for row in rows if row.kind == "page")

    without_page = tuple(row for row in rows if row is not page)
    with pytest.raises(InspectionError, match=r"included candidate.*no live endpoint"):
        filter_mount(without_page, "directory", graph=graph)

    extra_page = replace(page, source_path="/missing")
    with pytest.raises(InspectionError, match=r"live endpoint.*no included candidate"):
        filter_mount((*rows, extra_page), "directory", graph=graph)


@pytest.mark.parametrize(
    ("corruption", "expected"),
    [
        pytest.param(
            "normal-row-with-status",
            "normal route inventory row has a selection status",
            id="normal-status",
        ),
        pytest.param(
            "mount-row-without-status",
            "mount-selection row has no status",
            id="mount-status",
        ),
        pytest.param(
            "included-without-mount",
            "included page row has no mount",
            id="included-mount",
        ),
        pytest.param(
            "excluded-live-row",
            "live page row is marked excluded",
            id="excluded-live",
        ),
        pytest.param(
            "layout-declaration",
            "layout row has declaration evidence",
            id="layout-declaration",
        ),
        pytest.param("layout-methods", "layout row has methods", id="layout-methods"),
        pytest.param("layout-helper", "layout row has a helper", id="layout-helper"),
        pytest.param(
            "candidate-selection",
            "route candidate row is not excluded",
            id="candidate-selection",
        ),
        pytest.param(
            "candidate-methods",
            "excluded route candidate has methods",
            id="candidate-methods",
        ),
        pytest.param(
            "candidate-helper",
            "excluded route candidate has a helper",
            id="candidate-helper",
        ),
        pytest.param(
            "candidate-implementation",
            "excluded route candidate has implementation",
            id="candidate-implementation",
        ),
        pytest.param(
            "missing-declaration",
            "page row has no declaration",
            id="missing-declaration",
        ),
        pytest.param(
            "missing-implementation",
            "page row has no implementation",
            id="missing-implementation",
        ),
        pytest.param(
            "implementation-kind",
            "page row has fragment implementation",
            id="implementation-kind",
        ),
    ],
)
def test_inventory_renderers_reject_named_one_fact_corruptions(
    tmp_path: Path,
    make_app: Callable[..., Path],
    corruption: str,
    expected: str,
) -> None:
    application = make_app(tmp_path / "application")
    routes = application / "app" / "routes"
    _route(
        routes,
        "from pyganini import mount_route, route_mount\n"
        "def create(request): return object()\n"
        "Route = route_mount(\n"
        "    create=create, mount='directory', routes=(mount_route('/'),)\n"
        ")\n",
    )
    mounts = application / "app" / "mounts"
    mounts.mkdir()
    (mounts / "__init__.py").write_text("", encoding="ascii")
    source = _package(mounts, "directory")
    (source / "layout.py").write_text("VALUE = 1\n", encoding="ascii")
    (source / "layout.jinja").write_text("{{ child }}\n", encoding="ascii")
    _route(
        source,
        "from pyganini import route_kit\n"
        "def page(kit, request): return request\n"
        "Route = route_kit(page=page)\n",
    )
    excluded_source = _package(source, "extra")
    _route(
        excluded_source,
        "from pyganini import route_kit\n"
        "def page(kit, request): return request\n"
        "Route = route_kit(page=page)\n",
    )

    graph = build_route_graph(select_project_paths(explicit=application))
    rows = inventory_rows(graph, _url_helper_projection(graph))
    selected = filter_mount(rows, "directory", graph=graph)
    page = next(row for row in rows if row.kind == "page")
    layout = next(row for row in rows if row.kind == "layout")
    included = next(row for row in selected if row.kind == "page")
    candidate = next(row for row in selected if row.kind == "route")
    assert page.declaration is not None
    assert page.declaration.implementation is not None
    assert candidate.declaration is not None

    corruptions: dict[str, tuple[RouteInventoryRow, bool]] = {
        "normal-row-with-status": (replace(page, selection="included"), False),
        "mount-row-without-status": (page, True),
        "included-without-mount": (replace(included, mount=None), True),
        "excluded-live-row": (replace(included, selection="excluded"), True),
        "layout-declaration": (
            replace(layout, declaration=page.declaration),
            False,
        ),
        "layout-methods": (replace(layout, methods=("GET",)), False),
        "layout-helper": (replace(layout, helper="urls.root.path"), False),
        "candidate-selection": (replace(candidate, selection="included"), True),
        "candidate-methods": (replace(candidate, methods=("GET",)), True),
        "candidate-helper": (replace(candidate, helper="urls.root.path"), True),
        "candidate-implementation": (
            replace(
                candidate,
                declaration=replace(
                    candidate.declaration,
                    implementation=page.declaration.implementation,
                ),
            ),
            True,
        ),
        "missing-declaration": (replace(page, declaration=None), False),
        "missing-implementation": (
            replace(
                page,
                declaration=replace(page.declaration, implementation=None),
            ),
            False,
        ),
        "implementation-kind": (
            replace(
                page,
                declaration=replace(
                    page.declaration,
                    implementation=replace(
                        page.declaration.implementation,
                        kind="fragment",
                    ),
                ),
            ),
            False,
        ),
    }
    corrupted, mount_selection = corruptions[corruption]
    error_render = _error_render_evidence(graph)
    for renderer in (render_text, render_json):
        with pytest.raises(InspectionError) as captured:
            renderer(
                (corrupted,),
                error_render=error_render,
                mount_selection=mount_selection,
            )
        assert str(captured.value) == expected


def test_render_unit_rows_select_templates_and_preserve_layout_modes(
    tmp_path: Path, make_app: Callable[..., Path]
) -> None:
    application = make_app(tmp_path / "application")
    routes = application / "app" / "routes"
    (routes / "layout.py").write_text("VALUE = 1\n", encoding="ascii")
    (routes / "layout.jinja").write_text("{{ child }}\n", encoding="ascii")
    root_route = routes / "route.py"
    root_route.write_text(
        "from pyganini import route\n"
        "def root(request): return None\n"
        "Route = route(page=root)\n",
        encoding="ascii",
    )
    users = _package(routes, "users")
    (users / "layout.py").write_text("VALUE = 1\n", encoding="ascii")
    (users / "layout.jinja").write_text("{{ child }}\n", encoding="ascii")
    _route(
        users,
        "from pyganini import action, fragment_route, route\n"
        "def page(request): return None\n"
        "def table(request): return None\n"
        "def post(request): return None\n"
        "def put(request): return None\n"
        "def patch(request): return None\n"
        "def delete(request): return None\n"
        "def direct(request): return None\n"
        "Route = route(\n"
        "    page=page, template='page.jinja',\n"
        "    fragments=(fragment_route('/table', table, template='table.jinja'),),\n"
        "    actions=(\n"
        "        action('POST', '/post', post, template='post.jinja'),\n"
        "        action('PUT', '/put', put, template='put.jinja'),\n"
        "        action('PATCH', '/patch', patch, template='patch.jinja'),\n"
        "        action('DELETE', '/delete', delete, template='delete.jinja'),\n"
        "        action('POST', '/direct', direct),\n"
        "    ),\n"
        ")\n",
    )
    for name in ("page", "table", "post", "put", "patch", "delete"):
        (users / f"{name}.jinja").write_text("{{ value }}\n", encoding="ascii")

    graph = build_route_graph(select_project_paths(explicit=application))
    rows = _render_unit_rows(graph)

    assert isinstance(rows, tuple)
    assert [(row.kind, row.route, row.methods) for row in rows] == [
        ("page", "/users", ("GET", "HEAD")),
        ("action", "/users/delete", ("DELETE",)),
        ("action", "/users/patch", ("PATCH",)),
        ("action", "/users/post", ("POST",)),
        ("action", "/users/put", ("PUT",)),
        ("fragment", "/users/table", ("GET", "HEAD")),
    ]
    page = rows[0]
    assert page.layout_mode == "page"
    assert [
        (layout.source.path.as_posix(), layout.template.environment_name)
        for layout in page.effective_layouts
    ] == [
        ("app/routes/layout.py", "routes/layout.jinja"),
        ("app/routes/users/layout.py", "routes/users/layout.jinja"),
    ]
    assert rows[-1].layout_mode == "none"
    assert rows[-1].effective_layouts == ()
    assert all(row.layout_mode == "page-result" for row in rows[1:5])
    assert all(isinstance(row.effective_layouts, tuple) for row in rows)
    assert all(
        row.template.environment_name.startswith("routes/users/") for row in rows
    )


def test_render_unit_renderers_have_exact_schema_and_position_contracts() -> None:
    source = SourcePosition(PurePosixPath("app/routes/users/route.py"), 5, 1)
    template = TemplateSource(
        SourcePosition(PurePosixPath("app/routes/users/page.jinja"), 1, 1),
        "routes/users/page.jinja",
    )
    layout = SourcePosition(PurePosixPath("app/routes/layout.py"), 1, 1)
    layout_template = TemplateSource(
        SourcePosition(PurePosixPath("app/routes/layout.jinja"), 1, 1),
        "routes/layout.jinja",
    )

    assert _render_unit_text(()) == (
        b"KIND  METHOD  ROUTE  TEMPLATE  TEMPLATE_SOURCE  SOURCE  OWNER  MOUNT  "
        b"SOURCE_PATH  LAYOUT_MODE  EFFECTIVE_LAYOUTS\n"
    )
    payload = _render_unit_json(
        (
            _RenderUnitRow(
                "page",
                ("GET", "HEAD"),
                "/users",
                template,
                source,
                source,
                None,
                None,
                "page",
                (_RenderUnitLayout(layout, layout_template),),
            ),
        )
    )
    decoded = json.loads(payload)
    assert list(decoded) == ["schema", "render_units"]
    assert list(decoded["render_units"][0]) == [
        "kind",
        "methods",
        "route",
        "template",
        "source",
        "owner",
        "mount",
        "source_path",
        "layout_mode",
        "effective_layouts",
    ]
    assert decoded["render_units"][0]["template"] == {
        "name": "routes/users/page.jinja",
        "source": {
            "path": "app/routes/users/page.jinja",
            "line": 1,
            "column": 1,
        },
    }
    assert decoded["render_units"][0]["effective_layouts"] == [
        {
            "source": {
                "path": "app/routes/layout.py",
                "line": 1,
                "column": 1,
            },
            "template": {
                "name": "routes/layout.jinja",
                "source": {
                    "path": "app/routes/layout.jinja",
                    "line": 1,
                    "column": 1,
                },
            },
        }
    ]
    assert decoded["render_units"][0]["mount"] is None
    assert decoded["render_units"][0]["source_path"] is None


def test_selected_layouts_is_graph_owned_for_ordinary_and_mounted_endpoints(
    tmp_path: Path, make_app: Callable[..., Path]
) -> None:
    application = make_app(tmp_path / "application")
    routes = application / "app" / "routes"
    (routes / "layout.py").write_text("VALUE = 1\n", encoding="ascii")
    (routes / "layout.jinja").write_text("{{ child }}\n", encoding="ascii")
    (routes / "route.py").write_text(
        "from pyganini import route\n"
        "def page(request): return None\n"
        "Route = route(page=page)\n",
        encoding="ascii",
    )
    owner = _package(routes, "users")
    _route(
        owner,
        "from pyganini import route_mount\n"
        "def create(request): return None\n"
        "Route = route_mount(create=create, mount='directory')\n",
    )
    mounts = application / "app" / "mounts"
    mounts.mkdir()
    (mounts / "__init__.py").write_text("", encoding="ascii")
    source = _package(mounts, "directory")
    (source / "layout.py").write_text("VALUE = 1\n", encoding="ascii")
    (source / "layout.jinja").write_text("{{ child }}\n", encoding="ascii")
    _route(
        source,
        "from pyganini import route_kit\n"
        "def page(kit, request): return None\n"
        "Route = route_kit(page=page)\n",
    )

    graph = build_route_graph(select_project_paths(explicit=application))
    endpoints = tuple(iter_endpoints(graph))
    ordinary = next(endpoint for endpoint in endpoints if endpoint.path == "/")
    mounted = next(endpoint for endpoint in endpoints if endpoint.path == "/users")

    assert tuple(
        layout.source.path.as_posix() for layout in _selected_layouts(graph, ordinary)
    ) == ("app/routes/layout.py",)
    assert tuple(
        layout.source.path.as_posix() for layout in _selected_layouts(graph, mounted)
    ) == (
        "app/routes/layout.py",
        "app/mounts/directory/layout.py",
    )
    with pytest.raises(ValueError, match="endpoint source is absent from graph"):
        _selected_layouts(graph, replace(ordinary, node_path="/missing"))


def test_render_unit_rows_retain_shared_route_kit_template_evidence(
    tmp_path: Path, make_app: Callable[..., Path]
) -> None:
    application = make_app(tmp_path / "application")
    shared = application / "app" / "shared" / "reports"
    shared.mkdir(parents=True)
    (application / "app" / "shared" / "__init__.py").write_text("", encoding="ascii")
    (shared / "__init__.py").write_text("", encoding="ascii")
    (shared / "page.jinja").write_text("{{ value }}\n", encoding="ascii")
    (shared / "table.jinja").write_text("{{ value }}\n", encoding="ascii")
    users = _package(application / "app" / "routes", "users")
    _route(
        users,
        "from pyganini import kit_fragment_route, route_kit\n"
        "def create(request): return None\n"
        "def page(kit, request): return None\n"
        "def table(kit, request): return None\n"
        "Route = route_kit(\n"
        "    create=create, page=page, template='page.jinja',\n"
        "    template_root='shared/reports',\n"
        "    fragments=(kit_fragment_route(\n"
        "        '/table', table, template='table.jinja'\n"
        "    ),),\n"
        ")\n",
    )

    graph = build_route_graph(select_project_paths(explicit=application))
    rows = _render_unit_rows(graph)

    assert [(row.kind, row.route, row.template.environment_name) for row in rows] == [
        ("page", "/users", "shared/reports/page.jinja"),
        ("fragment", "/users/table", "shared/reports/table.jinja"),
    ]
    assert rows[0].template.source.path.as_posix() == ("app/shared/reports/page.jinja")
    assert rows[1].template.source.path.as_posix() == ("app/shared/reports/table.jinja")


def test_inventory_reuses_generated_helper_spelling_and_static_before_dynamic_order(
    tmp_path: Path, make_app: Callable[..., Path]
) -> None:
    application = make_app(tmp_path / "application")
    routes = application / "app" / "routes"
    (routes / "layout.py").write_text("VALUE = 1\n", encoding="ascii")
    (routes / "layout.jinja").write_text("{{ child }}\n", encoding="ascii")
    _route(
        routes,
        "from pyganini import route\n"
        "def page(request): return None\n"
        "Route = route(page=page)\n",
    )
    users = _package(routes, "users")
    (users / "layout.py").write_text("VALUE = 1\n", encoding="ascii")
    (users / "layout.jinja").write_text("{{ child }}\n", encoding="ascii")
    _route(
        users,
        "from pyganini import action, route\n"
        "def page(request): return None\n"
        "def save(request): return None\n"
        "Route = route(page=page, actions=(action('POST', '/', save),))\n",
    )
    _route(
        _package(users, "table"),
        "from pyganini import route\n"
        "def page(request): return None\n"
        "Route = route(page=page)\n",
    )
    _route(
        _package(users, "by_id"),
        "from pyganini import route\n"
        "def page(request): return None\n"
        "Route = route(page=page)\n",
    )
    reports = _package(routes, "teams/by_team_id/reports")
    _route(
        reports,
        "from pyganini import route\n"
        "def page(request): return None\n"
        "Route = route(page=page)\n",
    )

    paths = select_project_paths(explicit=application)
    graph = build_route_graph(paths)
    rows = inventory_rows(graph, _url_helper_projection(graph))
    endpoints = [row for row in rows if row.kind != "layout"]

    assert [(row.path, row.kind) for row in rows] == [
        ("/", "layout"),
        ("/", "page"),
        ("/teams/{team_id}/reports", "page"),
        ("/users", "layout"),
        ("/users", "page"),
        ("/users", "action"),
        ("/users/table", "page"),
        ("/users/{id}", "page"),
    ]
    assert [(row.path, row.helper, row.parameters) for row in endpoints] == [
        ("/", "urls.root.path", ()),
        (
            "/teams/{team_id}/reports",
            "urls.teams.by_team_id(team_id).reports.path",
            ("team_id",),
        ),
        ("/users", "urls.users.path", ()),
        ("/users", "urls.users.path", ()),
        ("/users/table", "urls.users.table.path", ()),
        ("/users/{id}", "urls.users.by_id(id).path", ("id",)),
    ]


def test_inventory_order_is_local_and_generated_dispatch_keeps_graph_order(
    tmp_path: Path, make_app: Callable[..., Path]
) -> None:
    application = make_app(tmp_path / "application")
    routes = application / "app" / "routes"
    (routes / "route.py").write_text(
        "from pyganini import route\n"
        "def page(request): return None\n"
        "Route = route(page=page)\n",
        encoding="ascii",
    )
    static = _package(routes, "a_b")
    _route(
        static,
        "from pyganini import route\n"
        "def page(request): return None\n"
        "Route = route(page=page)\n",
    )
    dynamic = _package(routes, "a/by_id")
    _route(
        dynamic,
        "from pyganini import route\n"
        "def page(request): return None\n"
        "Route = route(page=page)\n",
    )

    graph = build_route_graph(select_project_paths(explicit=application))
    assert [node.route_path for node in graph.nodes] == [
        "/",
        "/a",
        "/a-b",
        "/a/{id}",
    ]

    rows = inventory_rows(graph, _url_helper_projection(graph))
    assert [row.path for row in rows if row.kind == "page"] == [
        "/",
        "/a/{id}",
        "/a-b",
    ]
    generated = dispatch_plan(graph)[0].content
    assert generated.index(b"                '/a-b',") < generated.index(
        b"                '/a/{id}',"
    )


def test_inventory_reports_selected_mounted_endpoints_and_effective_layouts(
    tmp_path: Path, make_app: Callable[..., Path]
) -> None:
    application = make_app(tmp_path / "application")
    routes = application / "app" / "routes"
    (routes / "layout.py").write_text("VALUE = 1\n", encoding="ascii")
    (routes / "layout.jinja").write_text("{{ child }}\n", encoding="ascii")

    users = _package(routes, "users")
    (users / "layout.py").write_text("VALUE = 1\n", encoding="ascii")
    (users / "layout.jinja").write_text("{{ child }}\n", encoding="ascii")
    _route(
        users,
        "from pyganini import route_mount\n"
        "def create(request): return None\n"
        "Route = route_mount(create=create, mount='directory')\n",
    )
    settings_users = _package(routes, "settings/users")
    (settings_users / "layout.py").write_text("VALUE = 1\n", encoding="ascii")
    (settings_users / "layout.jinja").write_text("{{ child }}\n", encoding="ascii")
    _route(
        settings_users,
        "from pyganini import mount_route, route_mount\n"
        "def create(request): return None\n"
        "Route = route_mount(\n"
        "    create=create, mount='directory', routes=(mount_route('/'),)\n"
        ")\n",
    )
    child_only = _package(routes, "contacts")
    _route(
        child_only,
        "from pyganini import mount_route, route_mount\n"
        "def create(request): return None\n"
        "Route = route_mount(\n"
        "    create=create, mount='directory', routes=(mount_route('/{id}'),)\n"
        ")\n",
    )

    mounts = application / "app" / "mounts"
    mounts.mkdir()
    (mounts / "__init__.py").write_text("", encoding="ascii")
    directory = _package(mounts, "directory")
    (directory / "layout.py").write_text("VALUE = 1\n", encoding="ascii")
    (directory / "layout.jinja").write_text("{{ child }}\n", encoding="ascii")
    _route(
        directory,
        "from pyganini import kit_fragment_route, route_kit\n"
        "def page(kit, request): return None\n"
        "def table(kit, request): return None\n"
        "Route = route_kit(\n"
        "    page=page, template='page.jinja',\n"
        "    fragments=(kit_fragment_route('/table', table, template='table.jinja'),)\n"
        ")\n",
    )
    (directory / "page.jinja").write_text("{{ value }}\n", encoding="ascii")
    (directory / "table.jinja").write_text("{{ value }}\n", encoding="ascii")
    detail = _package(directory, "by_id")
    (detail / "layout.py").write_text("VALUE = 1\n", encoding="ascii")
    (detail / "layout.jinja").write_text("{{ child }}\n", encoding="ascii")
    _route(
        detail,
        "from pyganini import route_kit\n"
        "def page(kit, request): return None\n"
        "Route = route_kit(page=page)\n",
    )
    create = _package(directory, "create")
    _route(
        create,
        "from pyganini import kit_action, route_kit\n"
        "def save(kit, request): return None\n"
        "Route = route_kit(actions=(kit_action('POST', '/', save),))\n",
    )

    paths = select_project_paths(explicit=application)
    graph = build_route_graph(paths)
    rows = inventory_rows(graph, _url_helper_projection(graph))
    mounted = filter_mount(rows, "directory", graph=graph)

    row_keys = {(row.path, row.kind) for row in rows}
    assert ("/settings/users/create", "action") not in row_keys
    assert ("/settings/users/{id}", "page") not in row_keys
    assert {
        (row.path, row.kind, row.source_path, row.owner.path.as_posix())
        for row in mounted
        if row.kind != "layout" and row.selection == "included"
    } == {
        ("/users", "page", "/", "app/routes/users/route.py"),
        ("/users/table", "fragment", "/", "app/routes/users/route.py"),
        ("/users/create", "action", "/create", "app/routes/users/route.py"),
        ("/users/{id}", "page", "/{id}", "app/routes/users/route.py"),
        ("/settings/users", "page", "/", "app/routes/settings/users/route.py"),
        (
            "/settings/users/table",
            "fragment",
            "/",
            "app/routes/settings/users/route.py",
        ),
        ("/contacts/{id}", "page", "/{id}", "app/routes/contacts/route.py"),
    }
    assert {
        (
            row.path,
            row.source.path.as_posix(),
            row.source_path,
            row.owner.path.as_posix(),
        )
        for row in mounted
        if row.kind == "layout"
    } == {
        ("/users", "app/mounts/directory/layout.py", "/", "app/routes/users/route.py"),
        (
            "/users/{id}",
            "app/mounts/directory/by_id/layout.py",
            "/{id}",
            "app/routes/users/route.py",
        ),
        (
            "/settings/users",
            "app/mounts/directory/layout.py",
            "/",
            "app/routes/settings/users/route.py",
        ),
        (
            "/contacts/{id}",
            "app/mounts/directory/by_id/layout.py",
            "/{id}",
            "app/routes/contacts/route.py",
        ),
        (
            "/contacts",
            "app/mounts/directory/layout.py",
            "/",
            "app/routes/contacts/route.py",
        ),
    }
    assert {
        (row.path, row.source_path, row.owner.path.as_posix())
        for row in mounted
        if row.selection == "excluded"
    } == {
        ("/settings/users/create", "/create", "app/routes/settings/users/route.py"),
        ("/settings/users/{id}", "/{id}", "app/routes/settings/users/route.py"),
        ("/contacts", "/", "app/routes/contacts/route.py"),
        ("/contacts/create", "/create", "app/routes/contacts/route.py"),
    }
    assert all(row.mount == "directory" for row in mounted)
    assert all(
        row.source.path.as_posix() != "app/routes/users/layout.py" for row in mounted
    )


def test_inventory_reports_nested_mount_identity_and_exact_filtering(
    tmp_path: Path, make_app: Callable[..., Path]
) -> None:
    application = make_app(tmp_path / "application")
    routes = application / "app" / "routes"
    (routes / "layout.py").write_text("VALUE = 1\n", encoding="ascii")
    (routes / "layout.jinja").write_text("{{ child }}\n", encoding="ascii")
    owner = _package(routes, "organizations/by_org_id/users")
    (owner / "layout.py").write_text("VALUE = 1\n", encoding="ascii")
    (owner / "layout.jinja").write_text("{{ child }}\n", encoding="ascii")
    _route(
        owner,
        "from pyganini import mount_route, route_mount\n"
        "def create(request): return None\n"
        "Route = route_mount(\n"
        "    create=create, mount='reports/audit',\n"
        "    routes=(mount_route('/'), mount_route('/{contact_id}')),\n"
        ")\n",
    )

    mounts = application / "app" / "mounts"
    mounts.mkdir()
    (mounts / "__init__.py").write_text("", encoding="ascii")
    audit = _package(mounts, "reports/audit")
    (audit / "layout.py").write_text("VALUE = 1\n", encoding="ascii")
    (audit / "layout.jinja").write_text("{{ child }}\n", encoding="ascii")
    _route(
        audit,
        "from pyganini import kit_fragment_route, route_kit\n"
        "def page(kit, request): return None\n"
        "def table(kit, request): return None\n"
        "Route = route_kit(\n"
        "    page=page, template='page.jinja',\n"
        "    fragments=(kit_fragment_route('/table', table, template='table.jinja'),)\n"
        ")\n",
    )
    (audit / "page.jinja").write_text("{{ value }}\n", encoding="ascii")
    (audit / "table.jinja").write_text("{{ value }}\n", encoding="ascii")
    child = _package(audit, "by_contact_id")
    (child / "layout.py").write_text("VALUE = 1\n", encoding="ascii")
    (child / "layout.jinja").write_text("{{ child }}\n", encoding="ascii")
    _route(
        child,
        "from pyganini import route_kit\n"
        "def page(kit, request): return None\n"
        "Route = route_kit(page=page, template='detail.jinja')\n",
    )
    (child / "detail.jinja").write_text("{{ value }}\n", encoding="ascii")

    graph = build_route_graph(select_project_paths(explicit=application))
    rows = inventory_rows(graph, _url_helper_projection(graph))
    filtered = filter_mount(rows, "reports/audit", graph=graph)

    expected = [
        (
            "/organizations/{org_id}/users",
            "layout",
            "app/mounts/reports/audit/layout.py",
            "/",
        ),
        (
            "/organizations/{org_id}/users",
            "page",
            "app/mounts/reports/audit/route.py",
            "/",
        ),
        (
            "/organizations/{org_id}/users/table",
            "fragment",
            "app/mounts/reports/audit/route.py",
            "/",
        ),
        (
            "/organizations/{org_id}/users/{contact_id}",
            "layout",
            "app/mounts/reports/audit/by_contact_id/layout.py",
            "/{contact_id}",
        ),
        (
            "/organizations/{org_id}/users/{contact_id}",
            "page",
            "app/mounts/reports/audit/by_contact_id/route.py",
            "/{contact_id}",
        ),
    ]
    assert [
        (row.path, row.kind, row.source.path.as_posix(), row.source_path)
        for row in rows
        if row.mount == "reports/audit"
    ] == expected
    assert [
        (row.path, row.kind, row.source.path.as_posix(), row.source_path)
        for row in filtered
    ] == expected
    assert filtered == tuple(
        replace(row, selection="included")
        for row in rows
        if row.mount == "reports/audit"
    )
    assert any(
        row.path == "/" and row.kind == "layout" and row.mount is None for row in rows
    )
    assert all(
        row.owner.path.as_posix() == "app/routes/organizations/by_org_id/users/route.py"
        for row in filtered
    )
    render_units = _render_unit_rows(graph)
    assert [
        (
            row.route,
            row.kind,
            row.template.environment_name,
            row.mount,
            row.source_path,
        )
        for row in render_units
    ] == [
        (
            "/organizations/{org_id}/users",
            "page",
            "mounts/reports/audit/page.jinja",
            "reports/audit",
            "/",
        ),
        (
            "/organizations/{org_id}/users/table",
            "fragment",
            "mounts/reports/audit/table.jinja",
            "reports/audit",
            "/",
        ),
        (
            "/organizations/{org_id}/users/{contact_id}",
            "page",
            "mounts/reports/audit/by_contact_id/detail.jinja",
            "reports/audit",
            "/{contact_id}",
        ),
    ]
    assert [
        layout.template.environment_name for layout in render_units[0].effective_layouts
    ] == [
        "routes/layout.jinja",
        "routes/organizations/by_org_id/users/layout.jinja",
        "mounts/reports/audit/layout.jinja",
    ]


def test_inventory_renderers_have_exact_empty_contracts() -> None:
    error_render = _ErrorRenderEvidence(None, None, ())
    source = SourcePosition(PurePosixPath("app/routes/users/route.py"), 5, 1)
    row = RouteInventoryRow(
        "page",
        ("GET", "HEAD"),
        "/users/{id}",
        ("id",),
        source,
        source,
        None,
        None,
        "urls.users.by_id(id).path",
    )

    assert render_text((), error_render=error_render) == (
        b"KIND  METHOD  PATH  PARAMS  SOURCE  OWNER  MOUNT  SOURCE_PATH  DECL  "
        b"NAME  TITLE  LABELS  NAV  TRAIL_KEYS  DESTINATIONS  INBOUND  "
        b"IMPLEMENTATION  HELPER\n"
        b"ERROR_RENDER page=- fragment=- root_layouts=[]\n"
    )
    assert render_json((), error_render=error_render) == (
        b'{\n  "schema": "pyganini.routes.v1",\n  "error_render": {\n'
        b'    "page_template": null,\n    "fragment_template": null,\n'
        b'    "root_layouts": []\n  },\n  "routes": []\n}\n'
    )
    with pytest.raises(InspectionError, match="page row has no declaration"):
        render_json((row,), error_render=error_render)
