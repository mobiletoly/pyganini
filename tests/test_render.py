import asyncio
import contextvars
import hashlib
import re
import threading
from collections import UserDict
from collections.abc import Iterator, Mapping
from dataclasses import FrozenInstanceError, fields
from types import MappingProxyType
from typing import Any, cast, get_type_hints

import anyio
import pytest
from anyio.to_thread import current_default_thread_limiter, run_sync
from jinja2 import (
    BaseLoader,
    DictLoader,
    Environment,
    StrictUndefined,
    Undefined,
    UndefinedError,
)
from starlette.responses import PlainTextResponse

import pyganini
from pyganini import (
    FragmentResponse,
    FragmentRouteResponse,
    Page,
    PageMetadata,
    PageRouteResponse,
    RouteResponse,
    create_environment,
)
from pyganini._render import (
    RenderFailure,
    _marker_encode,
    _marker_id,
    render_response,
    validate_environment,
)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _page_response_alias_page() -> PageRouteResponse:
    return Page()


def _page_response_alias_starlette() -> PageRouteResponse:
    return PlainTextResponse("page")


def _fragment_response_alias_fragment() -> FragmentRouteResponse:
    return FragmentResponse()


def _fragment_response_alias_starlette() -> FragmentRouteResponse:
    return PlainTextResponse("fragment")


def _route_response_alias_page() -> RouteResponse:
    return Page()


def _route_response_alias_fragment() -> RouteResponse:
    return FragmentResponse()


def _route_response_alias_starlette() -> RouteResponse:
    return PlainTextResponse("route")


def test_handler_response_aliases_cover_render_values_and_starlette() -> None:
    assert isinstance(_page_response_alias_page(), Page)
    assert isinstance(_page_response_alias_starlette(), PlainTextResponse)
    assert isinstance(_fragment_response_alias_fragment(), FragmentResponse)
    assert isinstance(_fragment_response_alias_starlette(), PlainTextResponse)
    assert isinstance(_route_response_alias_page(), Page)
    assert isinstance(_route_response_alias_fragment(), FragmentResponse)
    assert isinstance(_route_response_alias_starlette(), PlainTextResponse)


def test_template_inspection_marker_encoding_and_id_are_byte_exact() -> None:
    assert _marker_encode("a b%->?#\x00\N{SNOWMAN}") == (
        "a%20b%25%2D%3E%3F%23%00%E2%98%83"
    )
    evidence = (
        "page",
        "page",
        "/users",
        "routes/users/page.jinja",
        "app/routes/users/page.jinja:1:1",
        "none",
        "app/routes/users/route.py:3:1",
        "app.routes.users.route:page",
        "none",
    )
    digest = hashlib.sha256()
    for value in evidence:
        raw = value.encode("utf-8")
        digest.update(str(len(raw)).encode("ascii") + b":" + raw)
    assert _marker_id(evidence, None) == "u" + digest.hexdigest()


def _template(
    name: str,
    declaration: tuple[str, int, int] | None = None,
) -> tuple[str, str, int, int, str | None, tuple[str, int, int] | None]:
    return name, "app/" + name, 1, 1, None, declaration


def _layout(name: str, prefix: str) -> tuple[object, ...]:
    return (
        "app/" + name.removesuffix(".jinja") + ".py",
        1,
        1,
        prefix,
        _template(name),
    )


def test_public_render_values_are_frozen_slotted_typed_and_immutable() -> None:
    child = object()
    context = {"name": "Ada", "child": child}
    layout = {"navigation_label": "People"}
    headers = {"x-page": "users"}

    page = Page(
        context=context,
        metadata=PageMetadata(title="Users", description="Directory"),
        layout=layout,
        status_code=201,
        headers=headers,
    )
    fragment = FragmentResponse(context=context, status_code=202, headers=headers)
    context["name"] = "changed"
    layout["navigation_label"] = "changed"
    headers["x-page"] = "changed"

    assert isinstance(page.context, MappingProxyType)
    assert isinstance(page.layout, MappingProxyType)
    assert isinstance(page.headers, MappingProxyType)
    assert page.context == {"name": "Ada", "child": child}
    assert page.layout == {"navigation_label": "People"}
    assert page.headers == {"x-page": "users"}
    assert fragment.context == {"name": "Ada", "child": child}
    assert fragment.headers == {"x-page": "users"}
    assert not hasattr(page, "__dict__")
    with pytest.raises(FrozenInstanceError):
        page.status_code = 200  # type: ignore[misc]

    assert [field.name for field in fields(PageMetadata)] == [
        "title",
        "description",
    ]
    assert [field.name for field in fields(Page)] == [
        "context",
        "metadata",
        "layout",
        "status_code",
        "headers",
    ]
    assert [field.name for field in fields(FragmentResponse)] == [
        "context",
        "status_code",
        "headers",
    ]
    assert get_type_hints(Page)["metadata"] is PageMetadata


@pytest.mark.parametrize("value", [None, [], (("name", "Ada"),)])
def test_render_values_require_mapping_inputs(value: object) -> None:
    with pytest.raises(TypeError, match="context must be a mapping"):
        Page(context=cast(Any, value))


def test_render_values_accept_mapping_implementations_and_require_string_keys() -> None:
    assert Page(context=UserDict({"name": "Ada"})).context == {"name": "Ada"}
    with pytest.raises(TypeError, match="context keys must be strings"):
        Page(context=cast(Any, {1: "Ada"}))
    with pytest.raises(TypeError, match="layout keys must be strings"):
        Page(layout=cast(Any, {1: "People"}))


@pytest.mark.parametrize("status", [100, 199, 204, 205, 300, 304, 399, 600, True])
def test_render_values_reject_non_body_statuses(status: object) -> None:
    error = TypeError if status is True else ValueError
    with pytest.raises(error):
        FragmentResponse(status_code=cast(Any, status))


@pytest.mark.parametrize("status", [200, 203, 206, 299, 400, 451, 500, 599])
def test_render_values_accept_body_statuses(status: int) -> None:
    assert Page(status_code=status).status_code == status


@pytest.mark.parametrize(
    ("headers", "reason"),
    [
        ({"": "value"}, "header name"),
        ({"bad name": "value"}, "header name"),
        ({"x-name": "line\nfeed"}, "header value"),
        ({"x-name": "delete\x7f"}, "header value"),
        ({"x-name": "not latin \N{EURO SIGN}"}, "Latin-1"),
        ({"x-name": 1}, "header values must be strings"),
        ({"X-Name": "one", "x-name": "two"}, "case-insensitive"),
        ({"content-type": "text/plain"}, "reserved"),
        ({"Content-Length": "1"}, "reserved"),
        ({"LOCATION": "/next"}, "reserved"),
        ({"transfer-encoding": "chunked"}, "reserved"),
    ],
)
def test_render_values_validate_headers(headers: object, reason: str) -> None:
    with pytest.raises((TypeError, ValueError), match=reason):
        Page(headers=cast(Any, headers))


def test_render_values_accept_latin1_and_visible_header_values() -> None:
    headers = {"x-visible": "\t printable \x80\xff"}
    assert FragmentResponse(headers=headers).headers == headers


def test_render_values_validate_metadata() -> None:
    with pytest.raises(TypeError, match="metadata must be a PageMetadata"):
        Page(metadata=cast(Any, object()))
    with pytest.raises(TypeError, match="title must be a string"):
        PageMetadata(title=cast(Any, 1))
    with pytest.raises(TypeError, match="description must be a string"):
        PageMetadata(description=cast(Any, 1))


def test_create_environment_uses_locked_synchronous_html_contract() -> None:
    environment = create_environment(loader=DictLoader({"page.jinja": "{{ value }}"}))

    assert isinstance(environment, Environment)
    assert environment.is_async is False
    assert environment.undefined is StrictUndefined
    assert environment.loader is not None
    autoescape = environment.autoescape
    assert callable(autoescape)
    assert autoescape("page.jinja") is True
    assert autoescape("page.html") is True
    assert autoescape(None) is True
    assert autoescape("page.txt") is False
    assert environment.from_string("{{ value }}").render(value="<b>") == "&lt;b&gt;"
    with pytest.raises(UndefinedError):
        environment.get_template("page.jinja").render()


def test_create_environment_accepts_a_custom_loader_without_mutating_it() -> None:
    loader = DictLoader({"page.jinja": "ok"})
    environment = create_environment(loader=loader)
    assert environment.loader is loader
    assert isinstance(loader, BaseLoader)


@pytest.mark.anyio
async def test_runtime_render_uses_one_mapping_snapshot_in_the_worker() -> None:
    loop_thread = threading.get_ident()

    class ChangingMapping(Mapping[str, str]):
        def __init__(self, name: str, first: str, later: str) -> None:
            self.name = name
            self.first = first
            self.later = later
            self.reads: list[int] = []

        def __getitem__(self, key: str) -> str:
            if key != self.name:
                raise KeyError(key)
            self.reads.append(threading.get_ident())
            return self.first if len(self.reads) == 1 else self.later

        def __iter__(self) -> Iterator[str]:
            return iter((self.name,))

        def __len__(self) -> int:
            return 1

    context = ChangingMapping("value", "first", "changed")
    headers = ChangingMapping("x-snapshot", "first", "changed")
    page = Page()
    object.__setattr__(page, "context", context)
    object.__setattr__(page, "headers", headers)
    environment = create_environment(
        loader=DictLoader({"routes/page.jinja": "{{ value }}"})
    )

    response = await render_response(
        environment=environment,
        result=page,
        template=_template("routes/page.jinja"),
        layouts=(),
    )

    assert response.body == b"first"
    assert response.headers["x-snapshot"] == "first"
    assert len(context.reads) == len(headers.reads) == 1
    assert context.reads[0] != loop_thread
    assert headers.reads[0] != loop_thread


def test_public_render_values_are_documented() -> None:
    for value in (Page, PageMetadata, FragmentResponse, create_environment):
        assert value.__doc__
    assert tuple(pyganini.TemplateInspectionMode) == (
        pyganini.TemplateInspectionMode.OFF,
        pyganini.TemplateInspectionMode.COMMENTS,
        pyganini.TemplateInspectionMode.OVERLAY,
    )
    assert [mode.value for mode in pyganini.TemplateInspectionMode] == [
        "off",
        "comments",
        "overlay",
    ]


@pytest.mark.parametrize(
    ("environment", "reason"),
    [
        (Environment(loader=DictLoader({}), enable_async=True), "async mode"),
        (Environment(loader=DictLoader({}), undefined=Undefined), "StrictUndefined"),
        (Environment(loader=None, undefined=StrictUndefined), "loader"),
        (
            Environment(
                loader=DictLoader({}),
                undefined=StrictUndefined,
                autoescape=False,
            ),
            "autoescape",
        ),
    ],
)
def test_environment_validation_fails_closed_without_mutation(
    environment: Environment, reason: str
) -> None:
    before = dict(vars(environment))
    with pytest.raises(RenderFailure, match=reason) as captured:
        validate_environment(environment, template_names=("routes/page.jinja",))
    assert captured.value.phase == "render-configuration"
    assert vars(environment) == before


def test_environment_validation_accepts_strict_subclasses_and_boolean_autoescape() -> (
    None
):
    class ApplicationUndefined(StrictUndefined):
        pass

    environment = Environment(
        loader=DictLoader({"routes/page.jinja": "ok"}),
        undefined=ApplicationUndefined,
        autoescape=True,
        enable_async=False,
    )
    assert (
        validate_environment(environment, template_names=("routes/page.jinja",))
        is environment
    )


@pytest.mark.anyio
async def test_page_renders_inner_to_outer_with_safe_child_and_escaped_app_values() -> (
    None
):
    environment = create_environment(
        loader=DictLoader(
            {
                "routes/users/page.jinja": "<p>{{ name }}</p>",
                "routes/users/layout.jinja": (
                    "<section data-nav='{{ layout.navigation_label }}'>"
                    "{{ child }}</section>"
                ),
                "routes/layout.jinja": (
                    "<!doctype html><title>{{ metadata.title }}</title>"
                    "<main>{{ child }}</main>"
                ),
            }
        )
    )
    page = Page(
        context={"name": "<Ada>"},
        metadata=PageMetadata(title="People & teams"),
        layout={"navigation_label": "<Users>"},
        status_code=201,
        headers={"x-page": "users"},
    )
    response = await render_response(
        environment=environment,
        result=page,
        template=_template("routes/users/page.jinja"),
        layouts=cast(
            Any,
            (
                _layout("routes/layout.jinja", "/"),
                _layout("routes/users/layout.jinja", "/users"),
            ),
        ),
    )

    assert response.status_code == 201
    assert response.headers["x-page"] == "users"
    assert response.headers["content-type"] == "text/html; charset=utf-8"
    assert int(response.headers["content-length"]) == len(response.body)
    assert bytes(response.body).decode() == (
        "<!doctype html><title>People &amp; teams</title><main>"
        "<section data-nav='&lt;Users&gt;'><p>&lt;Ada&gt;</p></section>"
        "</main>"
    )


@pytest.mark.anyio
async def test_template_inspection_comments_nest_page_layout_component_and_embedded_fragment(  # noqa: E501
) -> None:
    calls = 0

    def count() -> str:
        nonlocal calls
        calls += 1
        return ""

    environment = create_environment(
        loader=DictLoader(
            {
                "routes/users/page.jinja": (
                    "{% call pyganini_inspection.component(' Contact directory ') %}"
                    "{{ count() }}"
                    "{% call pyganini_inspection.fragment('/table') %}"
                    "{{ count() }}TABLE{% endcall %}"
                    "{% endcall %}"
                ),
                "routes/layout.jinja": (
                    "<main>{% call pyganini_inspection.fragment('/table') %}"
                    "LAYOUT{% endcall %}{{ child }}</main>"
                ),
            }
        )
    )
    environment.globals["count"] = count
    page_marker = (
        "page",
        "page",
        "/users",
        "routes/users/page.jinja",
        "app/routes/users/page.jinja:1:1",
        "app/routes/users/route.py:3:20",
        "app/routes/users/route.py:3:1",
        "app.routes.users.route:page",
        "none",
    )
    layout_marker = (
        "layout",
        "page",
        "/",
        "routes/layout.jinja",
        "app/routes/layout.jinja:1:1",
        "none",
        "app/routes/layout.py:1:1",
        "none",
        "none",
    )
    fragment_marker = (
        "fragment",
        "embedded-fragment",
        "/users/table",
        "routes/users/table.jinja",
        "app/routes/users/table.jinja:1:1",
        "app/routes/users/route.py:4:24",
        "app/routes/users/route.py:4:1",
        "app.routes.users.route:table",
        "none",
    )

    response = await render_response(
        environment=environment,
        result=Page(),
        template=_template("routes/users/page.jinja"),
        layouts=cast(Any, (_layout("routes/layout.jinja", "/"),)),
        template_inspection=pyganini.TemplateInspectionMode.COMMENTS,
        marker=page_marker,
        layout_markers=(layout_marker,),
        embedded_fragments=(("/table", fragment_marker),),
    )
    body = response.body.decode("utf-8")
    assert body.startswith("<!--pyganini:start id=u")
    assert " kind=layout surface=page route=/ " in body
    assert " kind=page surface=page route=/users " in body
    assert " kind=component surface=component route=/users " in body
    assert " label=Contact%20directory-->" in body
    assert " kind=fragment surface=embedded%2Dfragment route=/users/table " in body
    assert body.count("surface=embedded%2Dfragment") == 2
    fragment_positions = [match.start() for match in re.finditer("kind=fragment", body)]
    assert body.index("kind=layout") < body.index("kind=page")
    assert body.index("kind=layout") < fragment_positions[0] < body.index("kind=page")
    assert body.index("kind=page") < body.index("kind=component")
    assert body.index("kind=component") < fragment_positions[1]
    assert calls == 2

    off = await render_response(
        environment=environment,
        result=Page(),
        template=_template("routes/users/page.jinja"),
        layouts=cast(Any, (_layout("routes/layout.jinja", "/"),)),
        template_inspection=pyganini.TemplateInspectionMode.OFF,
        marker=page_marker,
        layout_markers=(layout_marker,),
        embedded_fragments=(("/table", fragment_marker),),
    )
    assert off.body == b"<main>LAYOUTTABLE</main>"
    assert calls == 4


@pytest.mark.anyio
async def test_template_inspection_reserved_context_fails_before_template_use() -> None:
    environment = create_environment(loader=DictLoader({"page.jinja": "unused"}))
    with pytest.raises(RenderFailure) as captured:
        await render_response(
            environment=environment,
            result=Page(context={"pyganini_inspection": object()}),
            template=_template("page.jinja"),
            layouts=(),
        )
    assert captured.value.phase == "render-template"
    assert isinstance(captured.value.__cause__, ValueError)
    assert str(captured.value.__cause__) == (
        "Jinja template context reserves pyganini_inspection"
    )


@pytest.mark.anyio
async def test_fragment_renders_without_layout_page_values_or_cache_policy() -> None:
    environment = create_environment(
        loader=DictLoader(
            {
                "routes/table.jinja": "{{ value | default('optional') }}",
                "routes/layout.jinja": "wrong {{ child }}",
            }
        )
    )
    response = await render_response(
        environment=environment,
        result=FragmentResponse(context={}),
        template=_template("routes/table.jinja"),
        layouts=cast(Any, (_layout("routes/layout.jinja", "/"),)),
    )
    assert response.body == b"optional"
    assert "cache-control" not in response.headers


@pytest.mark.anyio
async def test_rendering_supports_unicode_and_application_markup() -> None:
    from markupsafe import Markup

    environment = create_environment(
        loader=DictLoader({"routes/page.jinja": "{{ value }} - Buna ziua"})
    )
    response = await render_response(
        environment=environment,
        result=Page(context={"value": Markup("<strong>safe</strong>")}),
        template=_template("routes/page.jinja"),
        layouts=(),
    )
    assert bytes(response.body).decode() == "<strong>safe</strong> - Buna ziua"


@pytest.mark.anyio
async def test_template_failure_preserves_jinja_cause_and_local_evidence() -> None:
    environment = create_environment(
        loader=DictLoader({"routes/page.jinja": "{{ missing }}"})
    )
    with pytest.raises(RenderFailure) as captured:
        await render_response(
            environment=environment,
            result=Page(),
            template=_template(
                "routes/page.jinja",
                declaration=("app/routes/route.py", 4, 10),
            ),
            layouts=(),
        )
    assert captured.value.phase == "render-template"
    assert isinstance(captured.value.__cause__, UndefinedError)
    assert "template declaration: app/routes/route.py:4:10" in captured.value.details
    assert "template: routes/page.jinja" in captured.value.details
    assert "selected layout chain: <none>" in captured.value.details


@pytest.mark.anyio
async def test_layout_failure_names_marker_prefix_template_and_chain_position() -> None:
    environment = create_environment(
        loader=DictLoader(
            {
                "routes/users/page.jinja": "page",
                "routes/layout.jinja": "{{ child }}",
                "routes/users/layout.jinja": "{{ child }}{{ missing }}",
            }
        )
    )
    with pytest.raises(RenderFailure) as captured:
        await render_response(
            environment=environment,
            result=Page(),
            template=_template("routes/users/page.jinja"),
            layouts=cast(
                Any,
                (
                    _layout("routes/layout.jinja", "/"),
                    _layout("routes/users/layout.jinja", "/users"),
                ),
            ),
        )
    assert isinstance(captured.value.__cause__, UndefinedError)
    assert "layout chain position: 2 of 2" in captured.value.details
    assert "layout route prefix: /users" in captured.value.details
    assert "layout marker: app/routes/users/layout.py:1:1" in captured.value.details
    assert "template: routes/users/layout.jinja" in captured.value.details


@pytest.mark.anyio
async def test_rendering_runs_in_one_worker_with_context_and_no_event_loop() -> None:
    loop_thread = threading.get_ident()
    context = contextvars.ContextVar("render-context", default="missing")
    context.set("present")
    calls: list[tuple[int, str, str]] = []

    def observe(value: str) -> str:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            loop = "absent"
        else:
            loop = "present"
        calls.append((threading.get_ident(), context.get(), loop))
        return value

    environment = create_environment(
        loader=DictLoader(
            {
                "routes/page.jinja": "{{ 'page' | observe }}",
                "routes/layout.jinja": "{{ child }}{{ 'layout' | observe }}",
            }
        )
    )
    environment.filters["observe"] = observe
    limiter = current_default_thread_limiter()
    tokens = limiter.total_tokens
    response = await render_response(
        environment=environment,
        result=Page(),
        template=_template("routes/page.jinja"),
        layouts=cast(Any, (_layout("routes/layout.jinja", "/"),)),
    )
    assert response.body == b"pagelayout"
    assert len({thread for thread, _, _ in calls}) == 1
    assert calls[0][0] != loop_thread
    assert all(value == "present" and loop == "absent" for _, value, loop in calls)
    assert limiter.total_tokens == tokens


@pytest.mark.anyio
async def test_render_cancellation_before_worker_prevents_template_execution() -> None:
    called = False

    def observe(value: str) -> str:
        nonlocal called
        called = True
        return value

    environment = create_environment(
        loader=DictLoader({"routes/page.jinja": "{{ 'page' | observe }}"})
    )
    environment.filters["observe"] = observe
    with anyio.CancelScope() as scope:
        scope.cancel()
        await render_response(
            environment=environment,
            result=Page(),
            template=_template("routes/page.jinja"),
            layouts=(),
        )
    assert not called


@pytest.mark.anyio
async def test_render_cancellation_abandons_waiter_and_worker_finishes() -> None:
    entered = threading.Event()
    release = threading.Event()
    finished = threading.Event()

    def block(value: str) -> str:
        entered.set()
        release.wait(timeout=2)
        finished.set()
        return value

    environment = create_environment(
        loader=DictLoader({"routes/page.jinja": "{{ 'page' | block }}"})
    )
    environment.filters["block"] = block

    async def cancel_when_entered(scope: anyio.CancelScope) -> None:
        while not entered.is_set():
            await anyio.sleep(0)
        scope.cancel()

    with anyio.CancelScope() as scope:
        async with anyio.create_task_group() as group:
            group.start_soon(cancel_when_entered, scope)
            await render_response(
                environment=environment,
                result=Page(),
                template=_template("routes/page.jinja"),
                layouts=(),
            )
    assert not finished.is_set()
    release.set()
    assert await run_sync(finished.wait, 2)
