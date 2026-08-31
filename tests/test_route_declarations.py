import importlib
import os
import subprocess
import sys
from collections.abc import Callable
from dataclasses import FrozenInstanceError, fields
from pathlib import Path
from typing import Any, cast, get_type_hints

import pytest
from starlette.responses import Response

import pyganini
from pyganini import (
    ActionDef,
    FragmentResponse,
    FragmentRouteDef,
    KitActionDef,
    KitFragmentRouteDef,
    KitRouteDef,
    KitRouteMount,
    MountRoute,
    Page,
    RouteDef,
    RouteMeta,
    action,
    fragment_route,
    hx,
    kit_action,
    kit_fragment_route,
    mount_route,
    route,
    route_kit,
    route_mount,
)


def handler() -> object:
    return object()


def other_handler() -> object:
    return object()


def create_kit(request: object) -> str:
    return "kit"


def create_mount(request: object) -> str:
    return "mount"


def kit_page(kit: str, request: object) -> Page:
    return Page()


def kit_table(kit: str, request: object) -> FragmentResponse:
    return FragmentResponse()


def kit_save(kit: str, request: object) -> Response:
    return Response()


def test_public_declaration_values_are_frozen_slotted_and_normalized() -> None:
    declared_fragment = fragment_route("/user_table", handler, template="table.jinja")
    declared_action = action("POST", "/save_user", other_handler, template="form.jinja")
    declared_route = route(
        page=handler,
        template="page.jinja",
        fragments=(declared_fragment,),
        actions=(declared_action,),
    )

    assert declared_fragment == FragmentRouteDef("/user-table", handler, "table.jinja")
    assert declared_action == ActionDef(
        "POST", "/save-user", other_handler, "form.jinja"
    )
    assert declared_route == RouteDef(
        handler, "page.jinja", (declared_fragment,), (declared_action,)
    )
    assert not hasattr(declared_route, "__dict__")
    with pytest.raises(FrozenInstanceError):
        declared_fragment.path = "/changed"  # type: ignore[misc]


def test_route_metadata_is_immutable_copied_sorted_and_display_only() -> None:
    labels = {"zeta": "last", "alpha": "first"}
    meta = RouteMeta(labels=labels)
    declaration = route(
        page=handler,
        name="users.index",
        title="Users",
        meta=meta,
    )

    labels["alpha"] = "changed"

    assert list(meta.labels.items()) == [
        ("alpha", "first"),
        ("zeta", "last"),
    ]
    assert declaration.name == "users.index"
    assert declaration.title == "Users"
    assert declaration.meta is meta
    assert not hasattr(meta, "__dict__")
    assert RouteMeta.__doc__
    assert [field.name for field in fields(RouteDef)][-3:] == [
        "name",
        "title",
        "meta",
    ]
    with pytest.raises(TypeError):
        meta.labels["new"] = "value"  # type: ignore[index]
    with pytest.raises(FrozenInstanceError):
        meta.labels = {}  # type: ignore[misc]


def test_route_metadata_runtime_validation_fails_closed() -> None:
    with pytest.raises(TypeError, match="labels must be a mapping"):
        RouteMeta(labels=cast(Any, []))
    with pytest.raises(TypeError, match="keys and values must be strings"):
        RouteMeta(labels=cast(Any, {1: "value"}))
    with pytest.raises(TypeError, match="keys and values must be strings"):
        RouteMeta(labels=cast(Any, {"key": 1}))
    with pytest.raises(ValueError, match="label keys must not be empty"):
        RouteMeta(labels={"": "value"})
    with pytest.raises(TypeError, match="name must be a string or None"):
        route(page=handler, name=cast(Any, 1))
    with pytest.raises(TypeError, match="title must be a string or None"):
        route(page=handler, title=cast(Any, 1))
    with pytest.raises(TypeError, match="meta must be a RouteMeta value or None"):
        route(page=handler, meta=cast(Any, {}))
    with pytest.raises(ValueError, match="name must not be empty"):
        route(page=handler, name="")
    with pytest.raises(ValueError, match="title must not be empty"):
        route_kit(page=kit_page, title="")
    with pytest.raises(ValueError, match="metadata requires"):
        route(error_page_template="error_page.jinja", name="errors")
    with pytest.raises(ValueError, match="metadata requires"):
        route(meta=RouteMeta())


@pytest.mark.parametrize("checker", ["mypy", "pyright"])
def test_route_metadata_public_typing_accepts_valid_and_rejects_invalid_values(
    tmp_path: Path, checker: str
) -> None:
    application = tmp_path / "typing"
    application.mkdir()
    sample = application / "sample.py"
    sample.write_text(
        "from pyganini import Page, RouteMeta, route, route_kit\n"
        "def page(request: object) -> object: return object()\n"
        "def kit_page(kit: str, request: object) -> Page: return Page()\n"
        "valid = route(page=page, name='users', title='Users', "
        "meta=RouteMeta(labels={'area': 'admin'}))\n"
        "valid_kit = route_kit(page=kit_page, meta=RouteMeta())\n",
        encoding="ascii",
    )
    valid_result = _run_kit_checker(checker, application, sample)
    assert valid_result.returncode == 0, valid_result.stdout + valid_result.stderr

    sample.write_text(
        "from pyganini import RouteMeta, route\n"
        "def page(request: object) -> object: return object()\n"
        "bad_labels = RouteMeta(labels={'area': 1})\n"
        "bad_name = route(page=page, name=1)\n",
        encoding="ascii",
    )
    invalid_result = _run_kit_checker(checker, application, sample)
    assert invalid_result.returncode != 0


def test_live_root_declarations_retain_static_error_templates() -> None:
    ordinary = route(
        error_page_template="error_page.jinja",
        error_fragment_template="error_fragment.jinja",
    )
    kit = route_kit(
        create=create_kit,
        page=kit_page,
        error_page_template="error_page.jinja",
        error_fragment_template="error_fragment.jinja",
    )
    mounted = route_mount(
        create=create_mount,
        mount="contact_directory",
        error_page_template="error_page.jinja",
        error_fragment_template="error_fragment.jinja",
    )

    assert ordinary.error_page_template == "error_page.jinja"
    assert ordinary.error_fragment_template == "error_fragment.jinja"
    assert kit.error_page_template == "error_page.jinja"
    assert kit.error_fragment_template == "error_fragment.jinja"
    assert mounted.error_page_template == "error_page.jinja"
    assert mounted.error_fragment_template == "error_fragment.jinja"
    assert [field.name for field in fields(RouteDef)][-5:-3] == [
        "error_page_template",
        "error_fragment_template",
    ]


def test_direct_declaration_values_enforce_normalized_structure() -> None:
    assert FragmentRouteDef("/user_table", handler).path == "/user-table"
    assert ActionDef("POST", "/save_user", handler).path == "/save-user"

    with pytest.raises(ValueError, match="start with"):
        FragmentRouteDef("users", handler)
    with pytest.raises(ValueError, match="POST, PUT, PATCH, or DELETE"):
        ActionDef("GET", "/save", handler)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="one segment"):
        ActionDef("POST", "/users/save", handler)
    with pytest.raises(ValueError, match="page, fragment, or action"):
        RouteDef(None, None, (), ())


def test_route_kit_declaration_values_are_generic_frozen_and_normalized() -> None:
    declared_fragment = kit_fragment_route(
        "/user_table", kit_table, template="table.jinja"
    )
    declared_action = kit_action("POST", "/save_user", kit_save, template="form.jinja")
    declared_route = route_kit(
        create=create_kit,
        template_root="shared/reports",
        page=kit_page,
        template="page.jinja",
        fragments=(declared_fragment,),
        actions=(declared_action,),
    )

    assert declared_fragment == KitFragmentRouteDef(
        "/user-table", kit_table, "table.jinja"
    )
    assert declared_action == KitActionDef("POST", "/save-user", kit_save, "form.jinja")
    assert declared_route == KitRouteDef(
        create_kit,
        "shared/reports",
        kit_page,
        "page.jinja",
        (declared_fragment,),
        (declared_action,),
    )
    assert not hasattr(declared_route, "__dict__")
    with pytest.raises(FrozenInstanceError):
        declared_route.template_root = "changed"  # type: ignore[misc]


def test_mount_declaration_values_are_frozen_and_creator_free_sources_are_valid() -> (
    None
):
    selected = (mount_route("/user-table"), mount_route("/{contact_id}"))
    declaration = route_mount(
        create=create_mount,
        mount="contact_directory",
        routes=selected,
    )
    source = route_kit(page=kit_page, template="page.jinja")

    assert selected == (MountRoute("/user-table"), MountRoute("/{contact_id}"))
    assert declaration == KitRouteMount(create_mount, "contact_directory", selected)
    assert source == KitRouteDef(None, None, kit_page, "page.jinja", (), ())
    assert not hasattr(declaration, "__dict__")
    with pytest.raises(FrozenInstanceError):
        declaration.mount = "changed"  # type: ignore[misc]


def test_mount_declaration_values_normalize_and_reject_invalid_values() -> None:
    with pytest.raises(ValueError):
        mount_route("/user_table/")
    with pytest.raises(ValueError):
        mount_route("/users//list")
    with pytest.raises(TypeError):
        route_mount(create=create_mount, mount="contact_directory", routes=[])  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        route_mount(create=create_mount, mount="contact-directory")


@pytest.mark.parametrize(
    "template_root",
    [
        "",
        "/shared/reports",
        "shared/reports/",
        "shared//reports",
        "shared\\reports",
        "routes/reports",
        "_shared/reports",
        "shared/_reports",
        "shared/../reports",
        "shared/r" + chr(233),
    ],
)
def test_route_kit_template_roots_fail_closed(template_root: str) -> None:
    with pytest.raises((TypeError, ValueError), match="template_root"):
        route_kit(create=create_kit, template_root=template_root, page=kit_page)


def test_route_kit_template_root_pairing_and_surface_rules_fail_closed() -> None:
    source_route = route_kit(page=kit_page, template="page.jinja")
    assert source_route.template_root is None
    with pytest.raises(ValueError, match="template_root"):
        route_kit(create=create_kit, template_root="shared/reports", page=kit_page)
    with pytest.raises(ValueError, match="page template requires"):
        route_kit(
            create=create_kit,
            template_root="shared/reports",
            template="page.jinja",
            actions=(kit_action("POST", "/save", kit_save),),
        )
    with pytest.raises(ValueError, match="page, fragment, or action"):
        route_kit(create=create_kit)


def _run_kit_checker(
    checker: str, application: Path, sample: Path
) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    if checker == "pyright":
        (application / "pyrightconfig.json").write_text(
            '{"typeCheckingMode": "strict", "include": ["sample.py"]}\n',
            encoding="ascii",
        )
        command = [str(Path(sys.executable).parent / "pyright"), str(sample)]
    else:
        command = [
            sys.executable,
            "-m",
            "mypy",
            "--strict",
            "--python-version",
            "3.13",
            str(sample),
        ]
    return subprocess.run(
        command,
        cwd=application,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )


@pytest.mark.parametrize("checker", ["mypy", "pyright"])
def test_route_kit_generic_relationship_passes_and_rejects_cross_kit_handlers(
    tmp_path: Path, checker: str
) -> None:
    application = tmp_path / "typing"
    application.mkdir()
    valid = application / "sample.py"
    valid.write_text(
        "from pyganini import FragmentResponse, Page, kit_fragment_route, route_kit\n"
        "from starlette.requests import Request\n"
        "from starlette.responses import Response\n"
        "class ReportsKit: pass\n"
        "async def create(request: Request) -> ReportsKit:\n"
        "    return ReportsKit()\n"
        "def page(kit: ReportsKit, request: Request) -> Page:\n"
        "    return Page()\n"
        "async def table(kit: ReportsKit, request: Request) -> FragmentResponse:\n"
        "    return FragmentResponse()\n"
        "def save(kit: ReportsKit, request: Request) -> Response:\n"
        "    return Response()\n"
        "Route = route_kit(\n"
        "    create=create,\n"
        "    template_root='shared/reports',\n"
        "    page=page,\n"
        "    template='page.jinja',\n"
        "    fragments=(kit_fragment_route(\n"
        "        '/table', table, template='table.jinja'),\n"
        "    ),\n"
        "    actions=(),\n"
        ")\n",
        encoding="ascii",
    )
    valid_result = _run_kit_checker(checker, application, valid)
    assert valid_result.returncode == 0, valid_result.stdout + valid_result.stderr

    invalid = application / "sample.py"
    invalid.write_text(
        "from pyganini import KitRouteDef, Page, route_kit\n"
        "from starlette.requests import Request\n"
        "class ReportsKit: pass\n"
        "class OtherKit: pass\n"
        "def create(request: Request) -> ReportsKit:\n"
        "    return ReportsKit()\n"
        "def wrong_page(kit: OtherKit, request: Request) -> Page:\n"
        "    return Page()\n"
        "Route: KitRouteDef[ReportsKit] = route_kit(\n"
        "    create=create, page=wrong_page\n"
        ")\n",
        encoding="ascii",
    )
    invalid_result = _run_kit_checker(checker, application, invalid)
    assert invalid_result.returncode != 0
    diagnostic = invalid_result.stdout + invalid_result.stderr
    assert any(
        marker in diagnostic
        for marker in ("wrong_page", "not assignable", "incompatible type")
    )


@pytest.mark.parametrize("checker", ["mypy", "pyright"])
def test_kit_action_request_data_overloads_accept_sync_and_async_handlers(
    tmp_path: Path, checker: str
) -> None:
    application = tmp_path / "typing"
    application.mkdir()
    valid = application / "sample.py"
    valid.write_text(
        "from pyganini import route_kit, kit_action\n"
        "from pyganini.request_data import Body, Form, capture_body, capture_form\n"
        "from starlette.requests import Request\n"
        "from starlette.responses import Response\n"
        "class ReportsKit: pass\n"
        "def plain(kit: ReportsKit, request: Request) -> Response:\n"
        "    return Response()\n"
        "def body(kit: ReportsKit, request: Request, data: Body) -> Response:\n"
        "    return Response(data.content)\n"
        "def form(kit: ReportsKit, request: Request, data: Form) -> Response:\n"
        "    return Response(','.join(data.values('name')))\n"
        "async def async_body(\n"
        "    kit: ReportsKit, request: Request, data: Body\n"
        ") -> Response:\n"
        "    return Response(data.content)\n"
        "async def async_form(\n"
        "    kit: ReportsKit, request: Request, data: Form\n"
        ") -> Response:\n"
        "    return Response(','.join(data.values('name')))\n"
        "Route = route_kit(actions=(\n"
        "    kit_action('POST', '/plain', plain),\n"
        "    kit_action('POST', '/body', body, "
        "request_data=capture_body(max_bytes=8)),\n"
        "    kit_action('POST', '/form', form, request_data=capture_form(\n"
        "        max_files=1, max_fields=4, max_part_size=64, max_upload_size=128)),\n"
        "    kit_action('POST', '/async-body', async_body, "
        "request_data=capture_body(max_bytes=8)),\n"
        "    kit_action('POST', '/async-form', async_form, request_data=capture_form(\n"
        "        max_files=1, max_fields=4, max_part_size=64, max_upload_size=128)),\n"
        "))\n",
        encoding="ascii",
    )
    valid_result = _run_kit_checker(checker, application, valid)
    assert valid_result.returncode == 0, valid_result.stdout + valid_result.stderr


@pytest.mark.parametrize("checker", ["mypy", "pyright"])
def test_direct_kit_action_definition_handler_typing_is_correlated(
    tmp_path: Path, checker: str
) -> None:
    application = tmp_path / "typing"
    application.mkdir()
    valid = application / "sample.py"
    valid.write_text(
        "from pyganini import KitActionDef\n"
        "from pyganini.request_data import Body, BodyCapture, Form, FormCapture\n"
        "from starlette.requests import Request\n"
        "from starlette.responses import Response\n"
        "class ReportsKit: pass\n"
        "def plain(kit: ReportsKit, request: Request) -> Response:\n"
        "    return Response()\n"
        "async def async_plain(kit: ReportsKit, request: Request) -> Response:\n"
        "    return Response()\n"
        "def body(kit: ReportsKit, request: Request, data: Body) -> Response:\n"
        "    return Response(data.content)\n"
        "def form(kit: ReportsKit, request: Request, data: Form) -> Response:\n"
        "    return Response(','.join(data.values('name')))\n"
        "async def async_body(\n"
        "    kit: ReportsKit, request: Request, data: Body\n"
        ") -> Response:\n"
        "    return Response(data.content)\n"
        "async def async_form(\n"
        "    kit: ReportsKit, request: Request, data: Form\n"
        ") -> Response:\n"
        "    return Response(','.join(data.values('name')))\n"
        "plain_def: KitActionDef[ReportsKit] = KitActionDef(\n"
        "    'POST', '/plain', plain)\n"
        "async_plain_def: KitActionDef[ReportsKit] = KitActionDef(\n"
        "    'POST', '/async-plain', async_plain)\n"
        "body_def: KitActionDef[ReportsKit] = KitActionDef(\n"
        "    'POST', '/body', body, request_data=BodyCapture(max_bytes=8))\n"
        "form_def: KitActionDef[ReportsKit] = KitActionDef(\n"
        "    'POST', '/form', form, request_data=FormCapture(\n"
        "        max_files=1, max_fields=4, max_part_size=64, max_upload_size=128))\n"
        "async_body_def: KitActionDef[ReportsKit] = KitActionDef(\n"
        "    'POST', '/async-body', async_body,\n"
        "    request_data=BodyCapture(max_bytes=8))\n"
        "async_form_def: KitActionDef[ReportsKit] = KitActionDef(\n"
        "    'POST', '/async-form', async_form, request_data=FormCapture(\n"
        "        max_files=1, max_fields=4, max_part_size=64, max_upload_size=128))\n",
        encoding="ascii",
    )
    valid_result = _run_kit_checker(checker, application, valid)
    assert valid_result.returncode == 0, valid_result.stdout + valid_result.stderr


@pytest.mark.parametrize("checker", ["mypy", "pyright"])
@pytest.mark.parametrize(
    "declaration",
    [
        "KitActionDef[ReportsKit](\n"
        "    'POST', '/wrong-body', form_handler,\n"
        "    request_data=BodyCapture(max_bytes=8))",
        "KitActionDef[ReportsKit](\n"
        "    'POST', '/wrong-form', body_handler,\n"
        "    request_data=FormCapture(\n"
        "        max_files=1, max_fields=4, max_part_size=64, max_upload_size=128))",
        "KitActionDef[ReportsKit]('POST', '/body-without-capture', body_handler)",
        "KitActionDef[ReportsKit]('POST', '/form-without-capture', form_handler)",
    ],
)
def test_direct_kit_action_definition_rejects_uncorrelated_capture(
    tmp_path: Path, checker: str, declaration: str
) -> None:
    application = tmp_path / "typing"
    application.mkdir()
    sample = application / "sample.py"
    sample.write_text(
        "from pyganini import KitActionDef\n"
        "from pyganini.request_data import Body, BodyCapture, Form, FormCapture\n"
        "from starlette.requests import Request\n"
        "from starlette.responses import Response\n"
        "class ReportsKit: pass\n"
        "def body_handler(kit: ReportsKit, request: Request, data: Body) -> Response:\n"
        "    return Response()\n"
        "def form_handler(kit: ReportsKit, request: Request, data: Form) -> Response:\n"
        "    return Response()\n"
        f"invalid: KitActionDef[ReportsKit] = {declaration}\n",
        encoding="ascii",
    )

    result = _run_kit_checker(checker, application, sample)
    assert result.returncode != 0, result.stdout + result.stderr


@pytest.mark.parametrize("checker", ["mypy", "pyright"])
@pytest.mark.parametrize(
    "declaration",
    [
        "KitActionDef[ReportsKit](\n    'POST', '/wrong-kit', wrong_kit)",
        "KitActionDef[ReportsKit](\n    'POST', '/wrong-arity', wrong_arity)",
    ],
)
def test_direct_kit_action_definition_rejects_invalid_handler_independently(
    tmp_path: Path, checker: str, declaration: str
) -> None:
    application = tmp_path / "typing"
    application.mkdir()
    sample = application / "sample.py"
    sample.write_text(
        "from pyganini import KitActionDef\n"
        "from pyganini.request_data import Body, BodyCapture\n"
        "from starlette.requests import Request\n"
        "from starlette.responses import Response\n"
        "class ReportsKit: pass\n"
        "class OtherKit: pass\n"
        "def wrong_kit(kit: OtherKit, request: Request) -> Response:\n"
        "    return Response()\n"
        "def wrong_arity(\n"
        "    kit: ReportsKit, request: Request, data: Body, extra: str\n"
        ") -> Response:\n"
        "    return Response()\n"
        f"invalid: KitActionDef[ReportsKit] = {declaration}\n",
        encoding="ascii",
    )

    result = _run_kit_checker(checker, application, sample)
    assert result.returncode != 0, result.stdout + result.stderr


@pytest.mark.parametrize("checker", ["mypy", "pyright"])
def test_action_request_data_typing_correlates_capture_and_callable_mode(
    tmp_path: Path, checker: str
) -> None:
    application = tmp_path / "typing"
    application.mkdir()
    sample = application / "sample.py"
    sample.write_text(
        "from pyganini import ActionDef, action\n"
        "from pyganini.request_data import Body, BodyCapture, Form, capture_form\n"
        "from starlette.requests import Request\n"
        "from starlette.responses import Response\n"
        "def plain(request: Request) -> Response: return Response()\n"
        "async def body(request: Request, data: Body) -> Response:\n"
        "    return Response(data.content)\n"
        "async def form(request: Request, data: Form) -> Response:\n"
        "    return Response(','.join(data.values('name')))\n"
        "plain_def = action('POST', '/plain', plain)\n"
        "body_def: ActionDef = ActionDef(\n"
        "    'POST', '/body', body, request_data=BodyCapture(max_bytes=8))\n"
        "form_def = action('POST', '/form', form, request_data=capture_form(\n"
        "    max_files=1, max_fields=4, max_part_size=64, max_upload_size=128))\n",
        encoding="ascii",
    )

    result = _run_kit_checker(checker, application, sample)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("checker", ["mypy", "pyright"])
@pytest.mark.parametrize(
    "declaration",
    [
        "ActionDef('POST', '/wrong-body', form, request_data=BodyCapture(max_bytes=8))",
        "action('POST', '/body-without-capture', body)",
        "action('POST', '/missing-payload', plain, "
        "request_data=BodyCapture(max_bytes=8))",
    ],
)
def test_action_request_data_typing_rejects_uncorrelated_handlers(
    tmp_path: Path, checker: str, declaration: str
) -> None:
    application = tmp_path / "typing"
    application.mkdir()
    sample = application / "sample.py"
    sample.write_text(
        "from pyganini import ActionDef, action\n"
        "from pyganini.request_data import Body, BodyCapture, Form\n"
        "from starlette.requests import Request\n"
        "from starlette.responses import Response\n"
        "def plain(request: Request) -> Response: return Response()\n"
        "def body(request: Request, data: Body) -> Response: return Response()\n"
        "def form(request: Request, data: Form) -> Response: return Response()\n"
        f"invalid = {declaration}\n",
        encoding="ascii",
    )

    result = _run_kit_checker(checker, application, sample)
    assert result.returncode != 0, result.stdout + result.stderr


@pytest.mark.parametrize(
    "template",
    [
        "",
        "Page.jinja",
        "page.html",
        "page-name.jinja",
        "page.jinja/child",
        "../page.jinja",
        "page\\name.jinja",
        "page name.jinja",
        "page." + chr(233) + ".jinja",
    ],
)
def test_template_names_fail_closed(template: str) -> None:
    with pytest.raises(ValueError, match="template"):
        route(page=handler, template=template)
    with pytest.raises(ValueError, match="template"):
        fragment_route("/table", handler, template=template)
    with pytest.raises(ValueError, match="template"):
        action("POST", "/save", handler, template=template)
    with pytest.raises(ValueError, match="template"):
        route(error_page_template=template)
    with pytest.raises(ValueError, match="template"):
        route(error_fragment_template=template)


def test_template_types_and_page_pairing_fail_closed() -> None:
    with pytest.raises(TypeError, match="template must be a string or None"):
        route(page=handler, template=cast(Any, 1))
    with pytest.raises(TypeError, match="template must be a string or None"):
        route(error_page_template=cast(Any, 1))
    with pytest.raises(ValueError, match="page template requires a page handler"):
        route(template="page.jinja", actions=(action("POST", "/save", handler),))


@pytest.mark.parametrize(
    "path",
    [
        "",
        "users",
        "/users/",
        "/users/list",
        "/{user_id}",
        "/users.json",
        "/users%20list",
        "/users?active",
        "/users#active",
        "/Users",
        "/123",
    ],
)
def test_route_local_paths_fail_closed(path: str) -> None:
    with pytest.raises(ValueError):
        fragment_route(path, handler)


def test_route_local_paths_reject_non_ascii_text() -> None:
    with pytest.raises(ValueError, match="ASCII"):
        fragment_route("/utilisateur_" + chr(233), handler)


def test_route_local_path_and_method_types_fail_closed() -> None:
    with pytest.raises(TypeError):
        fragment_route(1, handler)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        action(1, "/save", handler)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        action("GET", "/save", handler)  # type: ignore[arg-type]


def test_route_rejects_empty_invalid_and_duplicate_surfaces() -> None:
    with pytest.raises(ValueError, match="page, fragment, or action"):
        route()
    with pytest.raises(TypeError, match="fragments must be a tuple"):
        route(fragments=[])  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="FragmentRouteDef"):
        route(fragments=(object(),))  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="actions must be a tuple"):
        route(actions=[])  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="ActionDef"):
        route(actions=(object(),))  # type: ignore[arg-type]

    index = fragment_route("/", handler)
    with pytest.raises(ValueError, match="index fragment"):
        route(page=handler, fragments=(index,))
    with pytest.raises(ValueError, match="fragment paths"):
        route(
            fragments=(
                fragment_route("/user_name", handler),
                fragment_route("/user-name", handler),
            )
        )
    with pytest.raises(ValueError, match="action method and path"):
        route(
            actions=(
                action("POST", "/save_item", handler),
                action("POST", "/save-item", other_handler),
            )
        )


def test_route_accepts_method_distinctions_and_handler_values_without_inspection() -> (
    None
):
    marker = object()
    declared = route(
        page=marker,  # type: ignore[arg-type]
        fragments=(FragmentRouteDef("/shared", marker, None),),  # type: ignore[arg-type]
        actions=(
            ActionDef("POST", "/shared", marker, None),  # type: ignore[arg-type]
            ActionDef("PATCH", "/shared", marker, None),  # type: ignore[arg-type]
        ),
    )
    assert declared.page is marker


def test_public_exports_annotations_and_docstrings_are_exact() -> None:
    expected = {
        "ActionDef",
        "Destination",
        "FragmentResponse",
        "FragmentRouteDef",
        "FragmentRouteResponse",
        "KitActionDef",
        "KitFragmentRouteDef",
        "KitRouteMount",
        "KitRouteDef",
        "MountRoute",
        "Navigation",
        "NavigationBack",
        "NavigationCurrent",
        "NavTrail",
        "NavTrailStep",
        "Page",
        "PageMetadata",
        "PageRouteResponse",
        "RouteDef",
        "RouteErrorHandler",
        "RouteMeta",
        "RouteNav",
        "RouteTarget",
        "RouteResponse",
        "TemplateInspectionMode",
        "action",
        "browser",
        "create_environment",
        "csrf",
        "fragment_route",
        "hx",
        "kit_action",
        "kit_fragment_route",
        "mount_route",
        "nav",
        "nav_step",
        "route",
        "route_mount",
        "route_kit",
        "sse",
        "RequestNav",
        "current_nav_step",
        "to",
    }
    assert set(pyganini.__all__) == expected
    assert {name for name in vars(pyganini) if not name.startswith("_")} == (
        expected | {"request_data"}
    )
    assert (
        importlib.import_module("pyganini.request_data")
        is vars(pyganini)["request_data"]
    )

    assert [field.name for field in fields(FragmentRouteDef)] == [
        "path",
        "handler",
        "template",
    ]
    assert [field.name for field in fields(ActionDef)] == [
        "method",
        "path",
        "handler",
        "template",
        "request_data",
    ]
    assert [field.name for field in fields(RouteDef)] == [
        "page",
        "page_template",
        "fragments",
        "actions",
        "nav",
        "destinations",
        "error_page_template",
        "error_fragment_template",
        "name",
        "title",
        "meta",
    ]
    assert [field.name for field in fields(KitFragmentRouteDef)] == [
        "path",
        "handler",
        "template",
    ]
    assert [field.name for field in fields(KitActionDef)] == [
        "method",
        "path",
        "handler",
        "template",
        "request_data",
    ]
    assert [field.name for field in fields(KitRouteDef)] == [
        "create",
        "template_root",
        "page",
        "page_template",
        "fragments",
        "actions",
        "nav",
        "destinations",
        "error_page_template",
        "error_fragment_template",
        "name",
        "title",
        "meta",
    ]
    assert [field.name for field in fields(MountRoute)] == [
        "path",
        "nav",
        "destinations",
    ]
    assert [field.name for field in fields(KitRouteMount)] == [
        "create",
        "mount",
        "routes",
        "error_page_template",
        "error_fragment_template",
    ]
    assert get_type_hints(FragmentRouteDef)["handler"] == Callable[..., object]
    assert get_type_hints(RouteDef)["page"] == Callable[..., object] | None
    for value in (
        ActionDef,
        FragmentRouteDef,
        KitActionDef,
        KitFragmentRouteDef,
        KitRouteDef,
        RouteDef,
        action,
        fragment_route,
        hx,
        kit_action,
        kit_fragment_route,
        mount_route,
        route,
        route_mount,
        route_kit,
    ):
        assert value.__doc__
    for old_name in (
        "Action",
        "Fragment",
        "Route",
        "fragment",
        "mounted_route",
        "mount_kit",
        "new",
        "factory",
        "include",
        "select",
    ):
        assert not hasattr(pyganini, old_name)
