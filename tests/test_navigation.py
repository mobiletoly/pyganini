# pyright: reportPrivateUsage=false

import asyncio
import importlib
import sys
from collections.abc import Callable
from copy import copy, deepcopy
from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import Any, cast
from urllib.parse import quote, urlsplit

import pytest
from fastapi import FastAPI
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Mount
from starlette.testclient import TestClient

import pyganini._navigation as navigation_module
from pyganini import (
    Destination,
    Navigation,
    NavigationBack,
    NavigationCurrent,
    NavTrailStep,
    RouteNav,
    current_nav_step,
    mount_route,
    nav,
    nav_step,
    route,
    to,
)
from pyganini._cli import main
from pyganini._dispatch import DispatchError, _Evidence, build_endpoint
from pyganini._generation import GenerationError
from pyganini._navigation import (
    _navigation_href,
    _NavigationState,
    _prepare_navigation,
    _safe_return_to,
)
from pyganini._paths import select_project_paths
from pyganini._route_graph import _resolve_target_selector, build_route_graph
from pyganini._url_generation import url_plan


def _empty_rendering(evidence: dict[str, _Evidence]) -> dict[str, Any]:
    return {method: (None, (), None, (), ()) for method in evidence}


def _empty_embedded(evidence: dict[str, _Evidence]) -> dict[str, Any]:
    return {method: () for method in evidence}


class Target:
    route_pattern = "/reports/{report_id}"


def page(request: object) -> object:
    return request


def _navigation_request(
    *,
    root_path: str = "",
    path: str = "/reports/r 1",
    query_string: bytes = b"",
    method: str = "GET",
) -> Request:
    return Request(
        {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": method,
            "scheme": "http",
            "path": path,
            "raw_path": path.encode(),
            "query_string": query_string,
            "root_path": root_path,
            "headers": [],
            "client": ("127.0.0.1", 1),
            "server": ("testserver", 80),
            "state": {},
            "path_params": {"report_id": "r 1"},
        }
    )


def test_empty_root_path_preserves_navigation_and_destination_bytes() -> None:
    request = _navigation_request(query_string=b"filter=active&filter=recent")
    _prepare_navigation(
        request,
        facts=(
            ("Home", None, "/", False),
            (None, "report", "/reports/{report_id}", True),
        ),
    )
    request_navigation = nav(request)
    request_navigation.resolve("report", "Report")
    navigation = request_navigation.navigation()

    assert navigation == Navigation(
        (nav_step("Home", "/"), current_nav_step("Report")),
        NavigationBack("/", "Home", True),
        NavigationCurrent("/reports/r%201", "Report", True),
    )
    assert (
        _navigation_href(navigation, "/contacts/42")
        == "/contacts/42?_pyganini_return_to="
        "%2Freports%2Fr%201%3Ffilter%3Dactive%26filter%3Drecent"
    )


def test_effective_root_path_prefixes_canonical_navigation_once() -> None:
    request = _navigation_request(
        root_path="/directory",
        path="/directory/reports/r 1",
    )
    _prepare_navigation(
        request,
        facts=(
            (None, "home", "/", False),
            (None, "report", "/reports/{report_id}", True),
        ),
    )
    request_navigation = nav(request)
    request_navigation.resolve_href("home", "Custom", "/application-owned")
    request_navigation.resolve("report", "Report")
    overridden = request_navigation.navigation()
    assert overridden.trail[0] == nav_step("Custom", "/application-owned")
    assert request_navigation.navigation_with_trail(
        (nav_step("Outside", "/application-owned/custom"),)
    ).trail == (nav_step("Outside", "/application-owned/custom"),)
    request_navigation.resolve("home", "Home")
    navigation = request_navigation.navigation()

    assert navigation.trail == (
        nav_step("Home", "/directory/"),
        current_nav_step("Report"),
    )
    assert navigation.current == NavigationCurrent(
        "/directory/reports/r%201", "Report", True
    )
    assert navigation.back == NavigationBack("/directory/", "Home", True)
    assert (
        _navigation_href(navigation, "/directory/contacts/42")
        == "/directory/contacts/42?_pyganini_return_to=%2Fdirectory%2Freports%2Fr%201"
    )


def test_request_navigation_uses_the_external_pattern_binding_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, object, object]] = []

    def bind_external_pattern(
        pattern: str,
        path_params: object,
        *,
        base_path: object,
    ) -> str:
        calls.append((pattern, path_params, base_path))
        return "/bound-by-owner"

    monkeypatch.setattr(
        navigation_module,
        "bind_external_pattern",
        bind_external_pattern,
    )
    request = _navigation_request(root_path="/directory")
    _prepare_navigation(
        request,
        facts=(("Report", None, "/reports/{report_id}", True),),
    )

    assert nav(request).navigation().current.href == "/bound-by-owner"
    assert calls == [
        ("/reports/{report_id}", request.path_params, "/directory"),
    ]


@pytest.mark.parametrize(
    ("return_to", "expected_back"),
    (
        ("/directory/reports", "/directory/reports"),
        ("/directoryish/reports", "/directory/"),
        ("/reports", "/directory/"),
        ("/directory/./admin", "/directory/"),
        ("/directory/%2e/admin", "/directory/"),
        ("/directory/../admin", "/directory/"),
        ("/directory/%2e%2e/admin", "/directory/"),
    ),
)
def test_nonempty_root_path_contains_inbound_return_to(
    return_to: str,
    expected_back: str,
) -> None:
    request = _navigation_request(
        root_path="/directory",
        path="/directory/reports/r 1",
        query_string=(
            "_pyganini_nav_trail_key=from-home&_pyganini_return_to="
            + quote(return_to, safe="")
        ).encode(),
    )
    _prepare_navigation(
        request,
        facts=(
            ("Home", None, "/", False),
            (None, "report", "/reports/{report_id}", True),
        ),
        accepted_keys=("from-home",),
    )
    request_navigation = nav(request)
    request_navigation.resolve("report", "Report")

    assert request_navigation.navigation().back.href == expected_back


@pytest.mark.parametrize(
    ("root_path", "external_base_path"),
    (
        ("/tenant%2Fblue", "/tenant%252Fblue"),
        ("/tenant%5Cblue", "/tenant%255Cblue"),
        ("/tenant%ZZblue", "/tenant%25ZZblue"),
        ("/%2E", "/%252E"),
        ("/%2E%2E", "/%252E%252E"),
        ("/tenant?blue", "/tenant%3Fblue"),
        ("/tenant#blue", "/tenant%23blue"),
    ),
)
def test_decoded_root_path_round_trips_captured_return(
    root_path: str,
    external_base_path: str,
) -> None:
    source_request = _navigation_request(
        root_path=root_path,
        path=root_path + "/reports/r 1",
        query_string=b"filter=active",
    )
    _prepare_navigation(
        source_request,
        facts=(("Reports", None, "/reports/{report_id}", True),),
    )
    source_navigation = nav(source_request).navigation()
    destination_href = _navigation_href(
        source_navigation,
        external_base_path + "/target?_pyganini_nav_trail_key=from-home",
    )

    target_request = _navigation_request(
        root_path=root_path,
        path=root_path + "/target",
        query_string=urlsplit(destination_href).query.encode("ascii"),
    )
    _prepare_navigation(
        target_request,
        facts=(
            ("Home", None, "/", False),
            ("Target", None, "/target", True),
        ),
        accepted_keys=("from-home",),
    )

    assert nav(target_request).navigation().back == NavigationBack(
        external_base_path + "/reports/r 1?filter=active",
        "Home",
        True,
    )


def test_head_capture_and_repeated_prefix_text_are_not_rewritten() -> None:
    request = _navigation_request(
        root_path="/directory",
        path="/directory/directory/users",
        method="HEAD",
    )
    _prepare_navigation(
        request,
        facts=(("Users", None, "/directory/users", True),),
    )
    navigation = nav(request).navigation()

    assert navigation.current.href == "/directory/directory/users"
    assert (
        _navigation_href(navigation, "/directory/target") == "/directory/target?"
        "_pyganini_return_to=%2Fdirectory%2Fdirectory%2Fusers"
    )


def test_navigation_public_values_are_frozen_and_validated() -> None:
    assert RouteNav(label=" Reports ").label == "Reports"
    assert RouteNav(key="report_id").key == "report_id"
    target = Target()
    destination = to("report-detail", target, trail_key="from-customers")
    assert destination == Destination("report-detail", target, "from-customers")
    assert copy(destination) == destination
    copied = deepcopy(destination)
    assert copied is not destination
    assert (copied.name, copied.target.route_pattern, copied.trail_key) == (
        destination.name,
        destination.target.route_pattern,
        destination.trail_key,
    )
    assert nav_step("Reports", "/reports") == NavTrailStep("Reports", "/reports")
    assert current_nav_step("Report") == NavTrailStep("Report", "", True)
    assert Navigation() == Navigation((), NavigationBack(), NavigationCurrent())

    with pytest.raises((TypeError, ValueError)):
        RouteNav()
    with pytest.raises((TypeError, ValueError)):
        RouteNav(label="Reports", key="report")
    with pytest.raises((TypeError, ValueError)):
        RouteNav(key="Report")
    with pytest.raises((TypeError, ValueError)):
        nav_step("Reports", "")
    with pytest.raises((TypeError, ValueError)):
        NavTrailStep("Report", "/reports", True)
    with pytest.raises(FrozenInstanceError):
        RouteNav(label="Reports").label = "Changed"  # type: ignore[misc]


def test_navigation_facade_is_inert_and_custom_trails_are_detached() -> None:
    inert = nav(None)
    inert.resolve("report", "Ignored")
    assert inert.navigation() == Navigation()
    assert inert.navigation_with_trail((current_nav_step("Current"),)) == Navigation(
        (current_nav_step("Current"),),
        current=NavigationCurrent(label="Current", ok=True),
    )


def test_route_declarations_own_navigation_values() -> None:
    target = Target()
    declared = route(
        page=page,
        nav=RouteNav(key="report"),
        destinations=(to("report-detail", target, trail_key="from-customers"),),
    )
    selected = mount_route(
        "/reports",
        nav=RouteNav(label="Reports"),
        destinations=(to("report-detail", target),),
    )

    assert declared.nav == RouteNav(key="report")
    assert declared.destinations[0].name == "report-detail"
    assert selected.nav == RouteNav(label="Reports")
    assert selected.destinations[0].target.route_pattern == "/reports/{report_id}"


def test_runtime_destinations_reject_names_that_share_a_python_member() -> None:
    target = Target()

    with pytest.raises(ValueError, match="duplicate"):
        route(
            page=page,
            destinations=(
                to("report-detail", target),
                to("report_detail", target),
            ),
        )


def test_static_by_member_selector_resolves_against_the_exact_live_url_path() -> None:
    assert _resolve_target_selector(("users", "by_id"), ("/users/by-id",)) == (
        "/users/by-id"
    )


def test_route_graph_retains_literal_navigation_and_destination_facts(
    tmp_path: Path,
    make_app: Callable[..., Path],
) -> None:
    application = make_app(tmp_path / "application")
    routes = application / "app" / "routes"
    (routes / "route.py").write_text(
        "from app._pyganini.urls import urls\n"
        "from pyganini import RouteNav, route, to\n"
        "def page(request): return object()\n"
        "Route = route(\n"
        "    page=page,\n"
        "    nav=RouteNav(label='Home'),\n"
        "    destinations=(to(\n"
        "        'report-detail', urls.reports.by_report_id, trail_key='from-home'\n"
        "    ),),\n"
        ")\n",
        encoding="ascii",
    )
    target = routes / "reports" / "by_report_id"
    target.mkdir(parents=True)
    (target.parent / "__init__.py").write_text("", encoding="ascii")
    (target / "__init__.py").write_text("", encoding="ascii")
    (target / "route.py").write_text(
        "from pyganini import RouteNav, route\n"
        "def page(request): return object()\n"
        "Route = route(page=page, nav=RouteNav(key='report'))\n",
        encoding="ascii",
    )

    graph = build_route_graph(
        select_project_paths(explicit=application, start=application)
    )
    root = next(node for node in graph.nodes if node.route_path == "/")
    report = next(
        node for node in graph.nodes if node.route_path == "/reports/{report_id}"
    )
    assert root.declaration is not None
    assert root.declaration.nav is not None
    assert root.declaration.nav.value.label == "Home"
    assert root.declaration.destinations[0].target_path == "/reports/{report_id}"
    assert report.declaration is not None
    assert report.declaration.nav is not None
    assert report.declaration.nav.value.key == "report"
    generated = url_plan(graph)[0].content
    compile(generated, "app/_pyganini/urls.py", "exec")
    text = generated.decode("ascii")
    assert "class _URLTarget" in text
    assert "route_pattern" in text
    assert "def __call__(self, report_id: str)" in text
    assert "destinations" in text
    assert "trail_keys" in text


def test_generated_navigation_targets_and_destinations_keep_call_syntax(
    tmp_path: Path,
    make_app: Callable[..., Path],
) -> None:
    application = make_app(tmp_path / "application")
    routes = application / "app" / "routes"
    (routes / "route.py").write_text(
        "from app._pyganini.urls import urls\n"
        "from pyganini import RouteNav, route, to\n"
        "def page(request): return object()\n"
        "Route = route(\n"
        "    page=page, nav=RouteNav(label='Home'),\n"
        "    destinations=(to('report-detail', urls.reports.by_report_id,\n"
        "        trail_key='from-home'),),\n"
        ")\n",
        encoding="ascii",
    )
    target = routes / "reports" / "by_report_id"
    target.mkdir(parents=True)
    (target.parent / "__init__.py").write_text("", encoding="ascii")
    (target / "__init__.py").write_text("", encoding="ascii")
    (target / "route.py").write_text(
        "from pyganini import RouteNav, route\n"
        "def page(request): return object()\n"
        "Route = route(page=page, nav=RouteNav(key='report'))\n",
        encoding="ascii",
    )
    generated_directory = application / "app" / "_pyganini"
    generated_directory.mkdir()
    (generated_directory / "__init__.py").write_text("", encoding="ascii")
    graph = build_route_graph(
        select_project_paths(explicit=application, start=application)
    )
    (generated_directory / "urls.py").write_bytes(url_plan(graph)[0].content)
    sys.path.insert(0, str(application))
    try:
        generated = importlib.import_module("app._pyganini.urls")
        target_value = generated.urls.reports.by_report_id
        assert target_value.route_pattern == "/reports/{report_id}"
        assert target_value("r 1").path == "/reports/r%201"
        assert (
            generated.urls.destinations.report_detail("r 1").href
            == "/reports/r%201?_pyganini_nav_trail_key=from-home"
        )
        assert generated.urls.reports.by_report_id.trail_keys.from_home == "from-home"
    finally:
        sys.path.remove(str(application))
        for name in tuple(sys.modules):
            if name == "app" or name.startswith("app."):
                del sys.modules[name]


def test_navigation_target_with_self_parameter_remains_importable(
    tmp_path: Path,
    make_app: Callable[..., Path],
) -> None:
    application = make_app(tmp_path / "application")
    routes = application / "app" / "routes"
    (routes / "route.py").write_text(
        "from app._pyganini.urls import urls\n"
        "from pyganini import RouteNav, route, to\n"
        "def page(request): return object()\n"
        "Route = route(\n"
        "    page=page, nav=RouteNav(label='Home'),\n"
        "    destinations=(to('self-target', urls.items.by_self),),\n"
        ")\n",
        encoding="ascii",
    )
    target = routes / "items" / "by_self"
    target.mkdir(parents=True)
    (target.parent / "__init__.py").write_text("", encoding="ascii")
    (target / "__init__.py").write_text("", encoding="ascii")
    (target / "route.py").write_text(
        "from pyganini import RouteNav, route\n"
        "def page(request): return object()\n"
        "Route = route(page=page, nav=RouteNav(key='item'))\n",
        encoding="ascii",
    )

    graph = build_route_graph(
        select_project_paths(explicit=application, start=application)
    )
    generated = url_plan(graph)[0].content
    compile(generated, "app/_pyganini/urls.py", "exec")
    assert "def __call__(instance, self: str)" in generated.decode("ascii")


def test_destination_with_self_and_instance_parameters_remains_valid_python(
    tmp_path: Path,
    make_app: Callable[..., Path],
) -> None:
    application = make_app(tmp_path / "application")
    routes = application / "app" / "routes"
    (routes / "route.py").write_text(
        "from app._pyganini.urls import urls\n"
        "from pyganini import RouteNav, route, to\n"
        "from starlette.responses import PlainTextResponse\n"
        "def page(request): return PlainTextResponse('root')\n"
        "Route = route(\n"
        "    page=page, nav=RouteNav(label='Home'),\n"
        "    destinations=(to(\n"
        "        'self-instance', urls.items.by_self.by_instance,\n"
        "    ),),\n"
        ")\n",
        encoding="ascii",
    )
    target = routes / "items" / "by_self" / "by_instance"
    target.mkdir(parents=True)
    for package in (target.parent.parent, target.parent, target):
        (package / "__init__.py").write_text("", encoding="ascii")
    (target / "route.py").write_text(
        "from pyganini import route\n"
        "from starlette.responses import PlainTextResponse\n"
        "def page(request): return PlainTextResponse('item')\n"
        "Route = route(page=page)\n",
        encoding="ascii",
    )

    graph = build_route_graph(
        select_project_paths(explicit=application, start=application)
    )
    generated = url_plan(graph)[0].content
    compile(generated, "app/_pyganini/urls.py", "exec")
    assert main(["generate", "--app-root", str(application)]) == 0

    sys.path.insert(0, str(application))
    try:
        generated_module = importlib.import_module("app._pyganini.urls")
        assert (
            generated_module.urls.destinations.self_instance("left", "right").href
            == "/items/left/right"
        )
    finally:
        sys.path.remove(str(application))
        for name in tuple(sys.modules):
            if name == "app" or name.startswith("app."):
                del sys.modules[name]


def test_nav_only_graph_keeps_plain_generated_url_bytes(
    tmp_path: Path,
    make_app: Callable[..., Path],
) -> None:
    def generated_urls(application: Path, nav_source: str) -> bytes:
        route_source = (
            "from pyganini import RouteNav, route\n"
            "from starlette.responses import PlainTextResponse\n"
            "def page(request): return PlainTextResponse('root')\n"
            f"Route = route(page=page{nav_source})\n"
        )
        (application / "app" / "routes" / "route.py").write_text(
            route_source,
            encoding="ascii",
        )
        graph = build_route_graph(
            select_project_paths(explicit=application, start=application)
        )
        return url_plan(graph)[0].content

    plain = generated_urls(make_app(tmp_path / "plain"), "")
    nav_only = generated_urls(
        make_app(tmp_path / "nav-only"), ", nav=RouteNav(label='Home')"
    )

    assert nav_only == plain
    assert b"_URLTarget" not in nav_only


def test_explicit_no_navigation_mount_does_not_require_selection_evidence(
    tmp_path: Path,
    make_app: Callable[..., Path],
) -> None:
    application = make_app(tmp_path / "application")
    mounts = application / "app" / "mounts"
    source = mounts / "directory"
    source.mkdir(parents=True)
    (mounts / "__init__.py").write_text("", encoding="ascii")
    (source / "__init__.py").write_text("", encoding="ascii")
    (source / "route.py").write_text(
        "from pyganini import route_kit\n"
        "from starlette.responses import PlainTextResponse\n"
        "def page(kit, request): return PlainTextResponse('mounted')\n"
        "Route = route_kit(page=page)\n",
        encoding="ascii",
    )
    owner = application / "app" / "routes" / "owners"
    owner.mkdir(parents=True)
    (owner / "__init__.py").write_text("", encoding="ascii")
    (owner / "route.py").write_text(
        "from pyganini import RouteNav, mount_route, route_mount\n"
        "def create(request): return object()\n"
        "Route = route_mount(\n"
        "    create=create, mount='directory',\n"
        "    routes=(mount_route('/', nav=RouteNav(label='Owner')),),\n"
        ")\n",
        encoding="ascii",
    )

    assert main(["generate", "--app-root", str(application)]) == 0
    sys.path.insert(0, str(application))
    try:
        generated = importlib.import_module("app._pyganini.asgi")
        with TestClient(generated.router) as client:
            response = client.get("/owners")
        assert response.status_code == 200
        assert response.text == "mounted"
    finally:
        sys.path.remove(str(application))
        for name in tuple(sys.modules):
            if name == "app" or name.startswith("app."):
                del sys.modules[name]


@pytest.mark.parametrize("drift", ["nav", "destinations"])
def test_generated_no_navigation_mount_rejects_stale_owner_navigation_or_destinations(
    tmp_path: Path,
    make_app: Callable[..., Path],
    drift: str,
) -> None:
    application = make_app(tmp_path / "application")
    mounts = application / "app" / "mounts"
    source = mounts / "directory"
    source.mkdir(parents=True)
    (mounts / "__init__.py").write_text("", encoding="ascii")
    (source / "__init__.py").write_text("", encoding="ascii")
    (source / "route.py").write_text(
        "from pyganini import route_kit\n"
        "from starlette.responses import PlainTextResponse\n"
        "def page(kit, request): return PlainTextResponse('mounted')\n"
        "Route = route_kit(page=page)\n",
        encoding="ascii",
    )
    owner = application / "app" / "routes" / "owners"
    owner.mkdir(parents=True)
    (owner / "__init__.py").write_text("", encoding="ascii")
    owner_route = owner / "route.py"
    owner_route.write_text(
        "from pyganini import mount_route, route_mount\n"
        "def create(request): return object()\n"
        "Route = route_mount(\n"
        "    create=create, mount='directory', routes=(mount_route('/'),)\n"
        ")\n",
        encoding="ascii",
    )

    assert main(["generate", "--app-root", str(application)]) == 0
    generated_directory = application / "app" / "_pyganini"
    generated_bytes = {
        path.name: path.read_bytes()
        for path in generated_directory.iterdir()
        if path.is_file()
    }
    if drift == "nav":
        owner_source = (
            "from pyganini import RouteNav, mount_route, route_mount\n"
            "def create(request): return object()\n"
            "Route = route_mount(\n"
            "    create=create, mount='directory',\n"
            "    routes=(mount_route('/', nav=RouteNav(label='Drifted')),),\n"
            ")\n"
        )
    else:
        owner_source = (
            "from pyganini import mount_route, route_mount, to\n"
            "class Target:\n"
            "    route_pattern = '/owners'\n"
            "target = Target()\n"
            "def create(request): return object()\n"
            "Route = route_mount(\n"
            "    create=create, mount='directory',\n"
            "    routes=(mount_route(\n"
            "        '/', destinations=(to('owners', target),)\n"
            "    ),),\n"
            ")\n"
        )
    owner_route.write_text(owner_source, encoding="ascii")

    sys.path.insert(0, str(application))
    try:
        with pytest.raises(DispatchError) as captured:
            importlib.import_module("app._pyganini.asgi")
        assert captured.value.code == "PYGANINI012"
        if drift == "destinations":
            assert (
                "runtime mounted selections disagree with generated evidence"
                in captured.value.message
            )
            assert (
                "actual selections: (('/', None, (('owners', '/owners', None),)),)"
                in captured.value.details
            )
            assert "expected selections: (('/', None, ()),)" in captured.value.details
        assert {
            path.name: path.read_bytes()
            for path in generated_directory.iterdir()
            if path.is_file()
        } == generated_bytes
    finally:
        sys.path.remove(str(application))
        for name in tuple(sys.modules):
            if name == "app" or name.startswith("app."):
                del sys.modules[name]


def test_navigation_facts_follow_the_endpoint_method_owner(
    tmp_path: Path,
    make_app: Callable[..., Path],
) -> None:
    application = make_app(tmp_path / "application")
    routes = application / "app" / "routes"
    (routes / "route.py").write_text(
        "from app._pyganini.urls import urls\n"
        "from pyganini import RouteNav, action, nav, route, to\n"
        "def root_page(request): return PlainTextResponse('root')\n"
        "from starlette.responses import PlainTextResponse\n"
        "def post(request): return PlainTextResponse(\n"
        "    f'{nav(request).trail_key()}|{nav(request).navigation()}'\n"
        ")\n"
        "Route = route(\n"
        "    page=root_page,\n"
        "    nav=RouteNav(label='Root'),\n"
        "    destinations=(to('root-workflow', urls.root, trail_key='from-root'),),\n"
        "    actions=(action('POST', '/same', post),),\n"
        ")\n",
        encoding="ascii",
    )
    child = routes / "same"
    child.mkdir()
    (child / "__init__.py").write_text("", encoding="ascii")
    (child / "route.py").write_text(
        "from pyganini import RouteNav, nav, route\n"
        "from starlette.responses import PlainTextResponse\n"
        "def page(request): return PlainTextResponse(\n"
        "    f'{nav(request).trail_key()}|{nav(request).navigation()}'\n"
        ")\n"
        "Route = route(page=page, nav=RouteNav(label='Child'))\n",
        encoding="ascii",
    )

    assert main(["generate", "--app-root", str(application)]) == 0
    sys.path.insert(0, str(application))
    try:
        generated = importlib.import_module("app._pyganini.asgi")
        with TestClient(generated.router) as client:
            get_response = client.get("/same?_pyganini_nav_trail_key=from-root")
            post_response = client.post("/same?_pyganini_nav_trail_key=from-root")
            head_response = client.head("/same")
        assert get_response.status_code == 200
        assert get_response.text.startswith("None|")
        assert "Root" in get_response.text
        assert "Child" in get_response.text
        assert post_response.status_code == 200
        assert post_response.text.startswith("from-root|")
        assert "Root" in post_response.text
        assert "Child" not in post_response.text
        assert head_response.status_code == 200
    finally:
        sys.path.remove(str(application))
        for name in tuple(sys.modules):
            if name == "app" or name.startswith("app."):
                del sys.modules[name]


def test_pages_fragments_actions_and_head_share_the_route_navigation(
    tmp_path: Path,
    make_app: Callable[..., Path],
) -> None:
    application = make_app(tmp_path / "application")
    users = application / "app" / "routes" / "users"
    users.mkdir(parents=True)
    (users / "__init__.py").write_text("", encoding="ascii")
    (users / "route.py").write_text(
        "from pyganini import RouteNav, action, fragment_route, nav, route\n"
        "from starlette.responses import PlainTextResponse\n"
        "def response(request):\n"
        "    return PlainTextResponse(nav(request).navigation().current.label)\n"
        "Route = route(\n"
        "    page=response,\n"
        "    fragments=(fragment_route('/table', response),),\n"
        "    actions=(action('POST', '/save', response),),\n"
        "    nav=RouteNav(label='Users'),\n"
        ")\n",
        encoding="ascii",
    )

    assert main(["generate", "--app-root", str(application)]) == 0
    sys.path.insert(0, str(application))
    try:
        generated = importlib.import_module("app._pyganini.asgi")
        with TestClient(generated.router) as client:
            responses = (
                client.get("/users"),
                client.get("/users/table"),
                client.post("/users/save"),
                client.head("/users"),
            )
        assert [response.status_code for response in responses] == [200] * 4
        assert [response.text for response in responses[:3]] == ["Users"] * 3
        assert responses[3].text == ""
    finally:
        sys.path.remove(str(application))
        for name in tuple(sys.modules):
            if name == "app" or name.startswith("app."):
                del sys.modules[name]


def test_mounted_navigation_rebases_two_owner_selection_subtrees_and_excludes_children(
    tmp_path: Path,
    make_app: Callable[..., Path],
) -> None:
    application = make_app(tmp_path / "application")
    mounts = application / "app" / "mounts"
    source = mounts / "directory"
    source.mkdir(parents=True)
    (mounts / "__init__.py").write_text("", encoding="ascii")
    (source / "__init__.py").write_text("", encoding="ascii")
    (source / "route.py").write_text(
        "from pyganini import RouteNav, nav, route_kit\n"
        "from starlette.responses import PlainTextResponse\n"
        "def page(kit, request): "
        "return PlainTextResponse(repr(nav(request).navigation()))\n"
        "Route = route_kit(page=page, nav=RouteNav(label='Source'))\n",
        encoding="ascii",
    )
    details = source / "details"
    details.mkdir()
    (details / "__init__.py").write_text("", encoding="ascii")
    (details / "route.py").write_text(
        "from pyganini import RouteNav, route_kit\n"
        "def page(kit, request): return object()\n"
        "Route = route_kit(page=page, nav=RouteNav(label='Details'))\n",
        encoding="ascii",
    )
    routes = application / "app" / "routes"
    left = routes / "left"
    left.mkdir(parents=True)
    (left / "__init__.py").write_text("", encoding="ascii")
    (left / "route.py").write_text(
        "from app._pyganini.urls import urls\n"
        "from pyganini import RouteNav, mount_route, route_mount, to\n"
        "def create(request): return object()\n"
        "Route = route_mount(\n"
        "    create=create, mount='directory',\n"
        "    routes=(mount_route(\n"
        "        '/', nav=RouteNav(label='Left'),\n"
        "        destinations=(to('right', urls.right, trail_key='from-left'),),\n"
        "    ),),\n"
        ")\n",
        encoding="ascii",
    )
    right = routes / "right"
    right.mkdir(parents=True)
    (right / "__init__.py").write_text("", encoding="ascii")
    (right / "route.py").write_text(
        "from pyganini import RouteNav, mount_route, route_mount\n"
        "def create(request): return object()\n"
        "Route = route_mount(\n"
        "    create=create, mount='directory',\n"
        "    routes=(mount_route('/', nav=RouteNav(label='Right')),),\n"
        ")\n",
        encoding="ascii",
    )

    graph = build_route_graph(
        select_project_paths(explicit=application, start=application)
    )
    mounted = [node for node in graph.nodes if node.mount == "directory"]
    assert [node.route_path for node in mounted] == ["/left", "/right"]
    assert not any(node.route_path.endswith("/details") for node in mounted)
    assert [
        node.declaration.nav.value.label
        for node in mounted
        if node.declaration is not None and node.declaration.nav is not None
    ] == ["Left", "Right"]
    left_node = next(node for node in mounted if node.route_path == "/left")
    assert left_node.declaration is not None
    assert left_node.declaration.destinations[0].target_path == "/right"
    compile(url_plan(graph)[0].content, "app/_pyganini/urls.py", "exec")
    assert main(["generate", "--app-root", str(application)]) == 0
    sys.path.insert(0, str(application))
    try:
        generated_asgi = importlib.import_module("app._pyganini.asgi")
        generated_urls = importlib.import_module("app._pyganini.urls")
        host = Starlette(routes=[Mount("/directory", app=generated_asgi.router)])
        with TestClient(host) as client:
            left_response = client.get("/directory/left")
            right_response = client.get("/directory/right")
            excluded_response = client.get("/directory/left/details")
        assert left_response.status_code == 200
        assert "href='/directory/left'" in left_response.text
        assert "label='Left'" in left_response.text
        assert right_response.status_code == 200
        assert "href='/directory/right'" in right_response.text
        assert "label='Right'" in right_response.text
        assert excluded_response.status_code == 404
        bound_urls = generated_urls.urls.with_base_path("/directory")
        assert bound_urls.left.destinations.right.href == (
            "/directory/right?_pyganini_nav_trail_key=from-left"
        )
        assert bound_urls.right.trail_keys.from_left == "from-left"
    finally:
        sys.path.remove(str(application))
        for name in tuple(sys.modules):
            if name == "app" or name.startswith("app."):
                del sys.modules[name]


@pytest.mark.parametrize(
    ("destination_name", "trail_key", "message"),
    (("class", None, "destination"), ("report", "class", "trail")),
)
def test_navigation_generation_rejects_python_keyword_members(
    tmp_path: Path,
    make_app: Callable[..., Path],
    destination_name: str,
    trail_key: str | None,
    message: str,
) -> None:
    application = make_app(tmp_path / "application")
    routes = application / "app" / "routes"
    trail_argument = "" if trail_key is None else f", trail_key={trail_key!r}"
    (routes / "route.py").write_text(
        "from app._pyganini.urls import urls\n"
        "from pyganini import RouteNav, route, to\n"
        "def page(request): return object()\n"
        "Route = route(page=page, nav=RouteNav(label='Home'), "
        f"destinations=(to({destination_name!r}, urls.root"
        f"{trail_argument}),))\n",
        encoding="ascii",
    )

    graph = build_route_graph(
        select_project_paths(explicit=application, start=application)
    )
    with pytest.raises(GenerationError, match=message):
        url_plan(graph)


def test_generated_dispatch_prepares_request_navigation_before_handler() -> None:
    seen: dict[str, object] = {}

    def handler(request: Request) -> Response:
        request_navigation = nav(request)
        request_navigation.resolve_href("home", "Custom home", "/custom-home")
        request_navigation.resolve_href("report", "Report", "/not-the-current-route")
        navigation = request_navigation.navigation()
        seen["navigation"] = navigation
        seen["custom"] = request_navigation.navigation_with_trail(
            (nav_step("Home", "/"), current_nav_step("Custom"))
        )
        return Response("ok")

    evidence: dict[str, _Evidence] = {
        "GET": (
            "page",
            "/reports/{report_id}",
            tuple(["GET", "HEAD"]),
            "app/routes/reports/route.py",
            4,
            20,
            __name__,
            "handler",
            "handler",
            "app/routes/reports/route.py",
            None,
            None,
            4,
            20,
            "/reports/{report_id}",
        )
    }
    endpoint = build_endpoint(
        handlers={"GET": handler},
        evidence=evidence,
        parameters=("report_id",),
        rendering=cast(Any, _empty_rendering(evidence)),
        embedded_expectations=cast(Any, _empty_embedded(evidence)),
        navigation=(
            (None, "home", "/", False),
            (None, "report", "/reports/{report_id}", True),
        ),
    )
    request = Request(
        {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/reports/r 1",
            "raw_path": b"/reports/r 1",
            "query_string": b"filter=active&filter=recent",
            "root_path": "",
            "headers": [],
            "client": ("127.0.0.1", 1),
            "server": ("testserver", 80),
            "state": {},
            "path_params": {"report_id": "r 1"},
        }
    )

    async def invoke() -> None:
        await endpoint(request)

    asyncio.run(invoke())
    navigation = cast(Navigation, seen["navigation"])
    assert navigation.trail == (
        nav_step("Custom home", "/custom-home"),
        current_nav_step("Report"),
    )
    assert navigation.current.href == "/reports/r%201"
    assert navigation.current.label == "Report"
    assert cast(Navigation, seen["custom"]).trail == (
        nav_step("Home", "/"),
        current_nav_step("Custom"),
    )


def test_navigation_resolutions_use_private_mapping_over_frozen_steps() -> None:
    seen: dict[str, object] = {}

    def handler(request: Request) -> Response:
        request_navigation = nav(request)
        request_navigation.resolve_href("report", "Report", "/override")
        seen["state"] = request.scope["_pyganini_navigation"]
        return Response("ok")

    evidence: dict[str, _Evidence] = {
        "GET": (
            "page",
            "/reports/{report_id}",
            tuple(["GET", "HEAD"]),
            "app/routes/reports/route.py",
            4,
            20,
            __name__,
            "handler",
            "handler",
            "app/routes/reports/route.py",
            None,
            None,
            4,
            20,
            "/reports/{report_id}",
        )
    }
    endpoint = build_endpoint(
        handlers={"GET": handler},
        evidence=evidence,
        parameters=("report_id",),
        rendering=cast(Any, _empty_rendering(evidence)),
        embedded_expectations=cast(Any, _empty_embedded(evidence)),
        navigation=((None, "report", "/reports/{report_id}", True),),
    )
    request = Request(
        {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/reports/r 1",
            "raw_path": b"/reports/r 1",
            "query_string": b"",
            "root_path": "",
            "headers": [],
            "client": ("127.0.0.1", 1),
            "server": ("testserver", 80),
            "state": {},
            "path_params": {"report_id": "r 1"},
        }
    )

    async def invoke() -> None:
        await endpoint(request)

    asyncio.run(invoke())
    state = cast(_NavigationState, seen["state"])
    steps = state.steps
    resolutions = state.resolutions
    assert not hasattr(steps[0], "resolution")
    assert steps[0].href == "/reports/r%201"
    assert resolutions["report"].href == "/override"
    with pytest.raises(FrozenInstanceError):
        steps[0].href = "/mutated"  # type: ignore[misc]


def test_navigation_back_and_return_query_validation() -> None:
    seen: list[Navigation] = []

    def handler(request: Request) -> Response:
        request_navigation = nav(request)
        request_navigation.resolve("report", "Report")
        seen.append(request_navigation.navigation())
        return Response("ok")

    evidence: dict[str, _Evidence] = {
        "GET": (
            "page",
            "/reports/{report_id}",
            tuple(["GET", "HEAD"]),
            "app/routes/reports/route.py",
            4,
            20,
            __name__,
            "handler",
            "handler",
            "app/routes/reports/route.py",
            None,
            None,
            4,
            20,
            "/reports/{report_id}",
        )
    }
    endpoint = build_endpoint(
        handlers={"GET": handler},
        evidence=evidence,
        parameters=("report_id",),
        rendering=cast(Any, _empty_rendering(evidence)),
        embedded_expectations=cast(Any, _empty_embedded(evidence)),
        navigation=(
            ("Home", None, "/", False),
            (None, "report", "/reports/{report_id}", True),
        ),
        trail_keys=("from-home",),
    )

    def request(query: bytes) -> Request:
        return Request(
            {
                "type": "http",
                "asgi": {"version": "3.0"},
                "http_version": "1.1",
                "method": "GET",
                "scheme": "http",
                "path": "/reports/one",
                "raw_path": b"/reports/one",
                "query_string": query,
                "root_path": "",
                "headers": [],
                "client": ("127.0.0.1", 1),
                "server": ("testserver", 80),
                "state": {},
                "path_params": {"report_id": "one"},
            }
        )

    async def invoke(selected_request: Request) -> None:
        await endpoint(selected_request)

    first_request = request(
        b"_pyganini_nav_trail_key=from-home&"
        b"_pyganini_return_to=%2Freports%2Fsource%3Fz%3D2%26a%3D1%26a%3D0"
    )
    asyncio.run(invoke(first_request))
    assert seen[-1].back == NavigationBack("/reports/source?a=1&a=0&z=2", "Home", True)
    assert "_pyganini_navigation_return_to" not in first_request.scope
    assert "_pyganini_navigation" in first_request.scope

    asyncio.run(
        invoke(
            request(
                b"_pyganini_nav_trail_key=from-home&"
                b"_pyganini_return_to=https%3A%2F%2Fevil.example"
            )
        )
    )
    assert seen[-1].back == NavigationBack("/", "Home", True)

    asyncio.run(
        invoke(
            request(
                b"_pyganini_nav_trail_key=from-home&"
                b"_pyganini_return_to=%252F%252Fevil.example"
            )
        )
    )
    assert seen[-1].back == NavigationBack("/", "Home", True)

    asyncio.run(
        invoke(
            request(
                b"_pyganini_nav_trail_key=from-home&_pyganini_return_to=%2F%5Cevil.example"
            )
        )
    )
    assert seen[-1].back == NavigationBack("/", "Home", True)

    asyncio.run(
        invoke(
            request(
                b"_pyganini_nav_trail_key=from-home&"
                b"_pyganini_return_to=%2Ffirst&_pyganini_return_to=%2Fsecond"
            )
        )
    )
    assert seen[-1].back == NavigationBack("/", "Home", True)


@pytest.mark.parametrize(
    ("value", "expected"),
    (
        ("/source?z=2&a=1&a=0", "/source?a=1&a=0&z=2"),
        ("/source?_pyganini_return_to=%2Fnested", "/source"),
        ("//evil.example", None),
        ("https://evil.example", None),
        ("/source#fragment", None),
        ("/\\evil.example", None),
        ("/source/%ZZ", None),
        ("/source/%2", None),
        ("/source/%FF", None),
        ("/source?value=%FF", None),
        ("/%2F%2Fevil.example", None),
        ("/\x00evil", None),
        ("/\x7fevil", None),
        ("/" + "a" * 2048, None),
    ),
)
def test_return_href_safety_matrix(value: str, expected: str | None) -> None:
    assert _safe_return_to(value) == expected


def test_navigation_state_is_request_isolated() -> None:
    seen: list[Navigation] = []

    def handler(request: Request) -> Response:
        request_navigation = nav(request)
        request_navigation.resolve("report", request.path_params["report_id"])
        seen.append(request_navigation.navigation())
        return Response("ok")

    evidence: dict[str, _Evidence] = {
        "GET": (
            "page",
            "/reports/{report_id}",
            tuple(["GET", "HEAD"]),
            "app/routes/reports/route.py",
            4,
            20,
            __name__,
            "handler",
            "handler",
            "app/routes/reports/route.py",
            None,
            None,
            4,
            20,
            "/reports/{report_id}",
        )
    }
    endpoint = build_endpoint(
        handlers={"GET": handler},
        evidence=evidence,
        parameters=("report_id",),
        rendering=cast(Any, _empty_rendering(evidence)),
        embedded_expectations=cast(Any, _empty_embedded(evidence)),
        navigation=(
            ("Reports", None, "/", False),
            (None, "report", "/reports/{report_id}", True),
        ),
    )

    def make_request(report_id: str) -> Request:
        return Request(
            {
                "type": "http",
                "asgi": {"version": "3.0"},
                "http_version": "1.1",
                "method": "GET",
                "scheme": "http",
                "path": f"/reports/{report_id}",
                "raw_path": f"/reports/{report_id}".encode(),
                "query_string": b"",
                "root_path": "",
                "headers": [],
                "client": ("127.0.0.1", 1),
                "server": ("testserver", 80),
                "state": {},
                "path_params": {"report_id": report_id},
            }
        )

    first = make_request("one")
    second = make_request("two")

    async def invoke(selected_request: Request) -> None:
        await endpoint(selected_request)

    asyncio.run(invoke(first))
    asyncio.run(invoke(second))

    assert seen[0].current.label == "one"
    assert seen[1].current.label == "two"
    assert nav(first).navigation().current.label == "one"
    assert nav(second).navigation().current.label == "two"
    assert (
        first.scope["_pyganini_navigation"] is not second.scope["_pyganini_navigation"]
    )


def test_navigation_state_is_prepared_before_handler_exception_and_cancellation() -> (
    None
):
    evidence: dict[str, _Evidence] = {
        "GET": (
            "page",
            "/reports",
            tuple(["GET", "HEAD"]),
            "app/routes/reports/route.py",
            4,
            20,
            __name__,
            "handler",
            "handler",
            "app/routes/reports/route.py",
            None,
            None,
            4,
            20,
            "/reports",
        )
    }

    def request() -> Request:
        return Request(
            {
                "type": "http",
                "asgi": {"version": "3.0"},
                "http_version": "1.1",
                "method": "GET",
                "scheme": "http",
                "path": "/reports",
                "raw_path": b"/reports",
                "query_string": b"",
                "root_path": "",
                "headers": [],
                "client": ("127.0.0.1", 1),
                "server": ("testserver", 80),
                "state": {},
                "path_params": {},
            }
        )

    def failing_handler(selected_request: Request) -> Response:
        assert nav(selected_request).navigation().trail == (nav_step("Reports", "/"),)
        raise RuntimeError("handler failure")

    failing_endpoint = build_endpoint(
        handlers={"GET": failing_handler},
        evidence=evidence,
        parameters=(),
        rendering=cast(Any, _empty_rendering(evidence)),
        embedded_expectations=cast(Any, _empty_embedded(evidence)),
        navigation=(("Reports", None, "/", False),),
    )
    failed_request = request()

    async def invoke_failing() -> None:
        await failing_endpoint(failed_request)

    with pytest.raises(RuntimeError, match="handler failure"):
        asyncio.run(invoke_failing())
    assert "_pyganini_navigation" in failed_request.scope

    async def cancelled_handler(selected_request: Request) -> Response:
        assert nav(selected_request).navigation().trail == (nav_step("Reports", "/"),)
        raise asyncio.CancelledError()

    cancelled_endpoint = build_endpoint(
        handlers={"GET": cancelled_handler},
        evidence=evidence,
        parameters=(),
        rendering=cast(Any, _empty_rendering(evidence)),
        embedded_expectations=cast(Any, _empty_embedded(evidence)),
        navigation=(("Reports", None, "/", False),),
    )
    cancelled_request = request()

    async def invoke_cancelled() -> None:
        await cancelled_endpoint(cancelled_request)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(invoke_cancelled())
    assert "_pyganini_navigation" in cancelled_request.scope


def test_generated_asgi_navigation_resolves_labels_and_accepts_trail_keys(
    tmp_path: Path,
    make_app: Callable[..., Path],
) -> None:
    application = make_app(tmp_path / "application")
    routes = application / "app" / "routes"
    (routes / "route.py").write_text(
        "from app._pyganini.urls import urls\n"
        "from pyganini import RouteNav, nav, route, to\n"
        "from starlette.responses import PlainTextResponse\n"
        "def page(request):\n"
        "    value = nav(request).navigation()\n"
        "    return PlainTextResponse(repr(value))\n"
        "Route = route(\n"
        "    page=page, nav=RouteNav(label='Home'),\n"
        "    destinations=(to('report-detail', urls.reports.by_report_id,\n"
        "        trail_key='from-home'),),\n"
        ")\n",
        encoding="ascii",
    )
    report = routes / "reports" / "by_report_id"
    report.mkdir(parents=True)
    (report.parent / "__init__.py").write_text("", encoding="ascii")
    (report / "__init__.py").write_text("", encoding="ascii")
    (report / "route.py").write_text(
        "from pyganini import RouteNav, nav, route\n"
        "from starlette.responses import PlainTextResponse\n"
        "def page(request):\n"
        "    request_navigation = nav(request)\n"
        "    request_navigation.resolve('report', 'Report')\n"
        "    return PlainTextResponse(repr(request_navigation.navigation()))\n"
        "Route = route(page=page, nav=RouteNav(key='report'))\n",
        encoding="ascii",
    )
    assert main(["generate", "--app-root", str(application)]) == 0
    sys.path.insert(0, str(application))
    try:
        generated = importlib.import_module("app._pyganini.asgi")
        with TestClient(generated.router) as client:
            response = client.get(
                "/reports/one?_pyganini_nav_trail_key=from-home&filter=active"
            )
        assert response.status_code == 200
        assert "label='Home'" in response.text
        assert "label='Report'" in response.text
        assert "href='/reports/one'" in response.text
    finally:
        sys.path.remove(str(application))
        for name in tuple(sys.modules):
            if name == "app" or name.startswith("app."):
                del sys.modules[name]


def test_starlette_and_fastapi_navigation_root_path_matrix(
    tmp_path: Path,
    make_app: Callable[..., Path],
) -> None:
    application = make_app(tmp_path / "application")
    routes = application / "app" / "routes"
    (routes / "route.py").write_text(
        "from app._pyganini.urls import urls\n"
        "from pyganini import RouteNav, route, to\n"
        "from starlette.responses import PlainTextResponse\n"
        "def page(request): return PlainTextResponse('root')\n"
        "Route = route(page=page, nav=RouteNav(label='Home'), "
        "destinations=(to('report-detail', urls.users.by_report_id, "
        "trail_key='from-home'),))\n",
        encoding="ascii",
    )
    users = routes / "users"
    users.mkdir()
    (users / "__init__.py").write_text("", encoding="ascii")
    (users / "route.py").write_text(
        "from pyganini import RouteNav, route\n"
        "from starlette.responses import PlainTextResponse\n"
        "def page(request): return PlainTextResponse('users')\n"
        "Route = route(page=page, nav=RouteNav(label='Users'))\n",
        encoding="ascii",
    )
    report = users / "by_report_id"
    report.mkdir()
    (report / "__init__.py").write_text("", encoding="ascii")
    (report / "route.py").write_text(
        "from app._pyganini.urls import urls\n"
        "from pyganini import RouteNav, nav, route\n"
        "from starlette.responses import JSONResponse\n"
        "def page(request):\n"
        "    request_navigation = nav(request)\n"
        "    request_navigation.resolve('report', 'Report')\n"
        "    navigation = request_navigation.navigation()\n"
        "    app_urls = urls.with_base_path(request.scope.get('root_path', ''))\n"
        "    destination = app_urls.destinations.report_detail("
        "request.path_params['report_id'])\n"
        "    return JSONResponse({\n"
        "        'root_path': request.scope['root_path'],\n"
        "        'path': request.scope['path'],\n"
        "        'trail': [[step.label, step.href, step.current] "
        "for step in navigation.trail],\n"
        "        'current': navigation.current.href,\n"
        "        'back': navigation.back.href,\n"
        "        'destination': destination.href,\n"
        "        'returning': destination.navigation_href(navigation),\n"
        "    })\n"
        "Route = route(page=page, nav=RouteNav(key='report'))\n",
        encoding="ascii",
    )
    assert main(["generate", "--app-root", str(application)]) == 0
    sys.path.insert(0, str(application))
    try:
        generated = importlib.import_module("app._pyganini.asgi")
        cases = (
            ("", "", ""),
            ("", "/directory", "/directory"),
            ("/proxy", "", "/proxy"),
            ("/proxy", "/directory", "/proxy/directory"),
        )
        for host_kind in ("starlette", "fastapi"):
            for proxy_path, mount_path, expected_root_path in cases:
                if host_kind == "starlette":
                    host = (
                        generated.router
                        if not mount_path
                        else Starlette(routes=[Mount(mount_path, app=generated.router)])
                    )
                else:
                    host = FastAPI()
                    host.mount(mount_path or "/", generated.router)
                base_url = "http://testserver" + proxy_path
                request_path = mount_path + "/users/r%201"
                with TestClient(
                    host,
                    base_url=base_url,
                    root_path=proxy_path,
                ) as client:
                    response = client.get(request_path + "?filter=active")
                    assert response.status_code == 200
                    value = response.json()
                    prefix = expected_root_path
                    assert value["root_path"] == prefix
                    assert value["path"] == prefix + "/users/r 1"
                    assert value["trail"] == [
                        ["Home", prefix + "/", False],
                        ["Users", prefix + "/users", False],
                        ["Report", "", True],
                    ]
                    assert value["current"] == prefix + "/users/r%201"
                    assert value["back"] == prefix + "/users"
                    destination = (
                        prefix + "/users/r%201?_pyganini_nav_trail_key=from-home"
                    )
                    assert value["destination"] == destination
                    assert value["returning"] == (
                        destination
                        + "&_pyganini_return_to="
                        + quote(
                            prefix + "/users/r 1?filter=active",
                            safe="",
                        )
                    )

                    return_query = quote(
                        prefix + "/users?status=active",
                        safe="",
                    )
                    returned = client.get(
                        request_path
                        + "?_pyganini_nav_trail_key=from-home&_pyganini_return_to="
                        + return_query
                    )
                    assert returned.status_code == 200
                    assert returned.json()["back"] == (prefix + "/users?status=active")
    finally:
        sys.path.remove(str(application))
        for name in tuple(sys.modules):
            if name == "app" or name.startswith("app."):
                del sys.modules[name]


def test_proxy_header_without_root_path_does_not_prefix_navigation() -> None:
    request = _navigation_request()
    request.scope["headers"] = [(b"x-forwarded-prefix", b"/proxy")]
    _prepare_navigation(
        request,
        facts=(("Home", None, "/", False),),
    )

    assert nav(request).navigation().trail == (nav_step("Home", "/"),)
    assert request.scope["root_path"] == ""
    assert request.scope["path"] == "/reports/r 1"


@pytest.mark.parametrize("creator_async", [False, True])
def test_mounted_creator_navigation_resolution_is_visible_to_handler(
    tmp_path: Path,
    make_app: Callable[..., Path],
    creator_async: bool,
) -> None:
    application = make_app(tmp_path / ("async" if creator_async else "sync"))
    mounts = application / "app" / "mounts"
    source = mounts / "directory"
    source.mkdir(parents=True)
    (mounts / "__init__.py").write_text("", encoding="ascii")
    (source / "__init__.py").write_text("", encoding="ascii")
    (source / "route.py").write_text(
        "from pyganini import RouteNav, nav, route_kit\n"
        "from starlette.responses import PlainTextResponse\n"
        "def page(kit, request):\n"
        "    current = nav(request).navigation().current.label\n"
        "    return PlainTextResponse(f'{kit}|{current}')\n"
        "Route = route_kit(page=page, nav=RouteNav(key='current'))\n",
        encoding="ascii",
    )
    owner = application / "app" / "routes" / "owners"
    owner.mkdir(parents=True)
    (owner / "__init__.py").write_text("", encoding="ascii")
    creator_prefix = "async " if creator_async else ""
    (owner / "route.py").write_text(
        "from pyganini import nav, mount_route, route_mount\n"
        f"{creator_prefix}def create(request):\n"
        "    nav(request).resolve('current', 'Created by creator')\n"
        "    return 'kit'\n"
        "Route = route_mount(\n"
        "    create=create, mount='directory', routes=(mount_route('/'),)\n"
        ")\n",
        encoding="ascii",
    )

    assert main(["generate", "--app-root", str(application)]) == 0
    sys.path.insert(0, str(application))
    try:
        generated = importlib.import_module("app._pyganini.asgi")
        with TestClient(generated.router) as client:
            response = client.get("/owners")
        assert response.status_code == 200
        assert response.text == "kit|Created by creator"
    finally:
        sys.path.remove(str(application))
        for name in tuple(sys.modules):
            if name == "app" or name.startswith("app."):
                del sys.modules[name]


def test_mounted_navigation_uses_source_defaults_and_live_selection_overrides(
    tmp_path: Path,
    make_app: Callable[..., Path],
) -> None:
    application = make_app(tmp_path / "application")
    mounts = application / "app" / "mounts"
    source = mounts / "directory"
    source.mkdir(parents=True)
    (mounts / "__init__.py").write_text("", encoding="ascii")
    (source / "__init__.py").write_text("", encoding="ascii")
    (source / "route.py").write_text(
        "from pyganini import RouteNav, route_kit\n"
        "def page(kit, request): return object()\n"
        "Route = route_kit(page=page, nav=RouteNav(label='Source'))\n",
        encoding="ascii",
    )
    owner_routes = application / "app" / "routes" / "owners"
    owner_routes.mkdir(parents=True)
    (owner_routes / "__init__.py").write_text("", encoding="ascii")
    (owner_routes / "route.py").write_text(
        "from pyganini import RouteNav, mount_route, route_mount\n"
        "def create(request): return object()\n"
        "Route = route_mount(\n"
        "    create=create, mount='directory',\n"
        "    routes=(mount_route('/', nav=RouteNav(label='Owner')),),\n"
        ")\n",
        encoding="ascii",
    )
    graph = build_route_graph(
        select_project_paths(explicit=application, start=application)
    )
    mounted = next(
        node for node in graph.nodes if node.mount == "directory" and node.declaration
    )
    assert mounted.declaration is not None
    assert mounted.declaration.nav is not None
    assert mounted.declaration.nav.value.label == "Owner"
    compile(url_plan(graph)[0].content, "app/_pyganini/urls.py", "exec")


def test_navigation_generation_rejects_reserved_destination_member(
    tmp_path: Path,
    make_app: Callable[..., Path],
) -> None:
    application = make_app(tmp_path / "application")
    routes = application / "app" / "routes"
    (routes / "route.py").write_text(
        "from app._pyganini.urls import urls\n"
        "from pyganini import RouteNav, route, to\n"
        "def page(request): return object()\n"
        "Route = route(page=page, nav=RouteNav(label='Home'),\n"
        "    destinations=(to('report', urls.destinations),))\n",
        encoding="ascii",
    )
    destinations = routes / "destinations"
    destinations.mkdir()
    (destinations / "__init__.py").write_text("", encoding="ascii")
    (destinations / "route.py").write_text(
        "from pyganini import route\n"
        "def page(request): return object()\n"
        "Route = route(page=page)\n",
        encoding="ascii",
    )

    graph = build_route_graph(
        select_project_paths(explicit=application, start=application)
    )
    with pytest.raises(GenerationError, match="destinations"):
        url_plan(graph)
