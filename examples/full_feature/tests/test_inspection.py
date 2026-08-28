import json
import subprocess
import sys
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[1]


def _run(*arguments: str) -> subprocess.CompletedProcess[str]:
    command = Path(sys.executable).with_name("pyganini")
    return subprocess.run(
        [str(command), *arguments],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )


def _rows(*arguments: str) -> list[dict[str, Any]]:
    payload = _inventory(*arguments)
    return cast(list[dict[str, Any]], payload["routes"])


def _inventory(*arguments: str) -> dict[str, Any]:
    result = _run("routes", "list", "--json", *arguments)
    payload = cast(dict[str, Any], json.loads(result.stdout))
    assert payload["schema"] == "pyganini.routes.v1"
    assert list(payload) == ["schema", "error_render", "routes"]
    return payload


def _references(*arguments: str) -> list[dict[str, Any]]:
    result = _run("routes", "refs", "--json", *arguments)
    payload = json.loads(result.stdout)
    assert payload["schema"] == "pyganini.refs.v1"
    return cast(list[dict[str, Any]], payload["references"])


def _render_units(*arguments: str) -> list[dict[str, Any]]:
    result = _run("routes", "render-units", "--json", *arguments)
    payload = json.loads(result.stdout)
    assert payload["schema"] == "pyganini.render_units.v1"
    return cast(list[dict[str, Any]], payload["render_units"])


def _failed(*arguments: str) -> subprocess.CompletedProcess[str]:
    command = Path(sys.executable).with_name("pyganini")
    return subprocess.run(
        [str(command), *arguments],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )


def test_installed_route_inventory_reports_both_mount_owners() -> None:
    text = _run("routes", "list")
    assert "KIND" in text.stdout
    assert "urls.users.by_id(id).path" in text.stdout
    assert text.stderr == ""
    assert _run("routes", "list").stdout == text.stdout

    inventory = _inventory()
    rows = cast(list[dict[str, Any]], inventory["routes"])
    assert (
        _run("routes", "list", "--json").stdout
        == _run("routes", "list", "--json").stdout
    )
    mounted = [row for row in rows if row["mount"] == "contact_directory"]
    assert {
        (row["path"], row["kind"], row["source_path"], row["owner"]["path"])
        for row in mounted
        if row["kind"] != "layout"
    } == {
        ("/users", "page", "/", "app/routes/users/route.py"),
        ("/users/table", "fragment", "/", "app/routes/users/route.py"),
        ("/users/create", "action", "/create", "app/routes/users/route.py"),
        ("/users/{id}", "page", "/{id}", "app/routes/users/route.py"),
        (
            "/settings/users",
            "page",
            "/",
            "app/routes/settings/users/route.py",
        ),
        (
            "/settings/users/table",
            "fragment",
            "/",
            "app/routes/settings/users/route.py",
        ),
    }
    assert {
        (row["path"], row["source"]["path"], row["source_path"])
        for row in mounted
        if row["kind"] == "layout"
    } == {
        (
            "/users",
            "app/mounts/contact_directory/layout.py",
            "/",
        ),
        (
            "/settings/users",
            "app/mounts/contact_directory/layout.py",
            "/",
        ),
    }
    assert {
        row["source"]["path"]
        for row in rows
        if row["kind"] == "layout" and row["mount"] is None
    } >= {
        "app/routes/layout.py",
        "app/routes/users/layout.py",
        "app/routes/settings/users/layout.py",
    }
    assert all(
        row["path"] not in {"/settings/users/create", "/settings/users/{id}"}
        for row in rows
    )

    implementations = {
        (row["path"], row["kind"]): row["declaration"]["implementation"]
        for row in rows
        if row["kind"] in {"page", "fragment", "action"}
    }
    assert implementations[("/", "page")]["declaration"] == {
        "path": "app/routes/route.py",
        "line": 6,
        "column": 10,
    }
    assert implementations[("/users/table", "fragment")]["declaration"] == {
        "path": "app/mounts/contact_directory/route.py",
        "line": 8,
        "column": 16,
    }
    assert implementations[("/users/create", "action")]["declaration"] == {
        "path": "app/mounts/contact_directory/create/route.py",
        "line": 8,
        "column": 9,
    }

    root = next(row for row in rows if row["path"] == "/" and row["kind"] == "page")
    assert root["selection"] is None
    assert root["declaration"]["kind"] == "route"
    assert root["declaration"]["name"] == "home"
    assert root["declaration"]["title"] == "Pyganini Full Feature"
    assert {
        label["key"]: label["value"] for label in root["declaration"]["labels"]
    } == {"app.area": "home", "app.visibility": "public"}

    mounted_roots = [
        row for row in mounted if row["kind"] == "page" and row["source_path"] == "/"
    ]
    assert {row["owner"]["path"] for row in mounted_roots} == {
        "app/routes/users/route.py",
        "app/routes/settings/users/route.py",
    }
    assert all(
        row["declaration"]["name"] == "contact-directory" for row in mounted_roots
    )
    assert all(
        row["declaration"]["title"] == "Contact Directory" for row in mounted_roots
    )
    assert all(
        {label["key"]: label["value"] for label in row["declaration"]["labels"]}
        == {"app.area": "contacts", "app.source": "shared-kit"}
        for row in mounted_roots
    )

    users = next(
        row
        for row in mounted_roots
        if row["owner"]["path"] == "app/routes/users/route.py"
    )
    assert users["declaration"]["nav"]["label"] == "Contacts"
    assert users["declaration"]["destinations"][0]["target"] == "/users/{id}"
    detail = next(row for row in rows if row["path"] == "/users/{id}")
    assert detail["declaration"]["trail_keys"] == ["from-contacts"]
    assert detail["declaration"]["inbound_destinations"][0]["source_route"] == "/users"

    error_render = inventory["error_render"]
    assert error_render["page_template"]["name"] == "routes/error_page.jinja"
    assert error_render["fragment_template"]["name"] == "routes/error_fragment.jinja"
    assert [layout["template"]["name"] for layout in error_render["root_layouts"]] == [
        "routes/layout.jinja"
    ]

    filtered = _rows("--mount", "contact_directory")
    assert all(row["mount"] == "contact_directory" for row in filtered)
    assert all(
        row["selection"] == "included" for row in filtered if row["kind"] != "route"
    )
    assert {
        (row["path"], row["selection"], row["kind"], row["owner"]["path"])
        for row in filtered
        if row["selection"] == "excluded"
    } == {
        (
            "/settings/users/create",
            "excluded",
            "route",
            "app/routes/settings/users/route.py",
        ),
        (
            "/settings/users/{id}",
            "excluded",
            "route",
            "app/routes/settings/users/route.py",
        ),
    }
    assert all(
        row["declaration"]["implementation"] is None
        for row in filtered
        if row["selection"] == "excluded"
    )
    assert any(row["helper"] == "urls.users.by_id(id).path" for row in filtered)

    module = subprocess.run(
        [sys.executable, "-m", "pyganini", "routes", "list", "--json"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert module.returncode == 0
    assert module.stdout == _run("routes", "list", "--json").stdout
    assert module.stderr == ""


def test_installed_reference_inventory_scans_selected_mount_source() -> None:
    first = _run("routes", "refs")
    second = _run("routes", "refs")
    module = subprocess.run(
        [sys.executable, "-m", "pyganini", "routes", "refs"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert first.stderr == ""
    assert first.stdout == second.stdout
    assert module.returncode == 0
    assert module.stdout == first.stdout
    assert module.stderr == ""
    assert first.stdout.startswith("STATUS   METHOD  ROUTE  KIND  ATTRIBUTE  SOURCE")
    assert "app/mounts/contact_directory/directory.jinja:3:1" in first.stdout
    assert "{{ directory.urls.create_url }}" in first.stdout

    references = _references()
    assert len(references) == 4
    assert {
        (reference["method"], reference["attribute"], reference["value"])
        for reference in references
    } == {
        ("POST", "hx-post", "{{ directory.urls.create_url }}"),
        ("GET", "hx-get", "{{ filter_urls.all }}"),
        ("GET", "hx-get", "{{ filter_urls.active }}"),
        ("GET", "hx-get", "{{ filter_urls.inactive }}"),
    }
    assert all(reference["status"] == "dynamic" for reference in references)


def test_installed_route_layout_map_reports_chains_and_mount_owners() -> None:
    first = _run("routes", "layouts")
    second = _run("routes", "layouts")
    module = subprocess.run(
        [sys.executable, "-m", "pyganini", "routes", "layouts"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert first.stderr == ""
    assert first.stdout == second.stdout
    assert module.returncode == 0
    assert module.stdout == first.stdout
    assert module.stderr == ""
    assert first.stdout.startswith("LAYOUT MAP\n/\n")
    assert "layout /users source=app/routes/users/layout.py:1:1" in first.stdout
    assert (
        "layout /settings/users source=app/routes/settings/users/layout.py:1:1"
        in first.stdout
    )
    assert (
        "layout /users source=app/mounts/contact_directory/layout.py:1:1 "
        "owner=app/routes/users/route.py:1:1 mount=contact_directory source_path=/"
    ) in first.stdout
    assert (
        "layout /settings/users source=app/mounts/contact_directory/layout.py:1:1 "
        "owner=app/routes/settings/users/route.py:1:1 mount=contact_directory "
        "source_path=/"
    ) in first.stdout
    assert (
        "page GET,HEAD /users source=app/mounts/contact_directory/route.py:1:1 "
        "owner=app/routes/users/route.py:1:1 mount=contact_directory source_path=/ "
        "layouts=[app/routes/layout.py:1:1 > app/routes/users/layout.py:1:1 > "
        "app/mounts/contact_directory/layout.py:1:1]"
    ) in first.stdout
    assert (
        "page GET,HEAD /settings/users "
        "source=app/mounts/contact_directory/route.py:1:1 "
        "owner=app/routes/settings/users/route.py:1:1 "
        "mount=contact_directory source_path=/ "
        "layouts=[app/routes/layout.py:1:1 > "
        "app/routes/settings/users/layout.py:1:1 > "
        "app/mounts/contact_directory/layout.py:1:1]"
    ) in first.stdout
    assert "fragment GET,HEAD /users/table" in first.stdout
    assert "fragment GET,HEAD /settings/users/table" in first.stdout
    assert "layouts=[] (not wrapped)" in first.stdout
    assert "action POST /users/create" in first.stdout
    assert "page GET,HEAD /users/{id}" in first.stdout
    users_tree = first.stdout.rindex("`-- users/")
    users_output = first.stdout[users_tree:]
    assert users_output.index("create/") < users_output.index("table/")
    assert users_output.index("table/") < users_output.index("{id}/")
    assert "/settings/users/create" not in first.stdout
    assert "/settings/users/{id}" not in first.stdout
    assert "\x1b[" not in first.stdout


def test_installed_render_unit_inventory_reports_templates_and_layout_modes() -> None:
    first = _run("routes", "render-units")
    second = _run("routes", "render-units")
    module = subprocess.run(
        [sys.executable, "-m", "pyganini", "routes", "render-units"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert first.returncode == second.returncode == 0
    assert first.stdout == second.stdout
    assert module.returncode == 0
    assert module.stdout == first.stdout
    assert module.stderr == first.stderr == ""
    assert first.stdout.startswith("KIND")
    assert first.stdout.isascii()
    assert "routes/page.jinja" in first.stdout
    assert "mounts/contact_directory/page.jinja" in first.stdout
    assert "page-result" in first.stdout
    assert "none" in first.stdout
    assert "/problem" not in first.stdout
    assert "/settings/users/create" not in first.stdout
    assert "/settings/users/{id}" not in first.stdout

    units = _render_units()
    assert {
        (unit["route"], unit["kind"], unit["template"]["name"], unit["mount"])
        for unit in units
    } == {
        ("/", "page", "routes/page.jinja", None),
        ("/settings", "page", "routes/settings/page.jinja", None),
        ("/users", "page", "mounts/contact_directory/page.jinja", "contact_directory"),
        (
            "/users/table",
            "fragment",
            "mounts/contact_directory/table.jinja",
            "contact_directory",
        ),
        (
            "/users/create",
            "action",
            "mounts/contact_directory/create/directory.jinja",
            "contact_directory",
        ),
        (
            "/users/{id}",
            "page",
            "mounts/contact_directory/by_id/page.jinja",
            "contact_directory",
        ),
        (
            "/settings/users",
            "page",
            "mounts/contact_directory/page.jinja",
            "contact_directory",
        ),
        (
            "/settings/users/table",
            "fragment",
            "mounts/contact_directory/table.jinja",
            "contact_directory",
        ),
    }
    by_route = {(unit["route"], unit["kind"]): unit for unit in units}
    assert by_route[("/users/table", "fragment")]["effective_layouts"] == []
    assert by_route[("/settings/users/table", "fragment")]["layout_mode"] == "none"
    assert by_route[("/users/create", "action")]["layout_mode"] == "page-result"
    assert by_route[("/users/create", "action")]["source_path"] == "/create"
    assert [
        layout["template"]["name"]
        for layout in by_route[("/users", "page")]["effective_layouts"]
    ] == [
        "routes/layout.jinja",
        "routes/users/layout.jinja",
        "mounts/contact_directory/layout.jinja",
    ]


def test_installed_route_explain_proves_dispatch_and_mount_evidence() -> None:
    root = _run("routes", "explain", "/")
    assert root.stderr == ""
    assert "status=matched" in root.stdout
    assert "kind=page" in root.stdout
    assert "layouts=[app/routes/layout.py:1:1]" in root.stdout
    assert "DECLARATION\nkind=route" in root.stdout
    assert 'name="home"' in root.stdout
    assert 'title="Pyganini Full Feature"' in root.stdout
    assert 'labels={"app.area":"home","app.visibility":"public"}' in root.stdout
    assert "IMPLEMENTATION\nkind=page" in root.stdout
    assert "declaration=app/routes/route.py:6:10\n" in root.stdout
    assert "ERROR_RENDER\npage=routes/error_page.jinja@" in root.stdout
    assert "fragment=routes/error_fragment.jinja@" in root.stdout
    assert root.stdout == _run("routes", "explain", "/").stdout

    module = subprocess.run(
        [sys.executable, "-m", "pyganini", "routes", "explain", "/"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert module.returncode == 0
    assert module.stdout == root.stdout
    assert module.stderr == ""

    problem = _run("routes", "explain", "/problem")
    assert "route=/problem" in problem.stdout
    assert "kind=page" in problem.stdout

    dynamic = _run(
        "routes",
        "explain",
        "http://127.0.0.1:8000/users/42?view=profile#details",
    )
    assert 'url_path="/users/42"' in dynamic.stdout
    assert 'asgi_path="/users/42"' in dynamic.stdout
    assert 'params=[id="42"]' in dynamic.stdout
    assert "owner=app/routes/users/route.py:1:1" in dynamic.stdout
    assert "mount=contact_directory" in dynamic.stdout
    assert 'trail_keys=["from-contacts"]' in dynamic.stdout
    assert (
        'inbound_destinations=["/users":"contact-detail"#"from-contacts"@'
        in dynamic.stdout
    )
    assert (
        "handler_source=app/mounts/contact_directory/by_id/route.py:" in dynamic.stdout
    )
    assert "page_layouts=[routes/layout.jinja@" in dynamic.stdout
    assert (
        "layouts=[app/routes/layout.py:1:1 > app/routes/users/layout.py:1:1 > "
        "app/mounts/contact_directory/layout.py:1:1]"
    ) in dynamic.stdout

    head = _run("routes", "explain", "--method", "HEAD", "/users/42")
    assert "method=HEAD" in head.stdout
    assert "dispatch_method=GET" in head.stdout
    assert "methods=GET,HEAD" in head.stdout

    action = _run("routes", "explain", "--method", "POST", "/users/create")
    assert "kind=action" in action.stdout
    assert "methods=POST" in action.stdout
    assert "dispatch_method=POST" in action.stdout
    assert (
        "declaration=app/mounts/contact_directory/create/route.py:8:9\n"
        in action.stdout
    )
    assert "(valid Page results only)" in action.stdout

    fragment = _run("routes", "explain", "/users/table")
    assert "kind=fragment" in fragment.stdout
    assert "declaration=app/mounts/contact_directory/route.py:8:16\n" in fragment.stdout
    assert "layouts=[] (not wrapped)" in fragment.stdout

    settings = _run("routes", "explain", "/settings/users")
    assert "owner=app/routes/settings/users/route.py:1:1" in settings.stdout
    assert (
        "layouts=[app/routes/layout.py:1:1 > "
        "app/routes/settings/users/layout.py:1:1 > "
        "app/mounts/contact_directory/layout.py:1:1]"
    ) in settings.stdout
    assert "source_path=/" in settings.stdout

    for target in ("/settings/users/create", "/settings/users/42"):
        failed = _failed("routes", "explain", target)
        assert failed.returncode == 1
        assert failed.stdout == ""
        assert "status=404" in failed.stderr


def test_installed_route_explain_has_ascii_and_repeated_bytes() -> None:
    first = _run("routes", "explain", "/users/a%252Fb")
    second = _run("routes", "explain", "/users/a%252Fb")
    assert first.returncode == second.returncode == 0
    assert first.stdout == second.stdout
    assert first.stdout.isascii()
    assert 'asgi_path="/users/a%2Fb"' in first.stdout
    assert 'params=[id="a%2Fb"]' in first.stdout
