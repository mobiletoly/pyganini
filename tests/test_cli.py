# pyright: reportPrivateUsage=false

import json
import os
import stat
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import cast

import pytest

import pyganini._cli as cli_module
import pyganini._inspection as inspection_module
import pyganini._paths as paths_module
import pyganini._route_graph as route_graph_module
import pyganini._template_references as template_references_module
from pyganini._cli import main
from pyganini._dispatch import PathPriorityRoute
from pyganini._inspection import InspectionError


def _snapshot(
    root: Path,
) -> tuple[tuple[str, bytes | str | None, int, int], ...]:
    entries: list[tuple[str, bytes | str | None, int, int]] = []
    for path in (root, *sorted(root.rglob("*"))):
        path_stat = path.lstat()
        content: bytes | str | None = None
        if stat.S_ISREG(path_stat.st_mode):
            content = path.read_bytes()
        elif stat.S_ISLNK(path_stat.st_mode):
            content = os.readlink(path)
        entries.append(
            (
                path.relative_to(root).as_posix(),
                content,
                path_stat.st_mode,
                path_stat.st_mtime_ns,
            )
        )
    return tuple(entries)


def _reference_application(application: Path, template: str) -> Path:
    routes = application / "app" / "routes"
    (routes / "route.py").write_text(
        "from pyganini import route\n"
        "def page(request): return None\n"
        "Route = route(page=page, template='page.jinja')\n",
        encoding="ascii",
    )
    (routes / "page.jinja").write_text(template, encoding="ascii")
    return application


def _render_unit_application(application: Path) -> Path:
    routes = application / "app" / "routes"
    (routes / "layout.py").write_text("VALUE = 1\n", encoding="ascii")
    (routes / "layout.jinja").write_text("{{ child }}\n", encoding="ascii")
    users = routes / "users"
    users.mkdir()
    (users / "__init__.py").write_text("", encoding="ascii")
    (users / "layout.py").write_text("VALUE = 1\n", encoding="ascii")
    (users / "layout.jinja").write_text("{{ child }}\n", encoding="ascii")
    (users / "route.py").write_text(
        "from pyganini import action, fragment_route, route\n"
        "def page(request): return None\n"
        "def table(request): return None\n"
        "def create(request): return None\n"
        "def direct(request): return None\n"
        "Route = route(\n"
        "    page=page, template='page.jinja',\n"
        "    fragments=(fragment_route('/table', table, template='table.jinja'),),\n"
        "    actions=(\n"
        "        action('POST', '/create', create, template='create.jinja'),\n"
        "        action('DELETE', '/direct', direct),\n"
        "    ),\n"
        ")\n",
        encoding="ascii",
    )
    for name in ("page", "table", "create"):
        (users / f"{name}.jinja").write_text("{{ value }}\n", encoding="ascii")
    return application


def test_generate_and_check_summaries(
    tmp_path: Path,
    make_app: Callable[..., Path],
    capsys: pytest.CaptureFixture[str],
) -> None:
    application = make_app(tmp_path / "application")
    assert main(["generate", "--app-root", str(application)]) == 0
    generated = capsys.readouterr()
    assert generated.out == (
        "Pyganini generated state: written=4 unchanged=0 removed=0.\n"
    )
    assert generated.err == ""

    assert main(["check", "--app-root", str(application)]) == 0
    checked = capsys.readouterr()
    assert checked.out == "Pyganini generated state is current.\n"
    assert checked.err == ""


def test_routes_list_empty_inventory_has_stable_text_header(
    tmp_path: Path,
    make_app: Callable[..., Path],
    capsys: pytest.CaptureFixture[str],
) -> None:
    application = make_app(tmp_path / "application")

    assert main(["routes", "list", "--app-root", str(application)]) == 0

    output = capsys.readouterr()
    assert output.out == (
        "KIND  METHOD  PATH  PARAMS  SOURCE  OWNER  MOUNT  SOURCE_PATH  DECL  "
        "NAME  TITLE  LABELS  NAV  TRAIL_KEYS  DESTINATIONS  INBOUND  "
        "IMPLEMENTATION  HELPER\n"
        "ERROR_RENDER page=- fragment=- root_layouts=[]\n"
    )
    assert output.err == ""


def test_routes_render_units_empty_inventory_has_stable_text_header(
    tmp_path: Path,
    make_app: Callable[..., Path],
    capsys: pytest.CaptureFixture[str],
) -> None:
    application = make_app(tmp_path / "application")

    assert main(["routes", "render-units", "--app-root", str(application)]) == 0

    output = capsys.readouterr()
    assert output.out.startswith(
        "KIND  METHOD  ROUTE  TEMPLATE  TEMPLATE_SOURCE  SOURCE  OWNER  MOUNT  "
        "SOURCE_PATH  LAYOUT_MODE  EFFECTIVE_LAYOUTS\n"
    )
    assert output.err == ""

    assert (
        main(
            [
                "routes",
                "render-units",
                "--app-root",
                str(application),
                "--json",
            ]
        )
        == 0
    )
    json_output = capsys.readouterr()
    assert json_output.out == (
        '{\n  "schema": "pyganini.render_units.v1",\n  "render_units": []\n}\n'
    )
    assert json_output.err == ""


def test_routes_render_units_reports_declared_templates_and_layout_modes(
    tmp_path: Path,
    make_app: Callable[..., Path],
    capsys: pytest.CaptureFixture[str],
) -> None:
    application = _render_unit_application(make_app(tmp_path / "application"))
    (application / "app" / "routes" / "users" / "page.jinja").write_text(
        "{% invalid", encoding="ascii"
    )

    assert main(["routes", "render-units", "--app-root", str(application)]) == 0
    output = capsys.readouterr()
    assert output.err == ""
    assert output.out.startswith(
        "KIND      METHOD    ROUTE          TEMPLATE                   TEMPLATE_SOURCE"
    )
    assert (
        "page      GET,HEAD  /users         routes/users/page.jinja    "
        "app/routes/users/page.jinja:1:1"
    ) in output.out
    assert (
        "action    POST      /users/create  routes/users/create.jinja  "
        "app/routes/users/create.jinja:1:1"
    ) in output.out
    assert (
        "fragment  GET,HEAD  /users/table   routes/users/table.jinja   "
        "app/routes/users/table.jinja:1:1"
    ) in output.out
    assert "routes/layout.jinja@app/routes/layout.py:1:1@" in output.out
    assert "routes/users/layout.jinja@app/routes/users/layout.py:1:1@" in output.out
    assert "page-result" in output.out
    assert "none" in output.out
    assert "/users/direct" not in output.out

    assert (
        main(["routes", "render-units", "--app-root", str(application), "--json"]) == 0
    )
    json_output = capsys.readouterr()
    assert json_output.err == ""
    payload = json.loads(json_output.out)
    assert list(payload) == ["schema", "render_units"]
    assert payload["schema"] == "pyganini.render_units.v1"
    assert [row["kind"] for row in payload["render_units"]] == [
        "page",
        "action",
        "fragment",
    ]
    rows = {row["kind"]: row for row in payload["render_units"]}
    assert list(rows["page"]) == [
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
    assert rows["page"]["template"] == {
        "name": "routes/users/page.jinja",
        "source": {
            "path": "app/routes/users/page.jinja",
            "line": 1,
            "column": 1,
        },
    }
    assert rows["page"]["layout_mode"] == "page"
    assert rows["fragment"]["layout_mode"] == "none"
    assert rows["fragment"]["effective_layouts"] == []
    assert rows["action"]["layout_mode"] == "page-result"
    assert rows["action"]["mount"] is None
    assert rows["action"]["source_path"] is None
    assert len(rows["page"]["effective_layouts"]) == 2
    assert rows["page"]["effective_layouts"][0]["template"]["name"] == (
        "routes/layout.jinja"
    )
    assert rows["page"]["effective_layouts"][1]["template"]["name"] == (
        "routes/users/layout.jinja"
    )


def test_routes_refs_reports_direct_literal_and_generated_values(
    tmp_path: Path,
    make_app: Callable[..., Path],
    capsys: pytest.CaptureFixture[str],
) -> None:
    application = make_app(tmp_path / "application")
    routes = application / "app" / "routes"
    (routes / "route.py").write_text(
        "from pyganini import action, route\n"
        "def page(request): return None\n"
        "def save(request): return None\n"
        "Route = route(\n"
        "    page=page,\n"
        "    template='page.jinja',\n"
        "    actions=(action('POST', '/save', save, template='save.jinja'),),\n"
        ")\n",
        encoding="ascii",
    )
    (routes / "page.jinja").write_text(
        '<button hx-get="/"></button>\n'
        '<button hx-post="{{ urls.save.path }}"></button>\n',
        encoding="ascii",
    )
    (routes / "save.jinja").write_text(
        '<button data-hx-get="/missing"></button>\n',
        encoding="ascii",
    )

    assert main(["routes", "refs", "--app-root", str(application)]) == 0

    output = capsys.readouterr()
    assert output.err == ""
    assert output.out == (
        "STATUS     METHOD  ROUTE     KIND    ATTRIBUTE    SOURCE                     "
        "VALUE\n"
        "resolved   GET     /         page    hx-get       app/routes/page.jinja:1:1  "
        "/\n"
        "resolved   POST    /save     action  hx-post      app/routes/page.jinja:2:1  "
        '"{{ urls.save.path }}"\n'
        "unmatched  GET     /missing  -       data-hx-get  app/routes/save.jinja:1:1  "
        "/missing\n"
    )


def test_routes_render_units_is_source_only_and_repeated_bytes_are_stable(
    tmp_path: Path,
    make_app: Callable[..., Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    application = _render_unit_application(make_app(tmp_path / "application"))
    (application / "app" / "__init__.py").write_text(
        "raise RuntimeError('application module must not be imported')\n",
        encoding="ascii",
    )
    route_file = application / "app" / "routes" / "users" / "route.py"
    route_file.write_text(
        "raise RuntimeError('route module must not be imported')\n"
        + route_file.read_text(encoding="ascii"),
        encoding="ascii",
    )
    generated = application / "app" / "_pyganini"
    generated.mkdir()
    (generated / ".pyganini-root").write_bytes(b"unsafe generated state\n")
    for name in ("__init__.py", "asgi.py", "urls.py"):
        (generated / name).write_text(
            "raise RuntimeError('generated module must not be imported')\n",
            encoding="ascii",
        )
    before = _snapshot(application)

    def fail_url_projection(_: object) -> object:
        raise AssertionError("render-unit inspection must not validate URL helpers")

    monkeypatch.setattr(cli_module, "_url_helper_projection", fail_url_projection)

    arguments = ["routes", "render-units", "--app-root", str(application)]
    assert main(arguments) == 0
    first = capsys.readouterr()
    assert first.err == ""
    assert "routes/users/page.jinja" in first.out
    assert main(arguments) == 0
    second = capsys.readouterr()
    assert second == first

    json_arguments = [*arguments, "--json"]
    assert main(json_arguments) == 0
    json_first = capsys.readouterr()
    assert json_first.err == ""
    assert json.loads(json_first.out)["schema"] == "pyganini.render_units.v1"
    assert main(json_arguments) == 0
    json_second = capsys.readouterr()
    assert json_second == json_first
    assert _snapshot(application) == before


def test_routes_render_units_projection_failure_has_no_partial_output(
    tmp_path: Path,
    make_app: Callable[..., Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    application = make_app(tmp_path / "application")
    (application / "app" / "routes" / "route.py").write_text(
        "from pyganini import route\n"
        "def page(request): return None\n"
        "Route = route(page=page, template='page.jinja')\n",
        encoding="ascii",
    )
    (application / "app" / "routes" / "page.jinja").write_text(
        "{{ value }}\n", encoding="ascii"
    )

    def fail_projection(_: object) -> tuple[object, ...]:
        raise InspectionError("render-unit projection failed")

    monkeypatch.setattr(cli_module, "_render_unit_rows", fail_projection)

    assert main(["routes", "render-units", "--app-root", str(application)]) == 1
    output = capsys.readouterr()
    assert output.out == ""
    assert output.err == (
        "pyganini routes render-units: PYGANINI017 route-inspection: "
        "render-unit projection failed\n"
    )


def test_routes_render_units_payload_failure_has_no_partial_output(
    tmp_path: Path,
    make_app: Callable[..., Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    application = make_app(tmp_path / "application")
    (application / "app" / "routes" / "route.py").write_text(
        "from pyganini import route\n"
        "def page(request): return None\n"
        "Route = route(page=page)\n",
        encoding="ascii",
    )

    def fail_payload(_: object, *, json_output: bool) -> bytes:
        raise InspectionError(
            "render-unit JSON encoding failed"
            if json_output
            else "render-unit encoding failed"
        )

    monkeypatch.setattr(cli_module, "_render_unit_payload", fail_payload)

    assert (
        main(
            [
                "routes",
                "render-units",
                "--app-root",
                str(application),
                "--json",
            ]
        )
        == 1
    )
    output = capsys.readouterr()
    assert output.out == ""
    assert output.err == (
        "pyganini routes render-units: PYGANINI017 route-inspection: "
        "render-unit JSON encoding failed\n"
    )


def test_routes_render_units_graph_failure_precedes_projection_output(
    tmp_path: Path,
    make_app: Callable[..., Path],
    capsys: pytest.CaptureFixture[str],
) -> None:
    application = make_app(tmp_path / "application")
    (application / "app" / "routes" / "route.py").write_text(
        "from pyganini import route\nRoute = route(page=missing)\n",
        encoding="ascii",
    )

    assert main(["routes", "render-units", "--app-root", str(application)]) == 1
    output = capsys.readouterr()
    assert output.out == ""
    assert "PYGANINI010 route-declaration" in output.err


def test_routes_render_units_output_failure_has_no_partial_output(
    tmp_path: Path,
    make_app: Callable[..., Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    application = make_app(tmp_path / "application")
    (application / "app" / "routes" / "route.py").write_text(
        "from pyganini import route\n"
        "def page(request): return None\n"
        "Route = route(page=page)\n",
        encoding="ascii",
    )

    class BrokenOutput:
        def write(self, _: str) -> int:
            raise RuntimeError("stdout unavailable")

    monkeypatch.setattr("pyganini._cli.sys.stdout", BrokenOutput())

    assert main(["routes", "render-units", "--app-root", str(application)]) == 1
    output = capsys.readouterr()
    assert output.out == ""
    assert output.err == (
        "pyganini routes render-units: PYGANINI017 route-inspection: "
        "stdout unavailable\n"
    )


def test_template_reference_projection_uses_public_jinja_and_html_boundaries() -> None:
    source = (
        "{# hidden <button hx-get='/comment'></button> #}\n"
        "{%- if enabled -%}\n"
        '<button HX-GET="{{ value }}" data-HX-POST="/save" '
        'hx-get="/duplicate" hx-target="#slot">\n'
        "{% endif %}\n"
    )

    masked = template_references_module._mask_jinja(source)
    assert len(masked.expressions) == 1
    sentinel = next(iter(masked.expressions))
    assert sentinel in masked.text
    assert masked.text.count("\n") == 3

    parser = template_references_module._HTMXAttributeParser()
    parser.feed(masked.text)
    parser.close()
    assert [
        (occurrence.attribute, occurrence.method, occurrence.line, occurrence.value)
        for occurrence in parser.occurrences
    ] == [
        ("hx-get", "GET", 3, sentinel),
        ("data-hx-post", "POST", 3, "/save"),
        ("hx-get", "GET", 3, "/duplicate"),
    ]


def test_template_reference_sentinel_skips_literal_collision() -> None:
    assert template_references_module._sentinel("literal __PYGANINI_REF_0__", 0) == (
        "__PYGANINI_REF_1__",
        2,
    )


def test_routes_refs_reserves_sentinel_against_html_character_references(
    tmp_path: Path,
    make_app: Callable[..., Path],
    capsys: pytest.CaptureFixture[str],
) -> None:
    application = _reference_application(
        make_app(tmp_path / "application"),
        '<button hx-get="/__PYGANINI&#95;REF_0__"></button>\n'
        '<button hx-get="{{ value }}"></button>\n',
    )

    assert (
        main(
            [
                "routes",
                "refs",
                "--app-root",
                str(application),
                "--json",
            ]
        )
        == 0
    )

    output = capsys.readouterr()
    assert output.err == ""
    references = json.loads(output.out)["references"]
    by_value = {reference["value"]: reference for reference in references}
    assert by_value["/__PYGANINI_REF_0__"]["status"] == "unmatched"
    assert by_value["{{ value }}"]["status"] == "dynamic"
    assert "/{{ value }}" not in by_value


def test_routes_refs_empty_source_inventory_has_stable_text_header(
    tmp_path: Path,
    make_app: Callable[..., Path],
    capsys: pytest.CaptureFixture[str],
) -> None:
    application = make_app(tmp_path / "application")

    assert main(["routes", "refs", "--app-root", str(application)]) == 0

    output = capsys.readouterr()
    assert output.out == ("STATUS  METHOD  ROUTE  KIND  ATTRIBUTE  SOURCE  VALUE\n")
    assert output.err == ""


def test_routes_refs_scans_graph_derived_route_shared_and_mount_roots_once(
    tmp_path: Path,
    make_app: Callable[..., Path],
    capsys: pytest.CaptureFixture[str],
) -> None:
    application = make_app(tmp_path / "application")
    routes = application / "app" / "routes"
    (routes / "route.py").write_text(
        "from pyganini import route\n"
        "def page(request): return None\n"
        "Route = route(page=page, template='page.jinja')\n",
        encoding="ascii",
    )
    (routes / "page.jinja").write_text(
        '<button hx-get="/"></button>\n', encoding="ascii"
    )
    (routes / "unreferenced.jinja").write_text(
        '<button hx-post="/route-extra"></button>\n', encoding="ascii"
    )
    shared = application / "app" / "shared" / "reports"
    shared.mkdir(parents=True)
    (application / "app" / "shared" / "__init__.py").write_text("", encoding="ascii")
    (shared / "__init__.py").write_text("", encoding="ascii")
    (shared / "page.jinja").write_text(
        '<button hx-get="/shared"></button>\n', encoding="ascii"
    )
    (shared / "unreferenced.jinja").write_text(
        '<button hx-post="/shared-extra"></button>\n', encoding="ascii"
    )
    (application / "app" / "shared" / "page.jinja").write_text(
        '<button hx-get="/shared-root"></button>\n', encoding="ascii"
    )
    users = routes / "users"
    users.mkdir()
    (users / "__init__.py").write_text("", encoding="ascii")
    (users / "route.py").write_text(
        "from pyganini import route_kit\n"
        "import app.shared.reports as reports\n"
        "def create(request): return reports.Kit()\n"
        "Route = route_kit(\n"
        "    create=create,\n"
        "    template_root='shared/reports',\n"
        "    page=reports.page,\n"
        "    template='page.jinja',\n"
        ")\n",
        encoding="ascii",
    )
    admin = routes / "admin"
    admin.mkdir()
    (admin / "__init__.py").write_text("", encoding="ascii")
    (admin / "route.py").write_text(
        "from pyganini import route_kit\n"
        "import app.shared.reports as reports\n"
        "def create(request): return reports.Kit()\n"
        "Route = route_kit(\n"
        "    create=create,\n"
        "    template_root='shared',\n"
        "    page=reports.page,\n"
        "    template='page.jinja',\n"
        ")\n",
        encoding="ascii",
    )
    mounts = application / "app" / "mounts"
    mounted = mounts / "directory"
    mounted.mkdir(parents=True)
    (mounts / "__init__.py").write_text("", encoding="ascii")
    (mounted / "__init__.py").write_text("", encoding="ascii")
    (mounted / "page.jinja").write_text(
        '<button hx-get="/mounted"></button>\n', encoding="ascii"
    )
    (mounted / "unreferenced.jinja").write_text(
        '<button hx-post="/mounted-extra"></button>\n', encoding="ascii"
    )
    (mounted / "route.py").write_text(
        "from pyganini import route_kit\n"
        "def page(kit, request): return kit\n"
        "Route = route_kit(page=page, template='page.jinja')\n",
        encoding="ascii",
    )
    owner = routes / "mounted"
    owner.mkdir()
    (owner / "__init__.py").write_text("", encoding="ascii")
    (owner / "route.py").write_text(
        "from pyganini import route_mount\n"
        "def create(request): return object()\n"
        "Route = route_mount(create=create, mount='directory')\n",
        encoding="ascii",
    )
    (application / "app" / "ignored.jinja").write_text(
        '<button hx-get="/ignored"></button>\n', encoding="ascii"
    )

    assert main(["routes", "refs", "--app-root", str(application)]) == 0
    output = capsys.readouterr()
    assert output.err == ""
    assert {line.split("  ")[-1] for line in output.out.splitlines()[1:]} >= {
        "/",
        "/route-extra",
        "/shared",
        "/shared-extra",
        "/mounted",
        "/mounted-extra",
    }
    assert "/ignored" not in output.out
    assert output.out.count("app/shared/page.jinja:1:1") == 1
    assert "app/routes/unreferenced.jinja" in output.out
    assert "app/shared/reports/unreferenced.jinja" in output.out
    assert "app/mounts/directory/unreferenced.jinja" in output.out


def test_routes_refs_json_masks_jinja_and_keeps_only_direct_request_attributes(
    tmp_path: Path,
    make_app: Callable[..., Path],
    capsys: pytest.CaptureFixture[str],
) -> None:
    application = make_app(tmp_path / "application")
    routes = application / "app" / "routes"
    (routes / "route.py").write_text(
        "from pyganini import action, fragment_route, route\n"
        "def page(request): return None\n"
        "def table(request): return None\n"
        "def save(request): return None\n"
        "Route = route(\n"
        "    page=page,\n"
        "    template='page.jinja',\n"
        "    fragments=(fragment_route('/table', table),),\n"
        "    actions=(action('POST', '/save', save),),\n"
        ")\n",
        encoding="ascii",
    )
    users = routes / "users" / "by_id"
    users.mkdir(parents=True)
    (routes / "users" / "__init__.py").write_text("", encoding="ascii")
    (users / "__init__.py").write_text("", encoding="ascii")
    (users / "route.py").write_text(
        "from pyganini import route\n"
        "def page(request): return None\n"
        "Route = route(page=page)\n",
        encoding="ascii",
    )
    (routes / "page.jinja").write_text(
        "<!-- <button hx-get='/comment'></button> -->\n"
        "<button\n"
        '  HX-GET="/?view=full&amp;mode=compact"\n'
        '  data-HX-POST="/save"\n'
        '  hx-get="/save"\n'
        '  hx-get="/users/42"\n'
        '  hx-get="{{ urls.users.by_id(42).path }}?view=full"\n'
        '  hx-get="{{ urls.users.by_id(id=42).path }}"\n'
        '  hx-get="{{\n'
        "    urls.users.by_id(id=42).path\n"
        '  }}"\n'
        '  hx-get="{{ urls.users.by_id(42, 43).path }}"\n'
        "  hx-get=\"{{ '/table' }}\"\n"
        '  hx-get="{{ value }}"\n'
        '  hx-get="?prefix{{ urls.users.by_id(42).path }}"\n'
        '  hx-get="{{ urls.unknown.path }}"\n'
        '  hx-get="{{ layout.urls.users.path }}"\n'
        '  hx-get="{{ urls.users.by_id(42).path }}{{ value }}"\n'
        '  hx-get="{{ urls.users.by_id(42).path }}/extra"\n'
        '  hx-get="https://example.test/users"\n'
        '  hx-get="https://example.test:bad/users"\n'
        '  hx-get="/bad%ZZ"\n'
        '  hx-put="relative"\n'
        "  hx-patch\n"
        '  href="/not-an-htmx-reference"\n'
        '  hx-target="#slot">\n'
        "</button>\n"
        "{% if enabled %}\n"
        '<button hx-delete="/missing"></button>\n'
        "{% endif %}\n"
        '{% raw %}<button hx-get="/raw"></button>{% endraw %}\n'
        "{%- if enabled -%}\n"
        '<button hx-get="/whitespace"></button>\n'
        "{%- endif -%}\n"
        '<style><button hx-get="/style"></button></style>\n'
        '<script><button hx-get="/script"></button></script>\n'
        '<button hx-get="/unterminated"\n',
        encoding="ascii",
    )

    assert (
        main(
            [
                "routes",
                "refs",
                "--app-root",
                str(application),
                "--json",
            ]
        )
        == 0
    )

    output = capsys.readouterr()
    assert output.err == ""
    payload = json.loads(output.out)
    assert list(payload) == ["schema", "references"]
    references = payload["references"]
    assert {reference["attribute"] for reference in references} <= {
        "hx-get",
        "hx-post",
        "hx-put",
        "hx-patch",
        "hx-delete",
        "data-hx-get",
        "data-hx-post",
        "data-hx-put",
        "data-hx-patch",
        "data-hx-delete",
    }
    by_value = {
        (reference["attribute"], reference["value"]): reference
        for reference in references
    }
    assert by_value[("hx-get", "/?view=full&mode=compact")]["status"] == "resolved"
    assert by_value[("data-hx-post", "/save")]["status"] == "resolved"
    assert by_value[("hx-get", "/save")]["status"] == "unmatched"
    assert by_value[("hx-get", "/users/42")]["status"] == "unmatched"
    assert (
        by_value[("hx-get", "{{ urls.users.by_id(42).path }}?view=full")]["status"]
        == "resolved"
    )
    assert (
        by_value[("hx-get", "{{ urls.users.by_id(id=42).path }}")]["status"]
        == "resolved"
    )
    assert (
        by_value[("hx-get", "{{\n    urls.users.by_id(id=42).path\n  }}")]["status"]
        == "resolved"
    )
    assert (
        by_value[("hx-get", "{{ urls.users.by_id(42, 43).path }}")]["status"]
        == "invalid"
    )
    assert by_value[("hx-get", "{{ '/table' }}")]["status"] == "resolved"
    assert by_value[("hx-get", "{{ value }}")]["status"] == "dynamic"
    assert (
        by_value[("hx-get", "?prefix{{ urls.users.by_id(42).path }}")]["status"]
        == "dynamic"
    )
    assert by_value[("hx-get", "{{ urls.unknown.path }}")]["status"] == "dynamic"
    assert by_value[("hx-get", "{{ layout.urls.users.path }}")]["status"] == "dynamic"
    assert (
        by_value[("hx-get", "{{ urls.users.by_id(42).path }}{{ value }}")]["status"]
        == "dynamic"
    )
    assert (
        by_value[("hx-get", "{{ urls.users.by_id(42).path }}/extra")]["status"]
        == "dynamic"
    )
    assert by_value[("hx-get", "https://example.test/users")]["status"] == "external"
    assert by_value[("hx-get", "https://example.test:bad/users")]["status"] == "invalid"
    assert by_value[("hx-get", "/bad%ZZ")]["status"] == "invalid"
    assert by_value[("hx-put", "relative")]["status"] == "invalid"
    assert by_value[("hx-patch", "")]["status"] == "invalid"
    assert by_value[("hx-delete", "/missing")]["status"] == "unmatched"
    assert by_value[("hx-get", "/raw")]["status"] == "unmatched"
    assert by_value[("hx-get", "/whitespace")]["status"] == "unmatched"
    assert by_value[("hx-get", "{{ urls.users.by_id(42).path }}?view=full")][
        "source"
    ] == {"path": "app/routes/page.jinja", "line": 2, "column": 1}
    assert not any(reference["value"] == "/comment" for reference in references)
    assert not any(reference["value"] == "/style" for reference in references)
    assert not any(reference["value"] == "/script" for reference in references)
    (routes / "page.jinja").write_text(
        '<button hx-get="/"></button>\n'
        '<button hx-post="{{ urls.save.path }}"></button>\n',
        encoding="ascii",
    )
    (routes / "save.jinja").write_text(
        '<button data-hx-get="/missing"></button>\n',
        encoding="ascii",
    )

    assert main(["routes", "refs", "--app-root", str(application)]) == 0

    output = capsys.readouterr()
    assert output.err == ""
    assert output.out == (
        "STATUS     METHOD  ROUTE     KIND    ATTRIBUTE    SOURCE                     "
        "VALUE\n"
        "resolved   GET     /         page    hx-get       app/routes/page.jinja:1:1  "
        "/\n"
        "resolved   POST    /save     action  hx-post      app/routes/page.jinja:2:1  "
        '"{{ urls.save.path }}"\n'
        "unmatched  GET     /missing  -       data-hx-get  app/routes/save.jinja:1:1  "
        "/missing\n"
    )


def test_routes_refs_invalid_utf8_fails_without_partial_output(
    tmp_path: Path,
    make_app: Callable[..., Path],
    capsys: pytest.CaptureFixture[str],
) -> None:
    application = make_app(tmp_path / "application")
    routes = application / "app" / "routes"
    (routes / "route.py").write_text(
        "from pyganini import route\n"
        "def page(request): return None\n"
        "Route = route(page=page, template='page.jinja')\n",
        encoding="ascii",
    )
    (routes / "page.jinja").write_text(
        '<button hx-get="/"></button>\n', encoding="ascii"
    )
    (routes / "z-invalid.jinja").write_bytes(b'<button hx-get="/">\xff')

    assert main(["routes", "refs", "--app-root", str(application)]) == 1

    output = capsys.readouterr()
    assert output.out == ""
    assert output.err.startswith("pyganini routes refs: PYGANINI017 route-inspection: ")
    assert "not valid UTF-8" in output.err


@pytest.mark.skipif(os.name == "nt", reason="POSIX symlink proof")
def test_routes_refs_jinja_symlink_fails_without_following_target(
    tmp_path: Path,
    make_app: Callable[..., Path],
    capsys: pytest.CaptureFixture[str],
) -> None:
    application = make_app(tmp_path / "application")
    routes = application / "app" / "routes"
    (routes / "route.py").write_text(
        "from pyganini import route\n"
        "def page(request): return None\n"
        "Route = route(page=page, template='page.jinja')\n",
        encoding="ascii",
    )
    (routes / "page.jinja").write_text(
        '<button hx-get="/"></button>\n', encoding="ascii"
    )
    target = tmp_path / "outside.jinja"
    target.write_text('<button hx-get="/outside"></button>\n', encoding="ascii")
    os.symlink(target, routes / "z-link.jinja")

    assert main(["routes", "refs", "--app-root", str(application)]) == 1

    output = capsys.readouterr()
    assert output.out == ""
    assert output.err.startswith("pyganini routes refs: PYGANINI017 route-inspection: ")
    assert "not a regular file" in output.err


@pytest.mark.parametrize("source", ["{% if broken", "{%", "{#"])
def test_routes_refs_unclosed_jinja_fails_with_template_path(
    tmp_path: Path,
    make_app: Callable[..., Path],
    source: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    application = _reference_application(make_app(tmp_path / "application"), source)

    assert main(["routes", "refs", "--app-root", str(application)]) == 1

    output = capsys.readouterr()
    assert output.out == ""
    assert output.err.startswith("pyganini routes refs: PYGANINI017 route-inspection: ")
    assert "app/routes/page.jinja" in output.err
    assert "Jinja lexical analysis failed" in output.err


def test_routes_refs_unreadable_root_fails_without_partial_output(
    tmp_path: Path,
    make_app: Callable[..., Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    application = _reference_application(
        make_app(tmp_path / "application"), '<button hx-get="/"></button>\n'
    )
    paths = paths_module.select_project_paths(
        explicit=application, start=None, validate_generated=False
    )
    graph = route_graph_module.build_route_graph(paths)

    def fail_open(_: Path) -> object:
        raise PermissionError("root unavailable")

    def return_graph(_: object) -> object:
        return graph

    monkeypatch.setattr("pyganini._cli.build_route_graph", return_graph)
    monkeypatch.setattr("pyganini._route_graph._open_route_root", fail_open)
    assert main(["routes", "refs", "--app-root", str(application)]) == 1

    output = capsys.readouterr()
    assert output.out == ""
    assert "cannot access selected template root app/routes" in output.err


@pytest.mark.parametrize("failure", ["read", "race", "wrong-kind", "close"])
def test_routes_refs_held_filesystem_failures_are_reported(
    tmp_path: Path,
    make_app: Callable[..., Path],
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    application = _reference_application(
        make_app(tmp_path / "application"), '<button hx-get="/"></button>\n'
    )
    paths = paths_module.select_project_paths(
        explicit=application, start=None, validate_generated=False
    )
    graph = route_graph_module.build_route_graph(paths)
    entry_kind = route_graph_module._RouteEntryKind.REGULAR

    class BrokenDirectory:
        def entries(self) -> tuple[str, ...]:
            return ("page.jinja",)

        def entry_kind(self, _: str) -> object:
            if failure == "race":
                raise FileNotFoundError("directory entry disappeared")
            if failure == "wrong-kind":
                return route_graph_module._RouteEntryKind.DIRECTORY
            return entry_kind

        def read_regular(self, _: str) -> bytes:
            if failure == "read":
                raise PermissionError("file unavailable")
            return b'<button hx-get="/"></button>\n'

        def close(self) -> None:
            if failure == "close":
                raise OSError("close failed")

    def return_graph(_: object) -> object:
        return graph

    def open_broken(_: object) -> object:
        return BrokenDirectory()

    monkeypatch.setattr("pyganini._cli.build_route_graph", return_graph)
    monkeypatch.setattr("pyganini._route_graph._open_route_root", open_broken)
    assert main(["routes", "refs", "--app-root", str(application)]) == 1

    output = capsys.readouterr()
    assert output.out == ""
    assert output.err.startswith("pyganini routes refs: PYGANINI017 route-inspection: ")
    assert {
        "read": "cannot read selected .jinja file",
        "race": "cannot inspect selected template entry",
        "wrong-kind": "selected .jinja entry is not a regular file",
        "close": "cannot close selected template directory",
    }[failure] in output.err


def test_routes_refs_parser_failure_has_no_partial_output(
    tmp_path: Path,
    make_app: Callable[..., Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    application = _reference_application(
        make_app(tmp_path / "application"), '<button hx-get="/"></button>\n'
    )

    def fail_feed(self: object, _: str) -> None:
        raise RuntimeError("parser unavailable")

    monkeypatch.setattr(
        template_references_module._HTMXAttributeParser, "feed", fail_feed
    )
    assert main(["routes", "refs", "--app-root", str(application)]) == 1

    output = capsys.readouterr()
    assert output.out == ""
    assert "HTMLParser failed for app/routes/page.jinja" in output.err


def test_routes_refs_reconciliation_failure_has_no_partial_output(
    tmp_path: Path,
    make_app: Callable[..., Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    application = _reference_application(
        make_app(tmp_path / "application"), '<button hx-get="/"></button>\n'
    )

    def fail_resolution(*_: object, **__: object) -> tuple[str, str | None, object]:
        raise InspectionError("reconciliation failed")

    monkeypatch.setattr(template_references_module, "_resolve_value", fail_resolution)
    assert main(["routes", "refs", "--app-root", str(application)]) == 1

    output = capsys.readouterr()
    assert output.out == ""
    assert "reference resolution failed for app/routes/page.jinja" in output.err
    assert "reconciliation failed" in output.err


def test_routes_refs_real_helper_collision_fails_before_inventory_output(
    tmp_path: Path,
    make_app: Callable[..., Path],
    capsys: pytest.CaptureFixture[str],
) -> None:
    application = make_app(tmp_path / "application")
    path_route = application / "app" / "routes" / "path"
    path_route.mkdir()
    (path_route / "__init__.py").write_text("", encoding="ascii")
    (path_route / "route.py").write_text(
        "from pyganini import route\n"
        "def page(request): return None\n"
        "Route = route(page=page)\n",
        encoding="ascii",
    )
    assert main(["routes", "refs", "--app-root", str(application)]) == 1

    output = capsys.readouterr()
    assert output.out == ""
    assert "PYGANINI016 url-interface" in output.err


@pytest.mark.parametrize(
    "arguments",
    [
        ("--unknown",),
        ("extra",),
        ("--app-root",),
        ("--json=invalid",),
    ],
)
def test_routes_refs_rejects_invalid_argparse_forms_before_root_selection(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    arguments: tuple[str, ...],
) -> None:
    selected = False

    def fail_selection(*_: object, **__: object) -> object:
        nonlocal selected
        selected = True
        raise AssertionError("root selection must not run")

    monkeypatch.setattr(cli_module, "select_project_paths", fail_selection)
    assert main(["routes", "refs", *arguments]) == 2

    output = capsys.readouterr()
    assert output.out == ""
    assert "usage: pyganini" in output.err
    assert not selected


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission and symlink proof")
@pytest.mark.parametrize(
    "generated_state",
    ["absent", "stale", "malformed", "unreadable", "symlink", "raising"],
)
def test_routes_refs_ignores_every_unsafe_generated_state(
    tmp_path: Path,
    make_app: Callable[..., Path],
    generated_state: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    application = _reference_application(
        make_app(tmp_path / "application"), '<button hx-get="/"></button>\n'
    )
    (application / "app" / "__init__.py").write_text(
        "raise RuntimeError('application module must not be imported')\n",
        encoding="ascii",
    )
    generated = application / "app" / "_pyganini"
    if generated_state == "stale":
        generated.mkdir()
        for name in (".pyganini-root", "__init__.py", "asgi.py", "urls.py"):
            (generated / name).write_bytes(b"stale generated state\n")
    elif generated_state == "malformed":
        generated.write_bytes(b"generated path is not a directory\n")
    elif generated_state == "unreadable":
        generated.mkdir()
        generated.chmod(0o000)
    elif generated_state == "symlink":
        target = tmp_path / "generated-target"
        target.mkdir()
        generated.symlink_to(target, target_is_directory=True)
    elif generated_state == "raising":
        generated.mkdir()
        (generated / ".pyganini-root").write_bytes(b"unsafe generated state\n")
        for name in ("__init__.py", "asgi.py", "urls.py"):
            (generated / name).write_text(
                "raise RuntimeError('generated module must not be imported')\n",
                encoding="ascii",
            )

    try:
        assert main(["routes", "refs", "--app-root", str(application)]) == 0
        output = capsys.readouterr()
        assert output.err == ""
        assert "resolved" in output.out
    finally:
        if generated_state == "unreadable":
            generated.chmod(0o700)


def test_routes_refs_output_failure_has_no_partial_output(
    tmp_path: Path,
    make_app: Callable[..., Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    application = _reference_application(
        make_app(tmp_path / "application"), '<button hx-get="/"></button>\n'
    )

    class BrokenOutput:
        def write(self, _: str) -> int:
            raise RuntimeError("stdout unavailable")

    monkeypatch.setattr("pyganini._cli.sys.stdout", BrokenOutput())
    assert main(["routes", "refs", "--app-root", str(application)]) == 1

    output = capsys.readouterr()
    assert output.out == ""
    assert output.err == (
        "pyganini routes refs: PYGANINI017 route-inspection: stdout unavailable\n"
    )


def test_routes_layouts_empty_inventory_has_exact_ascii_output(
    tmp_path: Path,
    make_app: Callable[..., Path],
    capsys: pytest.CaptureFixture[str],
) -> None:
    application = make_app(tmp_path / "application")

    assert main(["routes", "layouts", "--app-root", str(application)]) == 0

    output = capsys.readouterr()
    assert output.out == (
        "LAYOUT MAP\n"
        "/\n"
        "\n"
        "RULES\n"
        "  Page results with a declared endpoint template use the displayed "
        "layout chain.\n"
        "  Fragment results are not layout-wrapped.\n"
        "  Direct Response results bypass templates and layouts.\n"
    )
    assert output.err == ""


def test_routes_explain_renders_one_matched_page_before_implementation(
    tmp_path: Path,
    make_app: Callable[..., Path],
    capsys: pytest.CaptureFixture[str],
) -> None:
    application = make_app(tmp_path / "application")
    (application / "app" / "routes" / "route.py").write_text(
        "from pyganini import route\n"
        "def page(request): return None\n"
        "Route = route(page=page)\n",
        encoding="ascii",
    )

    assert main(["routes", "explain", "--app-root", str(application), "/"]) == 0

    output = capsys.readouterr()
    assert output.out.startswith(
        "ROUTE EXPLAIN\n"
        'url_path="/"\n'
        'asgi_path="/"\n'
        "method=GET\n"
        "status=matched\n"
        "\n"
        "MATCH\n"
        "kind=page\n"
        "methods=GET,HEAD\n"
        "route=/\n"
        "dispatch_method=GET\n"
        "params=[]\n"
        "handler=app.routes.route.page\n"
        "source=app/routes/route.py:1:1\n"
        "owner=-\n"
        "mount=-\n"
        "source_path=-\n"
        "layouts=[]\n"
    )
    assert (
        output.out.index("\nDECLARATION\n")
        < output.out.index("\nIMPLEMENTATION\n")
        < output.out.index("\nERROR_RENDER\n")
        < output.out.index("\nRULES\n")
    )
    assert "\nDECLARATION\nkind=route\n" in output.out
    assert "\nIMPLEMENTATION\nkind=page\n" in output.out
    assert "declaration=app/routes/route.py:3:20\n" in output.out
    assert "\nERROR_RENDER\npage=-\nfragment=-\npage_layouts=[]\n" in output.out
    assert output.err == ""


def test_routes_explain_adds_declaration_implementation_and_error_evidence(
    tmp_path: Path,
    make_app: Callable[..., Path],
    capsys: pytest.CaptureFixture[str],
) -> None:
    application = make_app(tmp_path / "application")
    routes = application / "app" / "routes"
    (routes / "error_page.jinja").write_text("error\n", encoding="ascii")
    (routes / "error_fragment.jinja").write_text("error\n", encoding="ascii")
    (routes / "route.py").write_text(
        "from pyganini import RouteMeta, route\n"
        "def page(request): return None\n"
        "Route = route(\n"
        "    page=page, name='home', title='Home',\n"
        "    meta=RouteMeta(labels={'area': 'public'}),\n"
        "    error_page_template='error_page.jinja',\n"
        "    error_fragment_template='error_fragment.jinja',\n"
        ")\n",
        encoding="ascii",
    )

    assert main(["routes", "explain", "--app-root", str(application), "/"]) == 0

    output = capsys.readouterr()
    assert "\nDECLARATION\nkind=route\n" in output.out
    assert 'name="home"\n' in output.out
    assert 'title="Home"\n' in output.out
    assert 'labels={"area":"public"}\n' in output.out
    assert "\nIMPLEMENTATION\nkind=page\n" in output.out
    assert "binding=page\n" in output.out
    assert "\nERROR_RENDER\npage=routes/error_page.jinja@" in output.out
    assert "fragment=routes/error_fragment.jinja@" in output.out
    assert "fragment_layouts=[] (not wrapped)\n" in output.out
    assert output.err == ""

    assert main(["routes", "explain", "--app-root", str(application), "/missing"]) == 1
    negative = capsys.readouterr()
    assert negative.out == ""
    assert " error_page=routes/error_page.jinja@" in negative.err
    assert " error_fragment=routes/error_fragment.jinja@" in negative.err
    assert " root_layouts=[]\n" in negative.err


def test_routes_explain_decodes_full_url_target_once_and_normalizes_method(
    tmp_path: Path,
    make_app: Callable[..., Path],
    capsys: pytest.CaptureFixture[str],
) -> None:
    application = make_app(tmp_path / "application")
    users = application / "app" / "routes" / "users" / "by_id"
    users.mkdir(parents=True)
    (application / "app" / "routes" / "users" / "__init__.py").write_text(
        "", encoding="ascii"
    )
    (users / "__init__.py").write_text("", encoding="ascii")
    (application / "app" / "routes" / "route.py").write_text(
        "from pyganini import route\n"
        "def root(request): return None\n"
        "Route = route(page=root)\n",
        encoding="ascii",
    )
    (users / "route.py").write_text(
        "from pyganini import route\n"
        "def page(request): return None\n"
        "Route = route(page=page)\n",
        encoding="ascii",
    )

    target = "https://user:pass@example.test:8443/users/a%252Fb?bad=%ZZ#bad=%ZZ"
    assert (
        main(
            [
                "routes",
                "explain",
                target,
                "--app-root",
                str(application),
                "--method",
                " get ",
            ]
        )
        == 0
    )

    output = capsys.readouterr()
    assert output.err == ""
    assert 'url_path="/users/a%252Fb"\n' in output.out
    assert 'asgi_path="/users/a%2Fb"\n' in output.out
    assert "method=GET\n" in output.out
    assert 'params=[id="a%2Fb"]\n' in output.out
    assert "bad=" not in output.out

    assert (
        main(
            [
                "routes",
                "explain",
                "  /users/a%252Fb \t",
                "--app-root",
                str(application),
            ]
        )
        == 0
    )
    trimmed = capsys.readouterr()
    assert 'url_path="/users/a%252Fb"' in trimmed.out

    assert (
        main(
            [
                "routes",
                "explain",
                "http://example.test",
                "--app-root",
                str(application),
            ]
        )
        == 0
    )
    empty_url_path = capsys.readouterr()
    assert 'url_path="/"' in empty_url_path.out
    assert 'asgi_path="/"' in empty_url_path.out

    assert (
        main(
            [
                "routes",
                "explain",
                "//users/a%252Fb",
                "--app-root",
                str(application),
            ]
        )
        == 1
    )
    literal_double_slash = capsys.readouterr()
    assert literal_double_slash.out == ""
    assert 'url_path="//users/a%252Fb"' in literal_double_slash.err


@pytest.mark.parametrize(
    "target",
    [
        "custom+scheme://user%20name:pass@example.test:8443/",
        "http://[2001:db8::1]/",
        "http://[v1.a:b]/",
    ],
)
def test_routes_explain_accepts_valid_authority_forms(
    tmp_path: Path,
    make_app: Callable[..., Path],
    capsys: pytest.CaptureFixture[str],
    target: str,
) -> None:
    application = make_app(tmp_path / "application")
    (application / "app" / "routes" / "route.py").write_text(
        "from pyganini import route\n"
        "def page(request): return None\n"
        "Route = route(page=page)\n",
        encoding="ascii",
    )

    assert main(["routes", "explain", "--app-root", str(application), target]) == 0
    output = capsys.readouterr()
    assert output.err == ""
    assert 'url_path="/"\n' in output.out
    assert 'asgi_path="/"\n' in output.out


def test_routes_explain_uses_decoded_asgi_path_without_normalizing_slashes(
    tmp_path: Path,
    make_app: Callable[..., Path],
    capsys: pytest.CaptureFixture[str],
) -> None:
    application = make_app(tmp_path / "application")
    users = application / "app" / "routes" / "users" / "by_id"
    users.mkdir(parents=True)
    (application / "app" / "routes" / "users" / "__init__.py").write_text(
        "", encoding="ascii"
    )
    (users / "__init__.py").write_text("", encoding="ascii")
    (users / "route.py").write_text(
        "from pyganini import route\n"
        "def page(request): return None\n"
        "Route = route(page=page)\n",
        encoding="ascii",
    )

    for target in ("/users/a%2Fb", "/users/a/", "/users//"):
        assert main(["routes", "explain", "--app-root", str(application), target]) == 1
        output = capsys.readouterr()
        assert output.out == ""
        assert "status=404" in output.err

    assert (
        main(["routes", "explain", "--app-root", str(application), "/users/a%20b"]) == 0
    )
    spaced = capsys.readouterr()
    assert 'asgi_path="/users/a b"\n' in spaced.out
    assert 'params=[id="a b"]\n' in spaced.out

    assert (
        main(
            [
                "routes",
                "explain",
                "--app-root",
                str(application),
                "/users/x%3Fy%23z",
            ]
        )
        == 0
    )
    delimiters = capsys.readouterr()
    assert 'asgi_path="/users/x?y#z"\n' in delimiters.out
    assert 'params=[id="x?y#z"]\n' in delimiters.out

    raw_unicode = "/users/" + chr(0xE9)
    assert main(["routes", "explain", "--app-root", str(application), raw_unicode]) == 0
    escaped = capsys.readouterr()
    assert "\\u00e9" in escaped.out
    assert escaped.out.isascii()


def test_routes_explain_path_ownership_precedes_method_selection(
    tmp_path: Path,
    make_app: Callable[..., Path],
    capsys: pytest.CaptureFixture[str],
) -> None:
    application = make_app(tmp_path / "application")
    users = application / "app" / "routes" / "users"
    static = users / "new"
    dynamic = users / "by_id"
    static.mkdir(parents=True)
    dynamic.mkdir()
    (users / "__init__.py").write_text("", encoding="ascii")
    (static / "__init__.py").write_text("", encoding="ascii")
    (dynamic / "__init__.py").write_text("", encoding="ascii")
    (static / "route.py").write_text(
        "from pyganini import route\n"
        "def page(request): return None\n"
        "Route = route(page=page)\n",
        encoding="ascii",
    )
    (dynamic / "route.py").write_text(
        "from pyganini import action, route\n"
        "def save(request): return None\n"
        "Route = route(actions=(action('POST', '/', save),))\n",
        encoding="ascii",
    )

    assert (
        main(
            [
                "routes",
                "explain",
                "--method",
                "post",
                "--app-root",
                str(application),
                "/users/new",
            ]
        )
        == 1
    )
    not_allowed = capsys.readouterr()
    assert not_allowed.out == ""
    assert not_allowed.err == (
        "pyganini routes explain: PYGANINI017 route-inspection: method=POST "
        'url_path="/users/new" asgi_path="/users/new" status=405 '
        "route=/users/new method not allowed; allowed=GET,HEAD "
        "error_page=- error_fragment=- root_layouts=[]\n"
    )

    assert (
        main(
            [
                "routes",
                "explain",
                "--method",
                "POST",
                "--app-root",
                str(application),
                "/users/value",
            ]
        )
        == 0
    )
    matched = capsys.readouterr()
    assert matched.err == ""
    assert "status=matched\n" in matched.out
    assert "route=/users/{id}\n" in matched.out
    assert 'params=[id="value"]\n' in matched.out


def test_routes_explain_selects_every_declared_action_method(
    tmp_path: Path,
    make_app: Callable[..., Path],
    capsys: pytest.CaptureFixture[str],
) -> None:
    application = make_app(tmp_path / "application")
    (application / "app" / "routes" / "route.py").write_text(
        "from pyganini import action, route\n"
        "def post(request): return None\n"
        "def put(request): return None\n"
        "def patch(request): return None\n"
        "def delete(request): return None\n"
        "Route = route(actions=(\n"
        "    action('POST', '/post', post),\n"
        "    action('PUT', '/put', put),\n"
        "    action('PATCH', '/patch', patch),\n"
        "    action('DELETE', '/delete', delete),\n"
        "))\n",
        encoding="ascii",
    )

    for method, path in (
        ("POST", "/post"),
        ("PUT", "/put"),
        ("PATCH", "/patch"),
        ("DELETE", "/delete"),
    ):
        assert (
            main(
                [
                    "routes",
                    "explain",
                    "--method",
                    method,
                    "--app-root",
                    str(application),
                    path,
                ]
            )
            == 0
        )
        output = capsys.readouterr()
        assert output.err == ""
        assert "status=matched\n" in output.out
        assert f"method={method}\n" in output.out
        assert "kind=action\n" in output.out


def test_routes_explain_negative_outcomes_are_empty_stdout(
    tmp_path: Path,
    make_app: Callable[..., Path],
    capsys: pytest.CaptureFixture[str],
) -> None:
    application = make_app(tmp_path / "application")
    (application / "app" / "routes" / "route.py").write_text(
        "from pyganini import route\n"
        "def page(request): return None\n"
        "Route = route(page=page)\n",
        encoding="ascii",
    )

    assert main(["routes", "explain", "--app-root", str(application), "/missing"]) == 1
    missing = capsys.readouterr()
    assert missing.out == ""
    assert missing.err == (
        "pyganini routes explain: PYGANINI017 route-inspection: method=GET "
        'url_path="/missing" asgi_path="/missing" status=404 '
        "no route matches path error_page=- error_fragment=- root_layouts=[]\n"
    )

    assert (
        main(
            [
                "routes",
                "explain",
                "--method",
                "OPTIONS",
                "--app-root",
                str(application),
                "/",
            ]
        )
        == 1
    )
    options = capsys.readouterr()
    assert options.out == ""
    assert (
        'method=OPTIONS url_path="/" asgi_path="/" status=405 '
        "route=/ method not allowed; allowed=GET,HEAD"
    ) in options.err


@pytest.mark.parametrize(
    "arguments",
    [
        ("relative",),
        ("mailto:test",),
        ("http:///users",),
        ("http://:80/users",),
        ("http://%ZZ/users",),
        ("http://example^/users",),
        ("http://exa\\mple/users",),
        ("http://user@name@example.test/users",),
        ("http://\ud800/users",),
        ("http://[v1.a%20]/users",),
        ("/users/%",),
        ("/users/%G0",),
        ("/users/%FF",),
        ("/users/with space",),
        ("/users/with\x00control",),
        ("/users/with\x7fcontrol",),
        ("/users/\ud800",),
        ("--method", "bad method", "/users"),
        ("--method", "\u00e9", "/users"),
        ("--method", "", "/users"),
    ],
)
def test_routes_explain_rejects_invalid_input_before_root_selection(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    arguments: tuple[str, ...],
) -> None:
    selected = False

    def fail_selection(*_: object, **__: object) -> object:
        nonlocal selected
        selected = True
        raise AssertionError("root selection must not run")

    monkeypatch.setattr(cli_module, "select_project_paths", fail_selection)
    assert main(["routes", "explain", *arguments]) == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert "usage: pyganini" in output.err
    assert not selected


def test_routes_explain_is_source_only_and_preserves_application_snapshot(
    tmp_path: Path,
    make_app: Callable[..., Path],
    capsys: pytest.CaptureFixture[str],
) -> None:
    application = make_app(tmp_path / "application")
    (application / "app" / "__init__.py").write_text(
        "raise RuntimeError('application module must not be imported')\n",
        encoding="ascii",
    )
    (application / "app" / "routes" / "route.py").write_text(
        "from pyganini import route\n"
        "raise RuntimeError('route module must not be imported')\n"
        "def page(request): return None\n"
        "Route = route(page=page)\n",
        encoding="ascii",
    )
    generated = application / "app" / "_pyganini"
    generated.mkdir()
    (generated / ".pyganini-root").write_bytes(b"unsafe generated state\n")
    for name in ("__init__.py", "asgi.py", "urls.py"):
        (generated / name).write_text(
            "raise RuntimeError('generated module must not be imported')\n",
            encoding="ascii",
        )
    before = _snapshot(application)

    assert main(["routes", "explain", "--app-root", str(application), "/"]) == 0

    output = capsys.readouterr()
    assert output.err == ""
    assert "status=matched\n" in output.out
    assert _snapshot(application) == before


@pytest.mark.skipif(os.name == "nt", reason="POSIX symlink and permission proof")
@pytest.mark.parametrize(
    "generated_state",
    ["absent", "stale", "malformed", "unreadable", "symlink", "raising"],
)
def test_routes_explain_ignores_every_unsafe_generated_state(
    tmp_path: Path,
    make_app: Callable[..., Path],
    generated_state: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    application = make_app(tmp_path / "application")
    (application / "app" / "__init__.py").write_text(
        "raise RuntimeError('application module must not be imported')\n",
        encoding="ascii",
    )
    (application / "app" / "routes" / "route.py").write_text(
        "from pyganini import route\n"
        "raise RuntimeError('route module must not be imported')\n"
        "def page(request): return None\n"
        "Route = route(page=page)\n",
        encoding="ascii",
    )
    generated = application / "app" / "_pyganini"
    if generated_state == "stale":
        generated.mkdir()
        for name in (".pyganini-root", "__init__.py", "asgi.py", "urls.py"):
            (generated / name).write_bytes(b"stale generated state\n")
    elif generated_state == "malformed":
        generated.write_bytes(b"generated path is not a directory\n")
    elif generated_state == "unreadable":
        generated.mkdir()
        generated.chmod(0o000)
    elif generated_state == "symlink":
        target = tmp_path / "generated-target"
        target.mkdir()
        generated.symlink_to(target, target_is_directory=True)
    elif generated_state == "raising":
        generated.mkdir()
        (generated / ".pyganini-root").write_bytes(b"unsafe generated state\n")
        for name in ("__init__.py", "asgi.py", "urls.py"):
            (generated / name).write_text(
                "raise RuntimeError('generated module must not be imported')\n",
                encoding="ascii",
            )

    try:
        assert main(["routes", "explain", "--app-root", str(application), "/"]) == 0
        output = capsys.readouterr()
        assert output.err == ""
        assert "status=matched\n" in output.out
    finally:
        if generated_state == "unreadable":
            generated.chmod(0o700)


def test_routes_explain_projection_failure_has_no_partial_output(
    tmp_path: Path,
    make_app: Callable[..., Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    application = make_app(tmp_path / "application")
    (application / "app" / "routes" / "route.py").write_text(
        "from pyganini import route\n"
        "def page(request): return None\n"
        "Route = route(page=page)\n",
        encoding="ascii",
    )

    def fail_projection(*_: object, **__: object) -> bytes:
        raise InspectionError("explain projection failed")

    monkeypatch.setattr(cli_module, "_render_explain", fail_projection)
    assert main(["routes", "explain", "--app-root", str(application), "/"]) == 1

    output = capsys.readouterr()
    assert output.out == ""
    assert output.err == (
        "pyganini routes explain: PYGANINI017 route-inspection: "
        "explain projection failed\n"
    )


def test_routes_explain_output_failure_has_no_partial_output(
    tmp_path: Path,
    make_app: Callable[..., Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    application = make_app(tmp_path / "application")
    (application / "app" / "routes" / "route.py").write_text(
        "from pyganini import route\n"
        "def page(request): return None\n"
        "Route = route(page=page)\n",
        encoding="ascii",
    )

    class BrokenOutput:
        def write(self, _: str) -> int:
            raise RuntimeError("stdout unavailable")

    monkeypatch.setattr("pyganini._cli.sys.stdout", BrokenOutput())
    assert main(["routes", "explain", "--app-root", str(application), "/"]) == 1

    output = capsys.readouterr()
    assert output.out == ""
    assert output.err == (
        "pyganini routes explain: PYGANINI017 route-inspection: stdout unavailable\n"
    )


def test_routes_explain_graph_failure_precedes_matching_output(
    tmp_path: Path,
    make_app: Callable[..., Path],
    capsys: pytest.CaptureFixture[str],
) -> None:
    application = make_app(tmp_path / "application")
    (application / "app" / "routes" / "route.py").write_text(
        "from pyganini import route\nRoute = route(page=missing)\n",
        encoding="ascii",
    )

    assert main(["routes", "explain", "--app-root", str(application), "/"]) == 1

    output = capsys.readouterr()
    assert output.out == ""
    assert "PYGANINI010 route-declaration" in output.err
    assert "ROUTE EXPLAIN" not in output.out


def test_routes_explain_does_not_evaluate_url_helper_projection(
    tmp_path: Path,
    make_app: Callable[..., Path],
    capsys: pytest.CaptureFixture[str],
) -> None:
    application = make_app(tmp_path / "application")
    path_route = application / "app" / "routes" / "path"
    path_route.mkdir()
    (path_route / "__init__.py").write_text("", encoding="ascii")
    (path_route / "route.py").write_text(
        "from pyganini import route\n"
        "def page(request): return None\n"
        "Route = route(page=page)\n",
        encoding="ascii",
    )

    assert main(["routes", "explain", "--app-root", str(application), "/path"]) == 0

    output = capsys.readouterr()
    assert output.err == ""
    assert "route=/path\n" in output.out


def test_routes_explain_accepts_custom_method_and_repeated_option_last_value(
    tmp_path: Path,
    make_app: Callable[..., Path],
    capsys: pytest.CaptureFixture[str],
) -> None:
    application = make_app(tmp_path / "application")
    (application / "app" / "routes" / "route.py").write_text(
        "from pyganini import route\n"
        "def page(request): return None\n"
        "Route = route(page=page)\n",
        encoding="ascii",
    )

    assert (
        main(
            [
                "routes",
                "explain",
                "--app-root",
                str(application),
                "--method",
                "x-custom",
                "/",
            ]
        )
        == 1
    )
    custom = capsys.readouterr()
    assert custom.out == ""
    assert custom.err == (
        "pyganini routes explain: PYGANINI017 route-inspection: method=X-CUSTOM "
        'url_path="/" asgi_path="/" status=405 route=/ method not allowed; '
        "allowed=GET,HEAD error_page=- error_fragment=- root_layouts=[]\n"
    )

    assert (
        main(
            [
                "routes",
                "explain",
                "--app-root",
                str(application),
                "--method",
                "POST",
                "--method",
                " get ",
                "/",
            ]
        )
        == 0
    )
    repeated = capsys.readouterr()
    assert repeated.err == ""
    assert "method=GET\n" in repeated.out
    assert "dispatch_method=GET\n" in repeated.out


def test_routes_explain_renders_exact_fragment_and_action_layout_output(
    tmp_path: Path,
    make_app: Callable[..., Path],
    capsys: pytest.CaptureFixture[str],
) -> None:
    application = make_app(tmp_path / "application")
    routes = application / "app" / "routes"
    users = routes / "users"
    users.mkdir()
    (users / "__init__.py").write_text("", encoding="ascii")
    for directory in (routes, users):
        (directory / "layout.py").write_text("VALUE = 1\n", encoding="ascii")
        (directory / "layout.jinja").write_text("{{ child }}\n", encoding="ascii")
    (users / "route.py").write_text(
        "from pyganini import action, fragment_route, route\n"
        "def table(request): return None\n"
        "def create(request): return None\n"
        "Route = route(\n"
        "    fragments=(fragment_route('/table', table),),\n"
        "    actions=(action('POST', '/create', create),),\n"
        ")\n",
        encoding="ascii",
    )

    assert (
        main(
            [
                "routes",
                "explain",
                "--app-root",
                str(application),
                "/users/table",
            ]
        )
        == 0
    )
    fragment = capsys.readouterr()
    assert fragment.err == ""
    assert fragment.out.startswith(
        "ROUTE EXPLAIN\n"
        'url_path="/users/table"\n'
        'asgi_path="/users/table"\n'
        "method=GET\n"
        "status=matched\n"
        "\n"
        "MATCH\n"
        "kind=fragment\n"
        "methods=GET,HEAD\n"
        "route=/users/table\n"
        "dispatch_method=GET\n"
        "params=[]\n"
        "handler=app.routes.users.route.table\n"
        "source=app/routes/users/route.py:1:1\n"
        "owner=-\n"
        "mount=-\n"
        "source_path=-\n"
        "layouts=[] (not wrapped)\n"
    )
    assert "\nDECLARATION\nkind=route\n" in fragment.out
    assert "\nIMPLEMENTATION\nkind=fragment\n" in fragment.out
    assert "declaration=app/routes/users/route.py:5:16\n" in fragment.out
    assert "page_layouts=[routes/layout.jinja@" in fragment.out

    assert (
        main(
            [
                "routes",
                "explain",
                "--app-root",
                str(application),
                "--method",
                "POST",
                "/users/create",
            ]
        )
        == 0
    )
    action = capsys.readouterr()
    assert action.err == ""
    assert action.out.startswith(
        "ROUTE EXPLAIN\n"
        'url_path="/users/create"\n'
        'asgi_path="/users/create"\n'
        "method=POST\n"
        "status=matched\n"
        "\n"
        "MATCH\n"
        "kind=action\n"
        "methods=POST\n"
        "route=/users/create\n"
        "dispatch_method=POST\n"
        "params=[]\n"
        "handler=app.routes.users.route.create\n"
        "source=app/routes/users/route.py:1:1\n"
        "owner=-\n"
        "mount=-\n"
        "source_path=-\n"
        "layouts=[app/routes/layout.py:1:1 > "
        "app/routes/users/layout.py:1:1] (valid Page results only)\n"
    )
    assert "\nIMPLEMENTATION\nkind=action\n" in action.out
    assert "declaration=app/routes/users/route.py:6:14\n" in action.out
    assert "page_layouts=[routes/layout.jinja@" in action.out
    assert " > routes/users/layout.jinja@" in action.out


def test_routes_explain_projects_multiple_parameters_in_graph_order(
    tmp_path: Path,
    make_app: Callable[..., Path],
    capsys: pytest.CaptureFixture[str],
) -> None:
    application = make_app(tmp_path / "application")
    routes = application / "app" / "routes"
    directories = (
        routes / "teams",
        routes / "teams" / "by_team_id",
        routes / "teams" / "by_team_id" / "users",
        routes / "teams" / "by_team_id" / "users" / "by_user_id",
    )
    for directory in directories:
        directory.mkdir()
        (directory / "__init__.py").write_text("", encoding="ascii")
    (directories[-1] / "route.py").write_text(
        "from pyganini import route\n"
        "def page(request): return None\n"
        "Route = route(page=page)\n",
        encoding="ascii",
    )

    assert (
        main(
            [
                "routes",
                "explain",
                "--app-root",
                str(application),
                "/teams/alpha/users/beta",
            ]
        )
        == 0
    )
    output = capsys.readouterr()
    assert output.err == ""
    assert "route=/teams/{team_id}/users/{user_id}\n" in output.out
    assert 'params=[team_id="alpha", user_id="beta"]\n' in output.out


def test_routes_explain_internal_failures_are_pyl017_without_partial_output(
    tmp_path: Path,
    make_app: Callable[..., Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
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
    arguments = ["routes", "explain", "--app-root", str(application), "/"]

    def assert_failure(message: str) -> None:
        assert main(arguments) == 1
        output = capsys.readouterr()
        assert output.out == ""
        assert output.err == (
            "pyganini routes explain: PYGANINI017 route-inspection: " + message + "\n"
        )
        assert "Traceback" not in output.err

    def fail_grouping(*_: object, **__: object) -> object:
        raise RuntimeError("explain grouping failed")

    with monkeypatch.context() as patch:
        patch.setattr(inspection_module, "_groups", fail_grouping)
        assert_failure("explain grouping failed")

    def fail_matching(*_: object, **__: object) -> object:
        raise RuntimeError("explain matching failed")

    with monkeypatch.context() as patch:
        patch.setattr(PathPriorityRoute, "matches", fail_matching)
        assert_failure("explain matching failed")

    def fail_layouts(*_: object, **__: object) -> object:
        raise RuntimeError("explain layout selection failed")

    with monkeypatch.context() as patch:
        patch.setattr(inspection_module, "_selected_layouts", fail_layouts)
        assert_failure("explain layout selection failed")

    def fail_json(*_: object, **__: object) -> object:
        raise RuntimeError("explain JSON escaping failed")

    with monkeypatch.context() as patch:
        patch.setattr(json, "dumps", fail_json)
        assert_failure("explain JSON escaping failed")

    def non_ascii_json(_: str) -> str:
        return '"' + chr(0xE9) + '"'

    with monkeypatch.context() as patch:
        patch.setattr(
            inspection_module,
            "_json_explain_string",
            non_ascii_json,
        )
        assert main(arguments) == 1
        encoding = capsys.readouterr()
        assert encoding.out == ""
        assert encoding.err.startswith(
            "pyganini routes explain: PYGANINI017 route-inspection: "
            "route explanation is not ASCII:"
        )
        assert encoding.err.endswith("\n")
        assert "Traceback" not in encoding.err


@pytest.mark.parametrize(
    "arguments",
    [
        ("routes", "explain"),
        ("routes", "explain", "/", "extra"),
        ("routes", "explain", "--j", "/"),
        ("routes", "explain", "--m", "GET", "/"),
        ("routes", "explain", "--app-r", "APPLICATION", "/"),
        ("routes", "explain", "--json", "/"),
        ("routes", "explain", "--mount", "directory", "/"),
    ],
)
def test_routes_explain_rejects_unsupported_grammar(
    tmp_path: Path,
    make_app: Callable[..., Path],
    capsys: pytest.CaptureFixture[str],
    arguments: tuple[str, ...],
) -> None:
    application = make_app(tmp_path / "application")
    resolved = [
        str(application) if value == "APPLICATION" else value for value in arguments
    ]
    assert main(resolved) == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert "usage: pyganini" in output.err


def test_routes_layouts_reports_ordinary_chains_and_fragment_boundary(
    tmp_path: Path,
    make_app: Callable[..., Path],
    capsys: pytest.CaptureFixture[str],
) -> None:
    application = make_app(tmp_path / "application")
    routes = application / "app" / "routes"
    (routes / "layout.py").write_text("VALUE = 1\n", encoding="ascii")
    (routes / "layout.jinja").write_text("{{ child }}\n", encoding="ascii")
    (routes / "users").mkdir()
    users = routes / "users"
    (users / "__init__.py").write_text("", encoding="ascii")
    (users / "layout.py").write_text("VALUE = 1\n", encoding="ascii")
    (users / "layout.jinja").write_text("{{ child }}\n", encoding="ascii")
    (users / "route.py").write_text(
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

    assert main(["routes", "layouts", "--app-root", str(application)]) == 0

    output = capsys.readouterr()
    assert output.err == ""
    assert (
        "layout / source=app/routes/layout.py:1:1 owner=- mount=- source_path=-"
        in output.out
    )
    assert (
        "layout /users source=app/routes/users/layout.py:1:1 owner=- mount=- "
        "source_path=-" in output.out
    )
    assert (
        "page GET,HEAD /users source=app/routes/users/route.py:1:1 owner=- "
        "mount=- source_path=- layouts=[app/routes/layout.py:1:1 > "
        "app/routes/users/layout.py:1:1]"
    ) in output.out
    assert (
        "fragment GET,HEAD /users/table source=app/routes/users/route.py:1:1 "
        "owner=- mount=- source_path=- layouts=[] (not wrapped)"
    ) in output.out
    assert (
        "action POST /users/save source=app/routes/users/route.py:1:1 owner=- "
        "mount=- source_path=- layouts=[app/routes/layout.py:1:1 > "
        "app/routes/users/layout.py:1:1] (valid Page results only)"
    ) in output.out


def test_routes_layouts_reports_empty_page_and_action_chains(
    tmp_path: Path,
    make_app: Callable[..., Path],
    capsys: pytest.CaptureFixture[str],
) -> None:
    application = make_app(tmp_path / "application")
    (application / "app" / "routes" / "route.py").write_text(
        "from pyganini import action, route\n"
        "def page(request): return None\n"
        "def save(request): return None\n"
        "Route = route(page=page, actions=(action('POST', '/save', save),))\n",
        encoding="ascii",
    )

    assert main(["routes", "layouts", "--app-root", str(application)]) == 0

    output = capsys.readouterr()
    assert output.err == ""
    assert "page GET,HEAD / source=app/routes/route.py:1:1" in output.out
    assert "layouts=[]\n" in output.out
    assert (
        "action POST /save source=app/routes/route.py:1:1 owner=- mount=- "
        "source_path=- layouts=[] (valid Page results only)"
    ) in output.out


def test_routes_layouts_reports_effective_mounted_layout_and_owner_evidence(
    tmp_path: Path,
    make_app: Callable[..., Path],
    capsys: pytest.CaptureFixture[str],
) -> None:
    application = make_app(tmp_path / "application")
    routes = application / "app" / "routes"
    (routes / "layout.py").write_text("VALUE = 1\n", encoding="ascii")
    (routes / "layout.jinja").write_text("{{ child }}\n", encoding="ascii")
    users = routes / "users"
    users.mkdir()
    (users / "__init__.py").write_text("", encoding="ascii")
    (users / "route.py").write_text(
        "from pyganini import route_mount\n"
        "def create(request): return None\n"
        "Route = route_mount(create=create, mount='directory')\n",
        encoding="ascii",
    )

    mounts = application / "app" / "mounts"
    mounts.mkdir()
    (mounts / "__init__.py").write_text("", encoding="ascii")
    directory = mounts / "directory"
    directory.mkdir()
    (directory / "__init__.py").write_text("", encoding="ascii")
    (directory / "layout.py").write_text("VALUE = 1\n", encoding="ascii")
    (directory / "layout.jinja").write_text("{{ child }}\n", encoding="ascii")
    (directory / "route.py").write_text(
        "from pyganini import kit_fragment_route, route_kit\n"
        "def page(kit, request): return None\n"
        "def table(kit, request): return None\n"
        "Route = route_kit(\n"
        "    page=page, fragments=(kit_fragment_route('/table', table),)\n"
        ")\n",
        encoding="ascii",
    )

    assert main(["routes", "layouts", "--app-root", str(application)]) == 0

    output = capsys.readouterr()
    assert output.err == ""
    assert (
        "layout /users source=app/mounts/directory/layout.py:1:1 "
        "owner=app/routes/users/route.py:1:1 mount=directory source_path=/"
    ) in output.out
    assert (
        "page GET,HEAD /users source=app/mounts/directory/route.py:1:1 "
        "owner=app/routes/users/route.py:1:1 mount=directory source_path=/ "
        "layouts=[app/routes/layout.py:1:1 > app/mounts/directory/layout.py:1:1]"
    ) in output.out
    assert (
        "fragment GET,HEAD /users/table source=app/mounts/directory/route.py:1:1 "
        "owner=app/routes/users/route.py:1:1 mount=directory source_path=/ "
        "layouts=[] (not wrapped)"
    ) in output.out


def test_routes_layouts_is_source_only_and_preserves_raising_application_snapshot(
    tmp_path: Path,
    make_app: Callable[..., Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    application = make_app(tmp_path / "application")
    (application / "app" / "__init__.py").write_text(
        "raise RuntimeError('application module must not be imported')\n",
        encoding="ascii",
    )
    (application / "app" / "routes" / "route.py").write_text(
        "from pyganini import route\n"
        "raise RuntimeError('route module must not be imported')\n"
        "def page(request): return None\n"
        "Route = route(page=page)\n",
        encoding="ascii",
    )
    generated = application / "app" / "_pyganini"
    generated.mkdir()
    (generated / ".pyganini-root").write_bytes(b"unsafe generated state\n")
    for name in ("__init__.py", "asgi.py", "urls.py"):
        (generated / name).write_text(
            "raise RuntimeError('generated module must not be imported')\n",
            encoding="ascii",
        )
    before = _snapshot(application)

    def fail_url_projection(_: object) -> object:
        raise AssertionError("layout inspection must not validate URL helpers")

    monkeypatch.setattr(
        cli_module,
        "_url_helper_projection",
        fail_url_projection,
    )

    assert main(["routes", "layouts", "--app-root", str(application)]) == 0

    output = capsys.readouterr()
    assert output.err == ""
    assert "page GET,HEAD / source=app/routes/route.py:1:1" in output.out
    assert main(["routes", "layouts", "--app-root", str(application)]) == 0
    repeated = capsys.readouterr()
    assert repeated.out == output.out
    assert repeated.err == ""
    assert _snapshot(application) == before


def test_routes_layouts_projection_failure_is_pyl017_without_partial_output(
    tmp_path: Path,
    make_app: Callable[..., Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    application = make_app(tmp_path / "application")
    (application / "app" / "routes" / "route.py").write_text(
        "from pyganini import route\n"
        "def page(request): return None\n"
        "Route = route(page=page)\n",
        encoding="ascii",
    )

    def fail_projection(_: object) -> bytes:
        raise InspectionError("layout projection failed")

    monkeypatch.setattr(
        cli_module,
        "render_layout_map",
        fail_projection,
    )

    assert main(["routes", "layouts", "--app-root", str(application)]) == 1

    output = capsys.readouterr()
    assert output.out == ""
    assert output.err == (
        "pyganini routes layouts: PYGANINI017 route-inspection: "
        "layout projection failed\n"
    )


def test_routes_layouts_output_failure_is_pyl017_without_traceback(
    tmp_path: Path,
    make_app: Callable[..., Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    application = make_app(tmp_path / "application")
    (application / "app" / "routes" / "route.py").write_text(
        "from pyganini import route\n"
        "def page(request): return None\n"
        "Route = route(page=page)\n",
        encoding="ascii",
    )

    class BrokenOutput:
        def write(self, _: str) -> int:
            raise RuntimeError("stdout unavailable")

    monkeypatch.setattr("pyganini._cli.sys.stdout", BrokenOutput())

    assert main(["routes", "layouts", "--app-root", str(application)]) == 1
    output = capsys.readouterr()
    assert output.out == ""
    assert output.err == (
        "pyganini routes layouts: PYGANINI017 route-inspection: stdout unavailable\n"
    )


def test_routes_layouts_graph_failure_precedes_inspection_output(
    tmp_path: Path,
    make_app: Callable[..., Path],
    capsys: pytest.CaptureFixture[str],
) -> None:
    application = make_app(tmp_path / "application")
    (application / "app" / "routes" / "route.py").write_text(
        "from pyganini import route\nRoute = route(page=missing)\n",
        encoding="ascii",
    )

    assert main(["routes", "layouts", "--app-root", str(application)]) == 1

    output = capsys.readouterr()
    assert output.out == ""
    assert "PYGANINI010 route-declaration" in output.err
    assert "LAYOUT MAP" not in output.out


def test_routes_list_json_is_source_only_and_preserves_application_snapshot(
    tmp_path: Path,
    make_app: Callable[..., Path],
    capsys: pytest.CaptureFixture[str],
) -> None:
    application = make_app(tmp_path / "application")
    route_file = application / "app" / "routes" / "route.py"
    route_file.write_text(
        "from pyganini import route\n"
        "raise RuntimeError('route module must not be imported')\n"
        "def page(request): return None\n"
        "Route = route(page=page)\n",
        encoding="ascii",
    )
    generated = application / "app" / "_pyganini"
    generated.mkdir()
    (generated / ".pyganini-root").write_bytes(b"not inspected\n")
    for name in ("__init__.py", "asgi.py", "urls.py"):
        (generated / name).write_text(
            "raise RuntimeError('generated module must not be imported')\n",
            encoding="ascii",
        )
    before = _snapshot(application)

    assert main(["routes", "list", "--app-root", str(application), "--json"]) == 0

    output = capsys.readouterr()
    data = json.loads(output.out)
    assert data["schema"] == "pyganini.routes.v1"
    assert data["routes"][0]["path"] == "/"
    assert data["routes"][0]["helper"] == "urls.root.path"
    assert output.err == ""
    assert _snapshot(application) == before


@pytest.mark.skipif(os.name == "nt", reason="POSIX symlink and permission proof")
@pytest.mark.parametrize(
    "generated_state",
    ["absent", "symlink", "non_directory", "unreadable"],
)
def test_routes_list_ignores_unsafe_generated_state_and_import_hooks(
    tmp_path: Path,
    make_app: Callable[..., Path],
    generated_state: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    application = make_app(tmp_path / "application")
    (application / "app" / "__init__.py").write_text(
        "raise RuntimeError('application module must not be imported')\n",
        encoding="ascii",
    )
    (application / "app" / "routes" / "route.py").write_text(
        "from pyganini import route\n"
        "raise RuntimeError('route module must not be imported')\n"
        "def page(request): return None\n"
        "Route = route(page=page)\n",
        encoding="ascii",
    )
    generated = application / "app" / "_pyganini"
    if generated_state == "symlink":
        target = tmp_path / "generated-target"
        target.mkdir()
        generated.symlink_to(target, target_is_directory=True)
    elif generated_state == "non_directory":
        generated.write_bytes(b"not a directory\n")
    elif generated_state == "unreadable":
        generated.mkdir()
        for name in ("__init__.py", "asgi.py", "urls.py"):
            (generated / name).write_text(
                "raise RuntimeError('generated module must not be imported')\n",
                encoding="ascii",
            )
        generated.chmod(0o000)

    try:
        assert (
            main(
                [
                    "routes",
                    "list",
                    "--app-root",
                    str(application),
                    "--json",
                ]
            )
            == 0
        )
        output = capsys.readouterr()
        assert json.loads(output.out)["routes"][0]["path"] == "/"
        assert output.err == ""
    finally:
        if generated_state == "unreadable":
            generated.chmod(0o700)


def test_routes_list_repeated_renderers_preserve_bytes_and_snapshot(
    tmp_path: Path,
    make_app: Callable[..., Path],
    capsys: pytest.CaptureFixture[str],
) -> None:
    application = make_app(tmp_path / "application")
    (application / "app" / "routes" / "route.py").write_text(
        "from pyganini import route\n"
        "def page(request): return None\n"
        "Route = route(page=page)\n",
        encoding="ascii",
    )
    before = _snapshot(application)

    for json_output in (False, True):
        args = ["routes", "list", "--app-root", str(application)]
        if json_output:
            args.append("--json")
        assert main(args) == 0
        first = capsys.readouterr()
        assert first.err == ""
        assert main(args) == 0
        second = capsys.readouterr()
        assert second.err == ""
        assert second.out == first.out

    assert _snapshot(application) == before


def test_routes_list_unknown_mount_is_successful_empty_json(
    tmp_path: Path,
    make_app: Callable[..., Path],
    capsys: pytest.CaptureFixture[str],
) -> None:
    application = make_app(tmp_path / "application")

    assert (
        main(
            [
                "routes",
                "list",
                "--app-root",
                str(application),
                "--mount",
                "unreferenced_mount",
                "--json",
            ]
        )
        == 0
    )

    output = capsys.readouterr()
    assert output.out == (
        '{\n  "schema": "pyganini.routes.v1",\n  "error_render": {\n'
        '    "page_template": null,\n'
        '    "fragment_template": null,\n'
        '    "root_layouts": []\n'
        "  },\n"
        '  "routes": []\n'
        "}\n"
    )
    assert output.err == ""


def test_routes_list_fallback_root_and_console_module_parity(
    tmp_path: Path, make_app: Callable[..., Path]
) -> None:
    application = make_app(tmp_path / "application")
    nested = application / "app" / "routes" / "nested"
    nested.mkdir()
    (nested / "__init__.py").write_text("", encoding="ascii")
    (application / "app" / "routes" / "route.py").write_text(
        "from pyganini import route\n"
        "def page(request): return None\n"
        "Route = route(page=page)\n",
        encoding="ascii",
    )
    console = Path(sys.executable).parent / "pyganini"
    console_result = subprocess.run(
        [str(console), "routes", "list", "--json", "--json"],
        cwd=nested,
        check=False,
        capture_output=True,
        text=True,
    )
    module_result = subprocess.run(
        [sys.executable, "-m", "pyganini", "routes", "list", "--json"],
        cwd=nested,
        check=False,
        capture_output=True,
        text=True,
    )
    assert console_result.returncode == 0
    assert module_result.returncode == 0
    assert console_result.stdout == module_result.stdout
    assert console_result.stderr == module_result.stderr == ""


def test_routes_list_invalid_mount_is_usage_error_before_root_selection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    selected = False

    def fail_selection(*_: object, **__: object) -> object:
        nonlocal selected
        selected = True
        raise AssertionError("root selection must not run")

    monkeypatch.setattr(cli_module, "select_project_paths", fail_selection)

    assert (
        main(
            [
                "routes",
                "list",
                "--app-root",
                str(tmp_path / "missing"),
                "--mount",
                "../invalid",
            ]
        )
        == 2
    )
    assert not selected
    assert "usage: pyganini" in capsys.readouterr().err


@pytest.mark.parametrize(
    "args",
    [
        ("routes", "list", "--j", "--app-root", "APPLICATION"),
        ("routes", "list", "--m", "directory", "--app-root", "APPLICATION"),
        ("routes", "list", "--app-r", "APPLICATION"),
        ("routes", "layouts", "--json", "--app-root", "APPLICATION"),
        ("routes", "layouts", "--mount", "directory", "--app-root", "APPLICATION"),
        ("routes", "layouts", "--app-r", "APPLICATION"),
        ("routes", "layouts", "extra", "--app-root", "APPLICATION"),
        ("routes", "render-units", "--j", "--app-root", "APPLICATION"),
        ("routes", "render-units", "--app-r", "APPLICATION"),
        ("routes", "render-units", "--json", "--app-root", "APPLICATION", "extra"),
        ("routes", "render-units", "--unknown"),
        ("routes", "list", "--unknown"),
        ("routes", "--json", "list"),
        ("routes",),
        ("routes", "unknown"),
    ],
)
def test_routes_list_rejects_abbreviated_misplaced_and_unknown_arguments(
    tmp_path: Path,
    make_app: Callable[..., Path],
    capsys: pytest.CaptureFixture[str],
    args: tuple[str, ...],
) -> None:
    application = make_app(tmp_path / "application")
    resolved = [str(application) if value == "APPLICATION" else value for value in args]

    assert main(resolved) == 2
    assert "usage: pyganini" in capsys.readouterr().err


@pytest.mark.parametrize(
    "arguments",
    [
        ("--j",),
        ("--app-r", "APPLICATION"),
        ("--json=invalid",),
        ("extra",),
    ],
)
def test_routes_render_units_rejects_invalid_arguments_before_root_selection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    arguments: tuple[str, ...],
) -> None:
    selected = False

    def fail_selection(*_: object, **__: object) -> object:
        nonlocal selected
        selected = True
        raise AssertionError("root selection must not run")

    monkeypatch.setattr(cli_module, "select_project_paths", fail_selection)
    resolved = [
        str(tmp_path / "application") if value == "APPLICATION" else value
        for value in arguments
    ]

    assert main(["routes", "render-units", *resolved]) == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert "usage: pyganini" in output.err
    assert not selected


def test_generate_retains_long_option_abbreviation(
    tmp_path: Path,
    make_app: Callable[..., Path],
    capsys: pytest.CaptureFixture[str],
) -> None:
    application = make_app(tmp_path / "application")

    assert main(["generate", "--app-r", str(application)]) == 0
    assert "written=4" in capsys.readouterr().out


def test_routes_list_graph_and_helper_fail_before_inventory_output(
    tmp_path: Path,
    make_app: Callable[..., Path],
    capsys: pytest.CaptureFixture[str],
) -> None:
    graph_failure = make_app(tmp_path / "graph-failure")
    (graph_failure / "app" / "routes" / "route.py").write_text(
        "from pyganini import route\nRoute = route(page=missing)\n",
        encoding="ascii",
    )
    assert main(["routes", "list", "--app-root", str(graph_failure)]) == 1
    graph_output = capsys.readouterr()
    assert graph_output.out == ""
    assert "PYGANINI010 route-declaration" in graph_output.err

    helper_failure = make_app(tmp_path / "helper-failure")
    path_route = helper_failure / "app" / "routes" / "path"
    path_route.mkdir()
    (path_route / "__init__.py").write_text("", encoding="ascii")
    (path_route / "route.py").write_text(
        "from pyganini import route\n"
        "def page(request): return None\n"
        "Route = route(page=page)\n",
        encoding="ascii",
    )
    assert main(["routes", "list", "--app-root", str(helper_failure)]) == 1
    helper_output = capsys.readouterr()
    assert helper_output.out == ""
    assert "PYGANINI016 url-interface" in helper_output.err


def test_routes_list_output_failure_is_pyl017_without_traceback(
    tmp_path: Path,
    make_app: Callable[..., Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    application = make_app(tmp_path / "application")
    (application / "app" / "routes" / "route.py").write_text(
        "from pyganini import route\n"
        "def page(request): return None\n"
        "Route = route(page=page)\n",
        encoding="ascii",
    )

    class BrokenOutput:
        def write(self, _: str) -> int:
            raise RuntimeError("stdout unavailable")

    monkeypatch.setattr("pyganini._cli.sys.stdout", BrokenOutput())

    assert main(["routes", "list", "--app-root", str(application)]) == 1
    output = capsys.readouterr()
    assert output.out == ""
    assert output.err == (
        "pyganini routes list: PYGANINI017 route-inspection: stdout unavailable\n"
    )


def test_nested_working_directory_uses_fallback_root(
    tmp_path: Path,
    make_app: Callable[..., Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    application = make_app(tmp_path / "application with spaces")
    nested = application / "app" / "routes" / "nested"
    nested.mkdir()
    (nested / "__init__.py").write_text("", encoding="ascii")
    monkeypatch.chdir(nested)
    assert main(["generate"]) == 0
    assert "written=4" in capsys.readouterr().out


def test_explicit_root_does_not_evaluate_cwd(
    tmp_path: Path,
    make_app: Callable[..., Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    application = make_app(tmp_path / "application")

    def fail_cwd() -> Path:
        raise OSError("unused cwd must not be touched")

    monkeypatch.setattr(Path, "cwd", fail_cwd)
    assert main(["generate", "--app-root", str(application)]) == 0


def test_stale_check_reports_sorted_diagnostic(
    tmp_path: Path,
    make_app: Callable[..., Path],
    capsys: pytest.CaptureFixture[str],
) -> None:
    application = make_app(tmp_path / "application")
    assert main(["check", "--app-root", str(application)]) == 1
    output = capsys.readouterr()
    assert output.out == ""
    assert output.err == (
        "app/_pyganini: PYGANINI005 generated-state: generated directory is missing; "
        "run pyganini generate\n"
    )


@pytest.mark.parametrize(
    ("args", "code"),
    [
        ([], 2),
        (["unknown"], 2),
        (["--app-root", "somewhere", "check"], 2),
    ],
)
def test_usage_errors_return_two(
    args: list[str], code: int, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(args) == code
    assert "usage: pyganini" in capsys.readouterr().err


def test_help_and_version_match_for_console_and_module() -> None:
    console = Path(sys.executable).parent / "pyganini"
    help_result = subprocess.run(
        [str(console), "--help"],
        check=False,
        capture_output=True,
        text=True,
    )
    module_version = subprocess.run(
        [sys.executable, "-m", "pyganini", "--version"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert help_result.returncode == 0
    normalized_help = " ".join(help_result.stdout.split())
    assert "app/_pyganini/.pyganini-root" in normalized_help
    assert "app/_pyganini/urls.py" in normalized_help
    assert "Validate app/routes" in normalized_help
    assert "check performs no application writes" in normalized_help
    assert module_version.returncode == 0
    assert module_version.stdout == "pyganini 0.1.1\n"


def test_root_and_configuration_diagnostics_use_stable_codes(
    tmp_path: Path,
    make_app: Callable[..., Path],
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["check", "--app-root", str(tmp_path / "missing")]) == 1
    assert "PYGANINI002 root-selection" in capsys.readouterr().err

    unmarked = tmp_path / "unmarked"
    unmarked.mkdir()
    assert main(["check", "--app-root", str(unmarked)]) == 1
    assert "PYGANINI003 configuration" in capsys.readouterr().err

    malformed = make_app(tmp_path / "malformed", config="[tool.pyganini\n")
    assert main(["check", "--app-root", str(malformed)]) == 1
    assert "PYGANINI003 configuration" in capsys.readouterr().err

    invalid_layout = make_app(tmp_path / "invalid", routes=False)
    assert main(["check", "--app-root", str(invalid_layout)]) == 1
    assert "PYGANINI004 project-layout" in capsys.readouterr().err


@pytest.mark.parametrize("command", ["generate", "check"])
def test_route_graph_failure_precedes_generated_state_work(
    tmp_path: Path,
    make_app: Callable[..., Path],
    capsys: pytest.CaptureFixture[str],
    command: str,
) -> None:
    application = make_app(tmp_path / "application")
    route_file = application / "app" / "routes" / "route.py"
    route_file.write_text(
        "from pyganini import route\nRoute = route(page=missing)\n",
        encoding="ascii",
    )
    before = tuple(
        (path.relative_to(application).as_posix(), path.stat().st_mtime_ns)
        for path in sorted(application.rglob("*"))
    )

    assert main([command, "--app-root", str(application)]) == 1
    output = capsys.readouterr()
    assert output.out == ""
    assert "app/routes/route.py:2:" in output.err
    assert "PYGANINI010 route-declaration" in output.err
    assert "page: missing handler symbol 'missing'" in output.err
    assert not (application / "app" / "_pyganini").exists()
    after = tuple(
        (path.relative_to(application).as_posix(), path.stat().st_mtime_ns)
        for path in sorted(application.rglob("*"))
    )
    assert after == before


def test_check_with_route_source_preserves_recursive_snapshot(
    tmp_path: Path,
    make_app: Callable[..., Path],
    capsys: pytest.CaptureFixture[str],
) -> None:
    application = make_app(tmp_path / "application")
    (application / "app" / "routes" / "route.py").write_text(
        "from pyganini import route\n"
        "def page(): return None\n"
        "Route = route(page=page)\n",
        encoding="ascii",
    )
    assert main(["generate", "--app-root", str(application)]) == 0
    capsys.readouterr()
    before = _snapshot(application)

    assert main(["check", "--app-root", str(application)]) == 0
    assert capsys.readouterr().out == "Pyganini generated state is current.\n"
    assert _snapshot(application) == before


@pytest.mark.parametrize("command", ["generate", "check"])
def test_required_template_validation_precedes_generated_state_work(
    tmp_path: Path,
    make_app: Callable[..., Path],
    capsys: pytest.CaptureFixture[str],
    command: str,
) -> None:
    application = make_app(tmp_path / "application")
    assert main(["generate", "--app-root", str(application)]) == 0
    capsys.readouterr()
    (application / "app" / "routes" / "route.py").write_text(
        "from pyganini import route\n"
        "def page(request): return request\n"
        "Route = route(page=page, template='missing.jinja')\n",
        encoding="ascii",
    )
    before = _snapshot(application)

    assert main([command, "--app-root", str(application)]) == 1
    output = capsys.readouterr()
    assert output.out == ""
    assert "app/routes/missing.jinja: PYGANINI009 route-filesystem" in output.err
    assert "required template" in output.err
    assert _snapshot(application) == before


@pytest.mark.skipif(os.name == "nt", reason="POSIX descriptor regression")
@pytest.mark.parametrize("command", ["generate", "check"])
def test_unreadable_shared_package_marker_precedes_generated_state_work(
    tmp_path: Path,
    make_app: Callable[..., Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    command: str,
) -> None:
    application = make_app(tmp_path / "application")
    shared = application / "app" / "shared" / "reports"
    shared.mkdir(parents=True)
    (application / "app" / "shared" / "__init__.py").write_text("", encoding="ascii")
    (shared / "__init__.py").write_text("", encoding="ascii")
    (shared / "page.jinja").write_text("<main>{{ title }}</main>", encoding="ascii")
    users = application / "app" / "routes" / "users"
    users.mkdir()
    (users / "__init__.py").write_text("", encoding="ascii")
    (users / "route.py").write_text(
        "from pyganini import route_kit\n"
        "import app.shared.reports as reports\n"
        "def create(request): return reports.Kit()\n"
        "Route = route_kit(\n"
        "    create=create,\n"
        "    template_root='shared/reports',\n"
        "    page=reports.page,\n"
        "    template='page.jinja',\n"
        ")\n",
        encoding="ascii",
    )
    assert main(["generate", "--app-root", str(application)]) == 0
    capsys.readouterr()

    real_read_regular = route_graph_module._PosixRouteDirectory.read_regular

    def deny_shared_marker(self: object, name: str) -> bytes:
        directory = cast(route_graph_module._PosixRouteDirectory, self)
        if directory.path == shared and name == "__init__.py":
            raise PermissionError("shared marker read denied")
        return real_read_regular(directory, name)

    monkeypatch.setattr(
        route_graph_module._PosixRouteDirectory,
        "read_regular",
        deny_shared_marker,
    )

    def fail_generated_state(*_: object, **__: object) -> object:
        raise AssertionError("generated state must not be accessed")

    monkeypatch.setattr(cli_module, "generate", fail_generated_state)
    monkeypatch.setattr(cli_module, "check_generated_state", fail_generated_state)

    assert main([command, "--app-root", str(application)]) == 1
    output = capsys.readouterr()
    assert output.out == ""
    assert "app/shared/reports/__init__.py: PYGANINI009 route-filesystem" in output.err
    assert "cannot read shared template package marker" in output.err
    assert "shared marker read denied" in output.err


@pytest.mark.skipif(os.name == "nt", reason="POSIX descriptor regression")
@pytest.mark.parametrize("command", ["generate", "check"])
def test_unreadable_mounted_descendant_marker_precedes_generated_state_work(
    tmp_path: Path,
    make_app: Callable[..., Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    command: str,
) -> None:
    application = make_app(tmp_path / "application")
    mounts = application / "app" / "mounts"
    mounted = mounts / "directory"
    descendant = mounted / "create"
    descendant.mkdir(parents=True)
    for package in (mounts, mounted, descendant):
        (package / "__init__.py").write_text("", encoding="ascii")
    (mounted / "route.py").write_text(
        "from pyganini import route_kit\n"
        "def page(kit, request): return kit\n"
        "Route = route_kit(page=page)\n",
        encoding="ascii",
    )
    (descendant / "route.py").write_text(
        "from pyganini import kit_action, route_kit\n"
        "def save(kit, request): return kit\n"
        "Route = route_kit(actions=(kit_action('POST', '/', save),))\n",
        encoding="ascii",
    )
    owner = application / "app" / "routes" / "users"
    owner.mkdir()
    (owner / "__init__.py").write_text("", encoding="ascii")
    (owner / "route.py").write_text(
        "from pyganini import route_mount\n"
        "def create(request): return object()\n"
        "Route = route_mount(create=create, mount='directory')\n",
        encoding="ascii",
    )
    assert main(["generate", "--app-root", str(application)]) == 0
    capsys.readouterr()

    real_read_regular = route_graph_module._PosixRouteDirectory.read_regular

    def deny_descendant_marker(self: object, name: str) -> bytes:
        directory = cast(route_graph_module._PosixRouteDirectory, self)
        if directory.path == descendant and name == "__init__.py":
            raise PermissionError("mounted descendant marker read denied")
        return real_read_regular(directory, name)

    monkeypatch.setattr(
        route_graph_module._PosixRouteDirectory,
        "read_regular",
        deny_descendant_marker,
    )

    def fail_generated_state(*_: object, **__: object) -> object:
        raise AssertionError("generated state must not be accessed")

    monkeypatch.setattr(cli_module, "generate", fail_generated_state)
    monkeypatch.setattr(cli_module, "check_generated_state", fail_generated_state)

    assert main([command, "--app-root", str(application)]) == 1
    output = capsys.readouterr()
    assert output.out == ""
    assert "app/mounts/directory/create/__init__.py" in output.err
    assert "PYGANINI009 route-filesystem" in output.err
    assert "cannot read mounted source package marker" in output.err
    assert "mounted descendant marker read denied" in output.err
