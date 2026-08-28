# pyright: reportPrivateUsage=false

from __future__ import annotations

import asyncio
import contextvars
import functools
import inspect
import sys
import threading
from collections.abc import AsyncGenerator, Awaitable, Callable
from pathlib import Path
from types import ModuleType
from typing import Any, cast

import anyio
import pytest
from anyio.to_thread import current_default_thread_limiter, run_sync
from jinja2 import DictLoader, Environment, StrictUndefined, UndefinedError
from starlette.background import BackgroundTask
from starlette.exceptions import HTTPException
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import (
    FileResponse,
    PlainTextResponse,
    RedirectResponse,
    Response,
    StreamingResponse,
)
from starlette.routing import Router
from starlette.testclient import TestClient
from starlette.types import Message, Receive, Scope, Send

from pyganini import (
    FragmentResponse,
    KitRouteDef,
    Page,
    create_environment,
    kit_action,
    kit_fragment_route,
    route,
    route_kit,
)
from pyganini._dispatch import (
    DispatchError,
    PathPriorityRoute,
    RouteErrorRouter,
    build_endpoint,
    load_middleware,
    load_route,
    prepare_environment,
    prepare_route_error_handler,
)

type Evidence = tuple[
    str,
    str,
    tuple[str, ...],
    str,
    int,
    int,
    str,
    str,
    str,
]


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _request(
    method: str = "GET", *, path_params: dict[str, str] | None = None
) -> Request:
    return Request(
        {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": method,
            "scheme": "http",
            "path": "/users/one",
            "raw_path": b"/users/one",
            "query_string": b"",
            "root_path": "",
            "headers": [],
            "client": ("127.0.0.1", 1),
            "server": ("testserver", 80),
            "state": {},
            "path_params": path_params or {},
        }
    )


def _evidence(
    *,
    kind: str = "page",
    path: str = "/users/{user_id}",
    methods: tuple[str, ...] = ("GET", "HEAD"),
    module: str = "app.routes.users.route",
    symbol: str = "page",
    binding: str = "page",
) -> Evidence:
    return (
        kind,
        path,
        methods,
        "app/routes/users/route.py",
        4,
        20,
        module,
        symbol,
        binding,
        "app/routes/users/route.py",
        None,
        None,
        4,
        20,
        path,
    )


def _endpoint(
    handler: Callable[[Request], object],
    *,
    methods: tuple[str, ...] = ("GET", "HEAD"),
    parameters: tuple[str, ...] = (),
    kind: str = "page",
    rendering: dict[str, Any] | None = None,
    error_rendering: tuple[Any, ...] = (None, None, (), None, None, ()),
    environment: Environment | None = None,
) -> Callable[[Request], Awaitable[Response]]:
    handlers = {method: handler for method in methods if method != "HEAD"}
    evidence = {
        method: cast(Any, _evidence(kind=kind, methods=methods))
        for method in methods
        if method != "HEAD"
    }
    selected_rendering = (
        {method: rendering[method] for method in handlers}
        if rendering is not None
        else {method: (None, (), None, (), ()) for method in handlers}
    )
    return build_endpoint(
        handlers=handlers,
        evidence=evidence,
        parameters=parameters,
        rendering=selected_rendering,
        embedded_expectations={
            method: cast(Any, facts)[4] for method, facts in selected_rendering.items()
        },
        error_rendering=cast(Any, error_rendering),
        environment=environment,
    )


def _kit_endpoint(
    creator: Callable[..., object],
    handler: Callable[..., object],
    *,
    methods: tuple[str, ...] = ("GET", "HEAD"),
    kind: str = "page",
    rendering: dict[str, Any] | None = None,
    environment: Environment | None = None,
) -> Callable[[Request], Awaitable[Response]]:
    handlers = {method: handler for method in methods if method != "HEAD"}
    creators = {method: creator for method in methods if method != "HEAD"}
    evidence = {
        method: cast(Any, _evidence(kind=kind, methods=methods))
        for method in methods
        if method != "HEAD"
    }
    selected_rendering = (
        {method: rendering[method] for method in handlers}
        if rendering is not None
        else {method: (None, (), None, (), ()) for method in handlers}
    )
    return build_endpoint(
        handlers=handlers,
        creators=creators,
        evidence=evidence,
        parameters=(),
        rendering=selected_rendering,
        embedded_expectations={
            method: cast(Any, facts)[4] for method, facts in selected_rendering.items()
        },
        environment=environment,
    )


def _error_router(
    endpoint: Callable[[Request], Awaitable[Response]],
    handler: Callable[..., object],
    *,
    methods: tuple[str, ...] = ("GET",),
    environment: Environment | None = None,
    rendering: tuple[Any, ...] = (None, None, (), None, None, ()),
    error_layouts: dict[str, tuple[Any, ...]] | None = None,
) -> Router:
    prepared = prepare_route_error_handler(
        cast(Any, handler),
        environment=environment,
        rendering=cast(Any, rendering),
        owner=(
            ("app/routes/route.py", 1, 1)
            if rendering[3] is not None or rendering[4] is not None
            else None
        ),
    )
    assert prepared is not None
    route = PathPriorityRoute(
        "/error",
        endpoint,
        methods=methods,
        error_handler=prepared,
        error_layouts=error_layouts,
    )
    return RouteErrorRouter(
        routes=[route],
        redirect_slashes=False,
        error_handler=prepared,
    )


def test_route_error_render_values_require_templates_and_localize_failures() -> None:
    calls: list[str] = []

    async def endpoint(_: Request) -> Response:
        raise HTTPException(status_code=418)

    def page(_: Request, __: Exception) -> Page:
        calls.append("page")
        return Page(status_code=418)

    environment = create_environment(loader=DictLoader({}))
    with (
        TestClient(_error_router(endpoint, page, environment=environment)) as client,
        pytest.raises(DispatchError) as missing_page,
    ):
        client.get("/error")
    assert missing_page.value.code == "PYGANINI019"
    assert missing_page.value.phase == "route-error-handler"
    assert missing_page.value.message == (
        "error handler returned Page without a declared root error page template"
    )
    assert "actual result type: Page" in missing_page.value.details
    assert "missing root declaration field: error_page_template" in (
        missing_page.value.details
    )
    assert "selected presentation boundary: matched route error page" in (
        missing_page.value.details
    )

    def fragment(_: Request, __: Exception) -> FragmentResponse:
        calls.append("fragment")
        return FragmentResponse(status_code=418)

    with (
        TestClient(
            _error_router(endpoint, fragment, environment=environment)
        ) as client,
        pytest.raises(DispatchError) as missing_fragment,
    ):
        client.get("/error")
    assert missing_fragment.value.code == "PYGANINI019"
    assert missing_fragment.value.message == (
        "error handler returned FragmentResponse without a declared root error "
        "fragment template"
    )
    assert "missing root declaration field: error_fragment_template" in (
        missing_fragment.value.details
    )

    failing_environment = create_environment(
        loader=DictLoader({"routes/error_page.jinja": "{{ missing }}"})
    )
    page_template = (
        "routes/error_page.jinja",
        "app/routes/error_page.jinja",
        1,
        1,
        None,
        ("app/routes/route.py", 3, 25),
    )
    page_marker = (
        "page",
        "root-error-page",
        "/",
        "routes/error_page.jinja",
        "app/routes/error_page.jinja:1:1",
        "app/routes/route.py:3:25",
        "app/routes/route.py:1:1",
        "route_error_handler",
        "none",
    )
    with (
        TestClient(
            _error_router(
                endpoint,
                page,
                environment=failing_environment,
                rendering=(page_template, None, (), page_marker, None, ()),
            )
        ) as client,
        pytest.raises(DispatchError) as render_failure,
    ):
        client.get("/error")
    assert render_failure.value.code == "PYGANINI015"
    assert render_failure.value.phase == "render-template"
    assert isinstance(render_failure.value.__cause__, UndefinedError)
    assert "selected presentation boundary: matched route error page" in (
        render_failure.value.details
    )
    assert calls == ["page", "fragment", "page"]


def test_route_error_handler_public_callback_validation_and_async_invocation() -> None:
    def invalid_handler(_: Request) -> None:
        return None

    with pytest.raises(DispatchError) as invalid:
        prepare_route_error_handler(cast(Any, invalid_handler))
    assert invalid.value.code == "PYGANINI019"
    assert invalid.value.phase == "route-error-handler"

    seen: list[tuple[str, str]] = []

    async def endpoint(_: Request) -> Response:
        raise HTTPException(status_code=418, headers={"X-Test": "required"})

    async def handler(request: Request, error: Exception) -> Response:
        assert isinstance(error, HTTPException)
        seen.append((request.method, type(error).__name__))
        return PlainTextResponse("teapot", status_code=418)

    with TestClient(_error_router(endpoint, handler)) as client:
        response = client.get("/error")

    assert response.status_code == 418
    assert response.text == "teapot"
    assert response.headers["x-test"] == "required"
    assert seen == [("GET", "HTTPException")]


def test_route_error_handler_snapshots_http_contract_before_callback() -> None:
    async def endpoint(_: Request) -> Response:
        raise HTTPException(status_code=418, headers={"X-Test": "required"})

    def handler(_: Request, error: Exception) -> Response:
        assert isinstance(error, HTTPException)
        error.status_code = 499
        error.headers = {"X-Test": "changed"}
        return PlainTextResponse(
            "handled",
            status_code=418,
            headers={"X-Test": "required"},
        )

    with TestClient(_error_router(endpoint, handler)) as client:
        response = client.get("/error")

    assert response.status_code == 418
    assert response.headers["x-test"] == "required"


def test_route_error_handler_snapshots_canonical_allow_before_callback() -> None:
    async def endpoint(_: Request) -> Response:
        return PlainTextResponse("body")

    def handler(_: Request, error: Exception) -> Response:
        assert isinstance(error, HTTPException)
        error.status_code = 418
        error.headers = {"Allow": "POST"}
        return PlainTextResponse(
            "handled",
            status_code=405,
            headers={"Allow": "GET, HEAD"},
        )

    with TestClient(_error_router(endpoint, handler)) as client:
        response = client.post("/error")

    assert response.status_code == 405
    assert response.headers["allow"] == "GET, HEAD"


def test_route_error_handler_rejects_invalid_result_and_status() -> None:
    async def endpoint(_: Request) -> Response:
        raise HTTPException(status_code=418, headers={"X-Test": "required"})

    def invalid_result(_: Request, __: Exception) -> object:
        return object()

    with (
        TestClient(_error_router(endpoint, invalid_result)) as client,
        pytest.raises(DispatchError) as result_error,
    ):
        client.get("/error")
    assert result_error.value.code == "PYGANINI019"
    assert result_error.value.message == (
        "error handler must return Page, FragmentResponse, a Starlette Response, "
        "or None"
    )
    assert "actual result type: object" in result_error.value.details
    assert "normalized path: /error" in result_error.value.details
    assert "expected status: 418" in result_error.value.details

    def wrong_status(_: Request, __: Exception) -> Response:
        return PlainTextResponse("wrong", status_code=200)

    with (
        TestClient(_error_router(endpoint, wrong_status)) as client,
        pytest.raises(DispatchError) as status_error,
    ):
        client.get("/error")
    assert status_error.value.code == "PYGANINI019"
    assert "expected status: 418" in status_error.value.details
    assert "actual status: 200" in status_error.value.details

    def wrong_header(_: Request, __: Exception) -> Response:
        return PlainTextResponse(
            "wrong header",
            status_code=418,
            headers={"X-Test": "wrong"},
        )

    with (
        TestClient(_error_router(endpoint, wrong_header)) as client,
        pytest.raises(DispatchError) as header_error,
    ):
        client.get("/error")
    assert header_error.value.code == "PYGANINI019"
    assert "required header: X-Test" in header_error.value.details
    assert "expected status: 418" in header_error.value.details
    assert "actual status: 418" in header_error.value.details


def test_route_error_handler_prefers_selected_route_path_for_dispatch_error() -> None:
    endpoint = build_endpoint(
        handlers={"GET": cast(Callable[..., object], object())},
        evidence={"GET": cast(Any, _evidence(methods=("GET",)))},
        parameters=(),
        rendering={"GET": (None, (), None, (), ())},
        embedded_expectations={"GET": ()},
    )

    def invalid_result(_: Request, __: Exception) -> object:
        return object()

    with (
        TestClient(_error_router(endpoint, invalid_result)) as client,
        pytest.raises(DispatchError) as result_error,
    ):
        client.get("/error")

    assert result_error.value.code == "PYGANINI019"
    assert "normalized path: /error" in result_error.value.details
    assert (
        "normalized path: app/routes/users/route.py" not in result_error.value.details
    )


def test_route_error_handler_preserves_head_and_allow_response_contracts() -> None:
    async def endpoint(_: Request) -> Response:
        return PlainTextResponse("body")

    def handler(_: Request, error: Exception) -> Response:
        assert isinstance(error, HTTPException)
        return PlainTextResponse("handled", status_code=error.status_code)

    with TestClient(_error_router(endpoint, handler)) as client:
        head = client.head("/missing")
        method_not_allowed = client.post("/error")

    assert head.status_code == 404
    assert head.content == b""
    assert head.headers["content-length"] == str(len("handled"))
    assert method_not_allowed.status_code == 405
    assert method_not_allowed.headers["allow"] == "GET, HEAD"


def test_route_error_handler_sends_non_http_500_then_reraises_original() -> None:
    original = RuntimeError("original")

    async def endpoint(_: Request) -> Response:
        raise original

    def handler(_: Request, error: Exception) -> Response:
        assert error is original
        return PlainTextResponse("presented", status_code=500)

    with (
        TestClient(_error_router(endpoint, handler)) as client,
        pytest.raises(RuntimeError) as captured,
    ):
        client.get("/error")
    assert captured.value is original


def test_route_error_handler_failure_propagates_without_recursion() -> None:
    callback_calls: list[str] = []

    async def endpoint(_: Request) -> Response:
        raise RuntimeError("route")

    def handler(_: Request, __: Exception) -> Response:
        callback_calls.append("called")
        raise ValueError("callback")

    with (
        TestClient(_error_router(endpoint, handler)) as client,
        pytest.raises(ValueError, match="callback"),
    ):
        client.get("/error")
    assert callback_calls == ["called"]


def test_route_error_handler_skips_callback_after_start_and_baseexception() -> None:
    callback_calls: list[str] = []

    async def streaming_endpoint(_: Request) -> Response:
        async def body() -> AsyncGenerator[bytes]:
            yield b"started"
            raise RuntimeError("after start")

        return StreamingResponse(body())

    def handler(_: Request, __: Exception) -> Response:
        callback_calls.append("called")
        return PlainTextResponse("handled", status_code=500)

    with (
        TestClient(_error_router(streaming_endpoint, handler)) as client,
        pytest.raises(RuntimeError, match="after start"),
    ):
        client.get("/error")
    assert callback_calls == []

    class ControlSignal(BaseException):
        pass

    async def cancelled(_: Request) -> Response:
        raise ControlSignal()

    cancelled_router = _error_router(cancelled, handler)

    async def receive() -> Message:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(_: Message) -> None:
        pass

    scope: Scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/error",
        "raw_path": b"/error",
        "query_string": b"",
        "root_path": "",
        "headers": [],
        "client": ("127.0.0.1", 1),
        "server": ("testserver", 80),
    }
    app = cast(Callable[[Scope, Receive, Send], Awaitable[None]], cancelled_router)

    with pytest.raises(ControlSignal):
        anyio.run(app, scope, receive, send)
    assert callback_calls == []


def _surface(
    *,
    kind: str = "page",
    method: str = "GET",
    local_path: str = "/",
    path: str = "/",
    methods: tuple[str, ...] = ("GET", "HEAD"),
    module: str,
    symbol: str,
    binding: str,
) -> tuple[Any, ...]:
    return (
        kind,
        method,
        local_path,
        path,
        methods,
        module,
        symbol,
        binding,
        "app/routes/route.py",
        4,
        20,
        None,
    )


def _modules(
    monkeypatch: pytest.MonkeyPatch,
    *,
    route_module_name: str,
    source_module_name: str,
    handler: object,
    symbol: str = "page",
    binding: str = "page",
    module_alias: bool = False,
) -> ModuleType:
    source_module = ModuleType(source_module_name)
    vars(source_module)[symbol] = handler
    route_module = ModuleType(route_module_name)
    vars(route_module)["Route"] = route(page=cast(Any, handler))
    vars(route_module)[binding] = source_module if module_alias else handler
    monkeypatch.setitem(sys.modules, source_module_name, source_module)
    monkeypatch.setitem(sys.modules, route_module_name, route_module)
    return route_module


def _kit_modules(
    monkeypatch: pytest.MonkeyPatch,
    *,
    route_module_name: str,
    source_module_name: str,
    creator: object,
    handler: object,
    creator_binding: str = "create",
) -> ModuleType:
    source_module = ModuleType(source_module_name)
    vars(source_module)["page"] = handler
    route_module = ModuleType(route_module_name)
    vars(route_module)[creator_binding] = creator
    vars(route_module)["handlers"] = source_module
    vars(route_module)["Route"] = route_kit(
        create=cast(Any, creator),
        page=cast(Any, handler),
    )
    monkeypatch.setitem(sys.modules, source_module_name, source_module)
    monkeypatch.setitem(sys.modules, route_module_name, route_module)
    return route_module


def test_load_middleware_reads_only_the_direct_module_binding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FixtureMiddleware(BaseHTTPMiddleware):
        async def dispatch(
            self,
            request: Request,
            call_next: Callable[[Request], Awaitable[Response]],
        ) -> Response:
            return await call_next(request)

    module = ModuleType("dispatch_fixture.middleware")
    configured = Middleware(FixtureMiddleware)
    vars(module)["MIDDLEWARE"] = (configured,)
    called = False

    def module_getattr(_: str) -> object:
        nonlocal called
        called = True
        return (configured,)

    vars(module)["__getattr__"] = module_getattr
    monkeypatch.setitem(sys.modules, module.__name__, module)

    loaded = load_middleware(
        module=module.__name__,
        source_path="app/routes/middleware.py",
        route_prefix="/",
        expected_entries=((1, 15),),
        binding=(1, 1),
        consumers=(),
    )

    assert loaded == (configured,)
    assert not called


def test_load_middleware_import_failure_preserves_cause() -> None:
    with pytest.raises(DispatchError) as captured:
        load_middleware(
            module="dispatch_fixture.module_that_does_not_exist",
            source_path="app/routes/middleware.py",
            route_prefix="/",
            expected_entries=((1, 15),),
            binding=(1, 1),
            consumers=(),
        )

    assert captured.value.code == "PYGANINI018"
    assert captured.value.phase == "route-middleware"
    assert isinstance(captured.value.__cause__, ModuleNotFoundError)
    assert "cannot import middleware module" in captured.value.message


@pytest.mark.parametrize(
    ("value", "message"),
    [
        ([], "not a tuple"),
        ((object(),), "invalid member"),
        ((object(), object()), "tuple count"),
    ],
)
def test_load_middleware_localizes_runtime_binding_failures(
    monkeypatch: pytest.MonkeyPatch,
    value: object,
    message: str,
) -> None:
    module = ModuleType("dispatch_fixture.invalid_middleware")
    vars(module)["MIDDLEWARE"] = value
    monkeypatch.setitem(sys.modules, module.__name__, module)

    with pytest.raises(DispatchError) as captured:
        load_middleware(
            module=module.__name__,
            source_path="app/routes/users/middleware.py",
            route_prefix="/users",
            expected_entries=((1, 15),),
            binding=(1, 1),
            consumers=(),
        )

    assert captured.value.code == "PYGANINI018"
    assert captured.value.phase == "route-middleware"
    assert message in captured.value.message
    assert captured.value.__cause__ is not None
    assert any(
        "app/routes/users/middleware.py" in detail for detail in captured.value.details
    )
    assert (
        "middleware binding: app/routes/users/middleware.py:1:1"
        in captured.value.details
    )


def _zero_argument_handler() -> Response:
    return PlainTextResponse("zero")


def _extra_argument_handler(_: Request, required: str) -> Response:
    return PlainTextResponse(required)


@pytest.mark.parametrize(
    ("aliased", "module_alias"),
    [(False, False), (True, False), (True, True)],
)
def test_load_route_validates_local_direct_alias_and_module_attribute_bindings(
    monkeypatch: pytest.MonkeyPatch, aliased: bool, module_alias: bool
) -> None:
    def page(_: Request) -> Response:
        return PlainTextResponse("ok")

    route_module_name = "dispatch_fixture.route"
    source_module_name = "dispatch_fixture.handlers" if aliased else route_module_name
    binding = "handlers" if module_alias else ("aliased_page" if aliased else "page")
    _modules(
        monkeypatch,
        route_module_name=route_module_name,
        source_module_name=source_module_name,
        handler=page,
        binding=binding,
        module_alias=module_alias,
    )

    loaded = load_route(
        module=route_module_name,
        source_path="app/routes/route.py",
        expected=(
            cast(
                Any,
                _surface(
                    module=source_module_name,
                    symbol="page",
                    binding=binding,
                ),
            ),
        ),
    )
    assert loaded.page is page


def test_load_route_rejects_dynamic_route_attribute(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = ModuleType("dispatch_dynamic.route")

    def page(_: Request) -> Response:
        return PlainTextResponse("wrong")

    def dynamic(name: str) -> object:
        if name == "Route":
            return route(page=page)
        raise AttributeError(name)

    vars(module)["__getattr__"] = dynamic
    monkeypatch.setitem(sys.modules, module.__name__, module)
    with pytest.raises(DispatchError) as captured:
        load_route(
            module=module.__name__,
            source_path="app/routes/route.py",
            expected=(),
        )
    assert captured.value.code == "PYGANINI012"
    assert captured.value.phase == "route-import"
    assert "direct Route binding" in captured.value.message


def test_load_route_preserves_import_failure_as_cause() -> None:
    with pytest.raises(DispatchError) as captured:
        load_route(
            module="dispatch_missing.route",
            source_path="app/routes/route.py",
            expected=(),
        )
    assert captured.value.code == "PYGANINI012"
    assert isinstance(captured.value.__cause__, ModuleNotFoundError)


def test_load_route_rejects_binding_drift(monkeypatch: pytest.MonkeyPatch) -> None:
    def page(_: Request) -> Response:
        return PlainTextResponse("ok")

    module = _modules(
        monkeypatch,
        route_module_name="dispatch_drift.route",
        source_module_name="dispatch_drift.route",
        handler=page,
    )

    def changed(_: Request) -> Response:
        return PlainTextResponse("changed")

    vars(module)["page"] = changed
    with pytest.raises(DispatchError) as captured:
        load_route(
            module=module.__name__,
            source_path="app/routes/route.py",
            expected=(
                cast(
                    Any,
                    _surface(module=module.__name__, symbol="page", binding="page"),
                ),
            ),
        )
    assert captured.value.code == "PYGANINI012"
    assert "identity" in captured.value.message


@pytest.mark.parametrize(
    ("handler", "reason"),
    [
        (_zero_argument_handler, "one positional request"),
        (_extra_argument_handler, "one positional request"),
    ],
)
def test_load_route_rejects_invalid_signatures(
    monkeypatch: pytest.MonkeyPatch, handler: object, reason: str
) -> None:
    module_name = "dispatch_signature.route"
    _modules(
        monkeypatch,
        route_module_name=module_name,
        source_module_name=module_name,
        handler=handler,
    )
    with pytest.raises(DispatchError) as captured:
        load_route(
            module=module_name,
            source_path="app/routes/route.py",
            expected=(
                cast(
                    Any,
                    _surface(module=module_name, symbol="page", binding="page"),
                ),
            ),
        )
    assert captured.value.code == "PYGANINI013"
    assert captured.value.phase == "route-callable"
    assert reason in captured.value.message


def test_load_route_validates_kit_creator_and_two_argument_handler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def creator(_: Request) -> str:
        return "kit"

    def page(_: str, __: Request) -> Response:
        return PlainTextResponse("ok")

    module_name = "kit_dispatch.route"
    _kit_modules(
        monkeypatch,
        route_module_name=module_name,
        source_module_name="kit_dispatch.handlers",
        creator=creator,
        handler=page,
    )
    loaded = load_route(
        module=module_name,
        source_path="app/routes/route.py",
        expected=(
            cast(
                Any,
                _surface(
                    module="kit_dispatch.handlers",
                    symbol="page",
                    binding="handlers",
                ),
            ),
        ),
        expected_creator=(
            module_name,
            "create",
            "create",
            "app/routes/route.py",
            4,
            20,
        ),
    )
    loaded_kit = cast(KitRouteDef[object], loaded)
    assert loaded_kit.create is creator


def test_load_route_rejects_kit_creator_and_handler_signature_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def bad_creator(_: Request, required: str) -> str:
        return required

    def page(_: str, __: Request) -> Response:
        return PlainTextResponse("ok")

    module_name = "kit_dispatch_bad_creator.route"
    _kit_modules(
        monkeypatch,
        route_module_name=module_name,
        source_module_name="kit_dispatch_bad_creator.handlers",
        creator=bad_creator,
        handler=page,
        creator_binding="bad_creator",
    )
    with pytest.raises(DispatchError, match="kit creator must accept") as creator_error:
        load_route(
            module=module_name,
            source_path="app/routes/route.py",
            expected=(
                cast(
                    Any,
                    _surface(
                        module="kit_dispatch_bad_creator.handlers",
                        symbol="page",
                        binding="handlers",
                    ),
                ),
            ),
            expected_creator=(
                module_name,
                "bad_creator",
                "bad_creator",
                "app/routes/route.py",
                4,
                20,
            ),
        )
    assert creator_error.value.code == "PYGANINI013"

    def creator(_: Request) -> str:
        return "kit"

    def bad_page(_: Request) -> Response:
        return PlainTextResponse("wrong")

    handler_module = _kit_modules(
        monkeypatch,
        route_module_name="kit_dispatch_bad_handler.route",
        source_module_name="kit_dispatch_bad_handler.handlers",
        creator=creator,
        handler=bad_page,
    )
    assert handler_module
    with pytest.raises(DispatchError, match="kit handler must accept") as handler_error:
        load_route(
            module="kit_dispatch_bad_handler.route",
            source_path="app/routes/route.py",
            expected=(
                cast(
                    Any,
                    _surface(
                        module="kit_dispatch_bad_handler.handlers",
                        symbol="page",
                        binding="handlers",
                    ),
                ),
            ),
            expected_creator=(
                "kit_dispatch_bad_handler.route",
                "create",
                "create",
                "app/routes/route.py",
                4,
                20,
            ),
        )
    assert handler_error.value.code == "PYGANINI013"
    assert "callable role: kit handler" in handler_error.value.details


def test_load_route_creator_diagnostics_include_all_kit_surfaces(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def bad_creator(_: Request, required: str) -> str:
        return required

    def page(_: str, __: Request) -> Response:
        return PlainTextResponse("page")

    def table(_: str, __: Request) -> FragmentResponse:
        return FragmentResponse()

    def save(_: str, __: Request) -> Response:
        return PlainTextResponse("save")

    route_module_name = "kit_dispatch_surfaces.route"
    source_module_name = "kit_dispatch_surfaces.handlers"
    source_module = ModuleType(source_module_name)
    vars(source_module).update(page=page, table=table, save=save)
    route_module = ModuleType(route_module_name)
    vars(route_module).update(create=bad_creator, handlers=source_module)
    vars(route_module)["Route"] = route_kit(
        create=cast(Any, bad_creator),
        page=cast(Any, page),
        fragments=(kit_fragment_route("/table", cast(Any, table)),),
        actions=(kit_action("POST", "/save", cast(Any, save)),),
    )
    monkeypatch.setitem(sys.modules, source_module_name, source_module)
    monkeypatch.setitem(sys.modules, route_module_name, route_module)

    expected = (
        cast(
            Any,
            _surface(
                kind="page",
                method="GET",
                local_path="/",
                path="/users",
                module=source_module_name,
                symbol="page",
                binding="handlers",
            ),
        ),
        cast(
            Any,
            _surface(
                kind="fragment",
                method="GET",
                local_path="/table",
                path="/users/table",
                module=source_module_name,
                symbol="table",
                binding="handlers",
            ),
        ),
        cast(
            Any,
            _surface(
                kind="action",
                method="POST",
                local_path="/save",
                path="/users/save",
                methods=("POST",),
                module=source_module_name,
                symbol="save",
                binding="handlers",
            ),
        ),
    )
    with pytest.raises(DispatchError, match="kit creator must accept") as captured:
        load_route(
            module=route_module_name,
            source_path="app/routes/users/route.py",
            expected=expected,
            expected_creator=(
                route_module_name,
                "create",
                "create",
                "app/routes/users/route.py",
                4,
                20,
            ),
        )

    assert "creator surface: page" in captured.value.details
    assert "creator normalized path: /users" in captured.value.details
    assert "creator surface: fragment" in captured.value.details
    assert "creator normalized path: /users/table" in captured.value.details
    assert "creator surface: action" in captured.value.details
    assert "creator methods: POST" in captured.value.details
    assert "creator normalized path: /users/save" in captured.value.details


def test_load_route_rejects_async_generator(monkeypatch: pytest.MonkeyPatch) -> None:
    async def page(_: Request) -> AsyncGenerator[object]:
        yield object()

    module_name = "dispatch_async_generator.route"
    _modules(
        monkeypatch,
        route_module_name=module_name,
        source_module_name=module_name,
        handler=page,
    )
    with pytest.raises(DispatchError, match="async generator") as captured:
        load_route(
            module=module_name,
            source_path="app/routes/route.py",
            expected=(
                cast(
                    Any,
                    _surface(module=module_name, symbol="page", binding="page"),
                ),
            ),
        )
    assert captured.value.code == "PYGANINI013"


def test_load_route_rejects_descriptor_without_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Descriptor:
        inspected = False

        @property
        def __wrapped__(self) -> object:
            self.inspected = True
            raise AssertionError("descriptor was accessed")

        def __get__(self, instance: object, owner: type[object]) -> object:
            def wrong(_: Request) -> Response:
                return PlainTextResponse("wrong")

            return wrong

    class Handler:
        __call__ = Descriptor()

    handler = cast(Any, Handler())
    module_name = "dispatch_descriptor.route"
    _modules(
        monkeypatch,
        route_module_name=module_name,
        source_module_name=module_name,
        handler=handler,
    )
    with pytest.raises(DispatchError, match="unsupported __call__ descriptor"):
        load_route(
            module=module_name,
            source_path="app/routes/route.py",
            expected=(
                cast(
                    Any,
                    _surface(module=module_name, symbol="page", binding="page"),
                ),
            ),
        )
    descriptor = cast(Descriptor, inspect.getattr_static(Handler, "__call__"))
    assert not descriptor.inspected


def test_load_route_rejects_partial_instance_without_request_slot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Handler:
        def __call__(self, _: Request) -> Response:
            return PlainTextResponse("ok")

    handler = functools.partial(Handler(), _request())
    module_name = "dispatch_partial_instance_without_request.route"
    _modules(
        monkeypatch,
        route_module_name=module_name,
        source_module_name=module_name,
        handler=handler,
    )

    with pytest.raises(DispatchError) as captured:
        load_route(
            module=module_name,
            source_path="app/routes/route.py",
            expected=(
                cast(
                    Any,
                    _surface(module=module_name, symbol="page", binding="page"),
                ),
            ),
        )
    assert captured.value.code == "PYGANINI013"
    assert captured.value.phase == "route-callable"


def test_load_route_accepts_partial_instance_with_bound_required_argument(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Handler:
        def __call__(self, prefix: str, _: Request) -> Response:
            return PlainTextResponse(prefix)

    handler = functools.partial(Handler(), "ok")
    module_name = "dispatch_partial_instance_with_bound_argument.route"
    _modules(
        monkeypatch,
        route_module_name=module_name,
        source_module_name=module_name,
        handler=handler,
    )

    loaded = load_route(
        module=module_name,
        source_path="app/routes/route.py",
        expected=(
            cast(
                Any,
                _surface(module=module_name, symbol="page", binding="page"),
            ),
        ),
    )
    assert loaded.page is handler


@pytest.mark.anyio
async def test_sync_handler_is_offloaded_with_context_and_no_event_loop() -> None:
    loop_thread = threading.get_ident()
    context = contextvars.ContextVar("dispatch-context", default="missing")
    context.set("present")

    def handler(_: Request) -> Response:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            loop = "absent"
        else:
            loop = "present"
        return PlainTextResponse(f"{threading.get_ident()}:{context.get()}:{loop}")

    response = await _endpoint(handler)(_request())
    worker, value, loop = bytes(response.body).decode().split(":")
    assert int(worker) != loop_thread
    assert value == "present"
    assert loop == "absent"


@pytest.mark.anyio
async def test_async_and_returned_awaitable_run_on_event_loop_thread() -> None:
    loop_thread = threading.get_ident()

    async def async_handler(_: Request) -> Response:
        return PlainTextResponse(str(threading.get_ident()))

    wrapper_thread: int | None = None

    def sync_wrapper(_: Request) -> Awaitable[Response]:
        nonlocal wrapper_thread
        wrapper_thread = threading.get_ident()

        async def result() -> Response:
            return PlainTextResponse(str(threading.get_ident()))

        return result()

    direct = await _endpoint(async_handler)(_request())
    wrapped = await _endpoint(sync_wrapper)(_request())
    assert direct.body == str(loop_thread).encode()
    assert wrapper_thread is not None and wrapper_thread != loop_thread
    assert wrapped.body == str(loop_thread).encode()


@pytest.mark.anyio
@pytest.mark.parametrize("creator_async", [False, True])
@pytest.mark.parametrize("handler_async", [False, True])
async def test_kit_creator_and_handler_classify_independently_with_context(
    creator_async: bool, handler_async: bool
) -> None:
    loop_thread = threading.get_ident()
    context = contextvars.ContextVar("kit-dispatch-context", default="missing")
    context.set("present")
    creator_threads: list[int] = []
    handler_threads: list[int] = []
    creator_loops: list[str] = []
    handler_loops: list[str] = []

    def sync_creator(_: Request) -> str:
        creator_threads.append(threading.get_ident())
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            creator_loops.append("absent")
        else:
            creator_loops.append("present")
        assert context.get() == "present"
        return "kit"

    async def async_creator(_: Request) -> str:
        creator_threads.append(threading.get_ident())
        creator_loops.append("present")
        assert context.get() == "present"
        await asyncio.sleep(0)
        return "kit"

    def sync_handler(kit: str, _: Request) -> Response:
        handler_threads.append(threading.get_ident())
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            handler_loops.append("absent")
        else:
            handler_loops.append("present")
        return PlainTextResponse(f"{kit}:{context.get()}")

    async def async_handler(kit: str, _: Request) -> Response:
        handler_threads.append(threading.get_ident())
        handler_loops.append("present")
        await asyncio.sleep(0)
        return PlainTextResponse(f"{kit}:{context.get()}")

    creator = cast(
        Callable[..., object], async_creator if creator_async else sync_creator
    )
    handler = cast(
        Callable[..., object], async_handler if handler_async else sync_handler
    )
    response = await _kit_endpoint(creator, handler)(_request())

    assert response.body == b"kit:present"
    assert len(creator_threads) == len(handler_threads) == 1
    assert (creator_threads[0] == loop_thread) is creator_async
    assert (handler_threads[0] == loop_thread) is handler_async
    assert creator_loops == (["present"] if creator_async else ["absent"])
    assert handler_loops == (["present"] if handler_async else ["absent"])


@pytest.mark.anyio
async def test_kit_sync_callables_await_returned_awaitables_on_the_event_loop() -> None:
    loop_thread = threading.get_ident()
    creator_thread: int | None = None
    handler_thread: int | None = None
    result_threads: list[int] = []

    def creator(_: Request) -> Awaitable[str]:
        nonlocal creator_thread
        creator_thread = threading.get_ident()

        async def result() -> str:
            result_threads.append(threading.get_ident())
            return "kit"

        return result()

    def handler(kit: str, _: Request) -> Awaitable[Response]:
        nonlocal handler_thread
        handler_thread = threading.get_ident()

        async def result() -> Response:
            result_threads.append(threading.get_ident())
            return PlainTextResponse(kit)

        return result()

    response = await _kit_endpoint(creator, handler)(_request())

    assert response.body == b"kit"
    assert creator_thread != loop_thread
    assert handler_thread != loop_thread
    assert result_threads == [loop_thread, loop_thread]


@pytest.mark.anyio
async def test_kit_creator_and_handler_are_not_cached_and_head_uses_head_request() -> (
    None
):
    calls: list[tuple[str, str]] = []

    def creator(request: Request) -> str:
        calls.append(("creator", request.method))
        return "kit"

    def handler(kit: str, request: Request) -> Response:
        calls.append(("handler", request.method))
        return PlainTextResponse(f"{kit}:{request.method}")

    endpoint = _kit_endpoint(creator, handler)
    get_response = await endpoint(_request("GET"))
    head_response = await endpoint(_request("HEAD"))
    second_get_response = await endpoint(_request("GET"))

    assert get_response.body == b"kit:GET"
    assert head_response.body == b""
    assert second_get_response.body == b"kit:GET"
    assert calls == [
        ("creator", "GET"),
        ("handler", "GET"),
        ("creator", "HEAD"),
        ("handler", "HEAD"),
        ("creator", "GET"),
        ("handler", "GET"),
    ]


@pytest.mark.anyio
async def test_kit_creator_exception_crosses_unchanged_and_handler_is_not_started() -> (
    None
):
    class CreatorError(RuntimeError):
        pass

    failure = CreatorError("creator failed")
    handler_called = False

    def creator(_: Request) -> str:
        raise failure

    def handler(_: str, __: Request) -> Response:
        nonlocal handler_called
        handler_called = True
        return PlainTextResponse("wrong")

    with pytest.raises(CreatorError) as captured:
        await _kit_endpoint(creator, handler)(_request())
    assert captured.value is failure
    assert not handler_called


@pytest.mark.anyio
async def test_cancellation_during_kit_creator_does_not_start_handler() -> None:
    entered = threading.Event()
    release = threading.Event()
    finished = threading.Event()
    handler_called = False

    def creator(_: Request) -> str:
        entered.set()
        release.wait(timeout=2)
        finished.set()
        return "kit"

    def handler(_: str, __: Request) -> Response:
        nonlocal handler_called
        handler_called = True
        return PlainTextResponse("wrong")

    async def cancel_when_entered(scope: anyio.CancelScope) -> None:
        while not entered.is_set():
            await anyio.sleep(0)
        scope.cancel()

    with anyio.CancelScope() as scope:
        async with anyio.create_task_group() as group:
            group.start_soon(cancel_when_entered, scope)
            await _kit_endpoint(creator, handler)(_request())
    assert not handler_called
    assert not finished.is_set()
    release.set()
    assert await run_sync(finished.wait, 2)


@pytest.mark.anyio
async def test_mixed_local_and_kit_methods_share_one_generated_path_plan() -> None:
    def local(_: Request) -> Response:
        return PlainTextResponse("local")

    def creator(_: Request) -> str:
        return "kit"

    def kit_handler(kit: str, _: Request) -> Response:
        return PlainTextResponse(kit)

    endpoint = build_endpoint(
        handlers={"GET": local, "POST": kit_handler},
        creators={"POST": creator},
        evidence={
            "GET": cast(Any, _evidence(kind="page", methods=("GET", "HEAD"))),
            "POST": cast(Any, _evidence(kind="action", methods=("POST",))),
        },
        parameters=(),
        rendering={
            "GET": (None, (), None, (), ()),
            "POST": (None, (), None, (), ()),
        },
        embedded_expectations={"GET": (), "POST": ()},
    )

    assert (await endpoint(_request("GET"))).body == b"local"
    assert (await endpoint(_request("POST"))).body == b"kit"


@pytest.mark.anyio
@pytest.mark.parametrize(
    "form",
    ["bound-sync", "bound-async", "partial", "sync-instance", "async-instance"],
)
async def test_supported_callable_forms(form: str) -> None:
    class Owner:
        def sync(self, _: Request) -> Response:
            return PlainTextResponse("bound-sync")

        async def async_(self, _: Request) -> Response:
            return PlainTextResponse("bound-async")

    class SyncInstance:
        def __call__(self, _: Request) -> Response:
            return PlainTextResponse("sync-instance")

    class AsyncInstance:
        async def __call__(self, _: Request) -> Response:
            return PlainTextResponse("async-instance")

    def prefixed(prefix: str, _: Request) -> Response:
        return PlainTextResponse(prefix)

    handlers: dict[str, Callable[[Request], object]] = {
        "bound-sync": Owner().sync,
        "bound-async": Owner().async_,
        "partial": functools.partial(prefixed, "partial"),
        "sync-instance": SyncInstance(),
        "async-instance": AsyncInstance(),
    }
    response = await _endpoint(handlers[form])(_request())
    assert response.body == form.encode()


@pytest.mark.anyio
async def test_sync_wrapper_uses_outer_classification_without_following_wrapped() -> (
    None
):
    loop_thread = threading.get_ident()
    wrapper_thread: int | None = None

    async def inner(_: Request) -> Response:
        return PlainTextResponse("ok")

    @functools.wraps(inner)
    def wrapper(request: Request) -> Awaitable[Response]:
        nonlocal wrapper_thread
        wrapper_thread = threading.get_ident()
        return inner(request)

    response = await _endpoint(wrapper)(_request())
    assert response.body == b"ok"
    assert wrapper_thread is not None and wrapper_thread != loop_thread


@pytest.mark.anyio
async def test_handler_exception_and_worker_traceback_cross_unchanged() -> None:
    class MarkerError(RuntimeError):
        pass

    failure = MarkerError("worker failed")

    def handler(_: Request) -> Response:
        raise failure

    with pytest.raises(MarkerError) as captured:
        await _endpoint(handler)(_request())
    assert captured.value is failure
    assert captured.value.__traceback__ is not None
    frames = [
        frame.function for frame in inspect.getinnerframes(captured.value.__traceback__)
    ]
    assert "handler" in frames


@pytest.mark.anyio
async def test_cancellation_before_offload_does_not_start_sync_handler() -> None:
    called = False

    def handler(_: Request) -> Response:
        nonlocal called
        called = True
        return PlainTextResponse("wrong")

    with anyio.CancelScope() as scope:
        scope.cancel()
        await _endpoint(handler)(_request())
    assert not called


@pytest.mark.anyio
async def test_cancellation_abandons_waiter_and_worker_finishes() -> None:
    entered = threading.Event()
    release = threading.Event()
    finished = threading.Event()

    def handler(_: Request) -> Response:
        entered.set()
        release.wait(timeout=2)
        finished.set()
        return PlainTextResponse("done")

    async def cancel_when_entered(scope: anyio.CancelScope) -> None:
        while not entered.is_set():
            await anyio.sleep(0)
        scope.cancel()

    with anyio.CancelScope() as scope:
        async with anyio.create_task_group() as group:
            group.start_soon(cancel_when_entered, scope)
            await _endpoint(handler)(_request())
    assert not finished.is_set()
    release.set()
    assert await run_sync(finished.wait, 2)


@pytest.mark.anyio
async def test_default_thread_limiter_is_not_mutated() -> None:
    limiter = current_default_thread_limiter()
    before = limiter.total_tokens

    def handler(_: Request) -> Response:
        return PlainTextResponse("ok")

    await _endpoint(handler)(_request())
    assert limiter.total_tokens == before


@pytest.mark.anyio
async def test_non_response_and_parameter_mismatch_use_pyganini014() -> None:
    def handler(_: Request) -> object:
        return object()

    with pytest.raises(DispatchError) as bad_response:
        await _endpoint(handler)(_request())
    assert bad_response.value.code == "PYGANINI014"
    assert bad_response.value.phase == "route-response"

    def good(_: Request) -> Response:
        return PlainTextResponse("ok")

    with pytest.raises(DispatchError) as bad_parameters:
        await _endpoint(good, parameters=("user_id",))(_request())
    assert bad_parameters.value.code == "PYGANINI014"
    assert "parameters" in bad_parameters.value.message


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("kind", "methods", "method", "expected"),
    [
        ("page", ("GET", "HEAD"), "GET", "Starlette Response or Page"),
        (
            "fragment",
            ("GET", "HEAD"),
            "GET",
            "Starlette Response or FragmentResponse",
        ),
        (
            "action",
            ("POST",),
            "POST",
            "Starlette Response, Page, or FragmentResponse",
        ),
    ],
)
async def test_non_response_diagnostic_names_surface_result_contract(
    kind: str,
    methods: tuple[str, ...],
    method: str,
    expected: str,
) -> None:
    def handler(_: Request) -> object:
        return object()

    with pytest.raises(DispatchError) as captured:
        await _endpoint(handler, kind=kind, methods=methods)(_request(method))
    assert expected in captured.value.message


@pytest.mark.anyio
async def test_head_suppresses_streamed_body_and_runs_background() -> None:
    background_ran = False

    def background() -> None:
        nonlocal background_ran
        background_ran = True

    class ChunkedResponse(Response):
        async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
            await send(
                {
                    "type": "http.response.start",
                    "status": self.status_code,
                    "headers": self.raw_headers,
                }
            )
            await send(
                {"type": "http.response.body", "body": b"one", "more_body": True}
            )
            await send(
                {"type": "http.response.body", "body": b"two", "more_body": False}
            )
            if self.background is not None:
                await self.background()

    async def handler(_: Request) -> Response:
        return ChunkedResponse(background=BackgroundTask(background))

    response = await _endpoint(handler)(_request("HEAD"))
    messages: list[dict[str, object]] = []

    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict[str, object]) -> None:
        messages.append(message)

    await response(_request("HEAD").scope, cast(Any, receive), cast(Any, send))
    bodies = [
        message["body"]
        for message in messages
        if message["type"] == "http.response.body"
    ]
    assert bodies and set(bodies) == {b""}
    assert background_ran


def _rendering(
    name: str = "routes/page.jinja", *, kind: str = "page"
) -> dict[str, Any]:
    marker = (
        kind,
        kind,
        "/users/{user_id}",
        name,
        f"app/{name}:1:1",
        "none",
        "app/routes/users/route.py:4:20",
        "app.routes.users.route:page",
        "none",
    )
    return {
        "GET": ((name, "app/" + name, 1, 1, None, None), (), marker, (), ()),
        "POST": ((name, "app/" + name, 1, 1, None, None), (), marker, (), ()),
    }


def _rendering_with_layout(
    name: str = "routes/page.jinja", *, kind: str = "page"
) -> dict[str, Any]:
    layout = (
        "app/routes/layout.py",
        2,
        3,
        "/",
        ("routes/layout.jinja", "app/routes/layout.jinja", 1, 1, None, None),
    )
    marker = _rendering(name, kind=kind)["GET"][2]
    layout_marker = (
        "layout",
        "action-page" if kind == "action" else "page",
        "/",
        "routes/layout.jinja",
        "app/routes/layout.jinja:1:1",
        "none",
        "app/routes/layout.py:2:3",
        "none",
        "none",
    )
    facts = (
        (name, "app/" + name, 1, 1, None, None),
        (layout,),
        marker,
        (layout_marker,),
        (),
    )
    return {"GET": facts, "POST": facts}


@pytest.mark.parametrize(
    ("field", "wrong"),
    [
        pytest.param(0, "action", id="kind"),
        pytest.param(1, "fragment", id="surface"),
        pytest.param(2, "/wrong", id="route"),
        pytest.param(3, "routes/wrong.jinja", id="template"),
        pytest.param(4, "app/routes/wrong.jinja:1:1", id="template-source"),
        pytest.param(5, "app/routes/route.py:9:9", id="template-declaration"),
        pytest.param(6, "app/routes/users/route.py:999:999", id="owner"),
        pytest.param(7, "app.routes.users.route:wrong", id="handler"),
        pytest.param(8, "contact_directory:/", id="mount"),
    ],
)
def test_inspection_marker_facts_fail_closed_at_endpoint_construction(
    field: int,
    wrong: str,
) -> None:
    template = ("routes/page.jinja", "app/routes/page.jinja", 1, 1, None, None)
    marker_values = [
        "page",
        "page",
        "/right",
        "routes/page.jinja",
        "app/routes/page.jinja:1:1",
        "none",
        "app/routes/users/route.py:1:1",
        "app.routes.users.route:page",
        "none",
    ]
    marker_values[field] = wrong
    marker = cast(Any, tuple(marker_values))

    with pytest.raises(DispatchError) as captured:
        build_endpoint(
            handlers={"GET": lambda _: Page()},
            evidence={
                "GET": cast(
                    Any,
                    _evidence(path="/right", methods=("GET", "HEAD")),
                )
            },
            parameters=(),
            rendering={"GET": (template, (), marker, (), ())},
            embedded_expectations={"GET": ()},
        )

    assert captured.value.code == "PYGANINI015"
    assert captured.value.phase == "render-configuration"
    assert captured.value.message == (
        "generated inspection facts disagree with captured route facts"
    )
    assert captured.value.path == "app/routes/users/route.py"
    assert captured.value.details == tuple(
        sorted(
            (
                "method: GET",
                "route kind: page",
                "route path: /right",
                "route handler: app.routes.users.route:page",
                f"inspection marker: {marker!r}",
            )
        )
    )
    assert wrong in "\n".join(captured.value.details)


@pytest.mark.parametrize(
    ("field", "wrong"),
    [
        pytest.param(0, "page", id="kind"),
        pytest.param(1, "action-page", id="surface"),
        pytest.param(2, "/wrong", id="route"),
        pytest.param(3, "routes/wrong.jinja", id="template"),
        pytest.param(4, "app/routes/wrong.jinja:1:1", id="template-source"),
        pytest.param(5, "app/routes/layout.py:9:9", id="template-declaration"),
        pytest.param(6, "app/routes/layout.py:999:999", id="owner"),
        pytest.param(7, "app.routes.layouts:wrong", id="handler"),
        pytest.param(8, "contact_directory:/", id="mount"),
    ],
)
def test_inspection_layout_facts_fail_closed_at_endpoint_construction(
    field: int,
    wrong: str,
) -> None:
    template = ("routes/page.jinja", "app/routes/page.jinja", 1, 1, None, None)
    marker = (
        "page",
        "page",
        "/right",
        "routes/page.jinja",
        "app/routes/page.jinja:1:1",
        "none",
        "app/routes/users/route.py:1:1",
        "app.routes.users.route:page",
        "none",
    )
    layout = (
        "app/routes/layout.py",
        1,
        1,
        "/",
        ("routes/layout.jinja", "app/routes/layout.jinja", 1, 1, None, None),
    )
    layout_marker_values = [
        "layout",
        "page",
        "/",
        "routes/layout.jinja",
        "app/routes/layout.jinja:1:1",
        "none",
        "app/routes/layout.py:1:1",
        "none",
        "none",
    ]
    layout_marker_values[field] = wrong
    wrong_layout_marker = cast(Any, tuple(layout_marker_values))

    with pytest.raises(DispatchError) as captured:
        build_endpoint(
            handlers={"GET": lambda _: Page()},
            evidence={
                "GET": cast(
                    Any,
                    _evidence(path="/right", methods=("GET", "HEAD")),
                )
            },
            parameters=(),
            rendering={
                "GET": (
                    template,
                    (layout,),
                    marker,
                    (wrong_layout_marker,),
                    (),
                )
            },
            embedded_expectations={"GET": ()},
        )
    assert captured.value.code == "PYGANINI015"
    assert captured.value.phase == "render-configuration"
    assert captured.value.path == "app/routes/users/route.py"
    assert captured.value.message == (
        "generated inspection facts disagree with captured route facts"
    )
    assert captured.value.details == tuple(
        sorted(
            (
                "method: GET",
                "route kind: page",
                "route path: /right",
                "route handler: app.routes.users.route:page",
                f"inspection marker: {marker!r}",
            )
        )
    )


@pytest.mark.parametrize(
    "rendering",
    [{"GET": (None, ())}, {}],
)
def test_endpoint_inspection_facts_cannot_use_obsolete_shape_or_be_omitted(
    rendering: dict[str, Any],
) -> None:
    with pytest.raises(DispatchError) as captured:
        build_endpoint(
            handlers={"GET": lambda _: PlainTextResponse("unused")},
            evidence={
                "GET": cast(Any, _evidence(path="/right", methods=("GET", "HEAD")))
            },
            parameters=(),
            rendering=rendering,
            embedded_expectations={"GET": ()},
        )

    assert captured.value.code == "PYGANINI015"
    assert captured.value.phase == "render-configuration"


def test_endpoint_evidence_cannot_use_obsolete_shape() -> None:
    with pytest.raises(DispatchError) as captured:
        build_endpoint(
            handlers={"GET": lambda _: PlainTextResponse("unused")},
            evidence={
                "GET": cast(
                    Any,
                    (
                        "page",
                        "/right",
                        ("GET", "HEAD"),
                        "app/routes/route.py",
                        1,
                        1,
                        "app.routes.handlers",
                        "page",
                        "page",
                    ),
                )
            },
            parameters=(),
            rendering={"GET": (None, (), None, (), ())},
            embedded_expectations={"GET": ()},
        )

    assert captured.value.code == "PYGANINI015"
    assert captured.value.phase == "render-configuration"


@pytest.mark.parametrize(
    "malformed_shape",
    [
        "endpoint-marker",
        "layout-marker",
        "embedded-marker",
        "template",
        "layout",
        "embedded-entry",
    ],
)
def test_malformed_endpoint_marker_arity_uses_render_configuration_diagnostic(
    malformed_shape: str,
) -> None:
    template = ("routes/page.jinja", "app/routes/page.jinja", 1, 1, None, None)
    marker = (
        "page",
        "page",
        "/users/{user_id}",
        "routes/page.jinja",
        "app/routes/page.jinja:1:1",
        "none",
        "app/routes/users/route.py:4:20",
        "app.routes.users.route:page",
        "none",
    )
    layout = (
        "app/routes/layout.py",
        1,
        1,
        "/",
        ("routes/layout.jinja", "app/routes/layout.jinja", 1, 1, None, None),
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
    selected_by_shape = {
        "endpoint-marker": (template, (), marker[:-1], (), ()),
        "layout-marker": (
            template,
            (layout,),
            marker,
            (layout_marker[:-1],),
            (),
        ),
        "embedded-marker": (template, (), marker, (), (("/table", marker[:-1]),)),
        "template": (template[:-1], (), marker, (), ()),
        "layout": (template, (layout[:-1],), marker, (layout_marker,), ()),
        "embedded-entry": (template, (), marker, (), (("/table",),)),
    }
    selected = selected_by_shape[malformed_shape]
    with pytest.raises(DispatchError) as captured:
        build_endpoint(
            handlers={"GET": lambda _: Page()},
            evidence={"GET": cast(Any, _evidence())},
            parameters=(),
            rendering={"GET": cast(Any, selected)},
            embedded_expectations={"GET": cast(Any, selected[4])},
        )

    assert captured.value.code == "PYGANINI015"
    assert captured.value.phase == "render-configuration"
    assert captured.value.path == "app/_pyganini/asgi.py"
    assert captured.value.message == (
        "generated inspection facts disagree with captured route facts"
    )
    fact_name = (
        "embedded expectations"
        if malformed_shape in {"embedded-marker", "embedded-entry"}
        else "rendering facts"
    )
    facts = selected[4] if fact_name == "embedded expectations" else selected
    assert captured.value.details == tuple(
        sorted(("method: GET", f"{fact_name}: {facts!r}"))
    )


@pytest.mark.parametrize(
    ("field", "wrong"),
    [
        pytest.param(0, "page", id="kind"),
        pytest.param(1, "fragment", id="surface"),
        pytest.param(2, "/wrong", id="route"),
        pytest.param(3, "routes/wrong.jinja", id="template"),
        pytest.param(4, "app/routes/wrong.jinja:1:1", id="template-source"),
        pytest.param(5, "app/routes/route.py:9:9", id="template-declaration"),
        pytest.param(6, "app/routes/route.py:999:999", id="owner"),
        pytest.param(7, "app.routes.handlers:wrong", id="handler"),
        pytest.param(8, "directory:/", id="mount"),
    ],
)
def test_embedded_fragment_facts_fail_closed_at_endpoint_construction(
    field: int,
    wrong: str,
) -> None:
    template = ("routes/page.jinja", "app/routes/page.jinja", 1, 1, None, None)
    marker = (
        "page",
        "page",
        "/right",
        "routes/page.jinja",
        "app/routes/page.jinja:1:1",
        "none",
        "app/routes/users/route.py:1:1",
        "app.routes.users.route:page",
        "none",
    )
    fragment = [
        "fragment",
        "embedded-fragment",
        "/table",
        "routes/table.jinja",
        "app/routes/table.jinja:1:1",
        "app/routes/route.py:3:1",
        "app/routes/route.py:1:1",
        "app.routes.handlers:table",
        "none",
    ]
    fragment[field] = wrong
    fragment_template = (
        "routes/table.jinja",
        "app/routes/table.jinja",
        1,
        1,
        None,
        ("app/routes/route.py", 3, 1),
    )
    fragment_evidence = (
        "fragment",
        "/table",
        ("GET", "HEAD"),
        "app/routes/route.py",
        3,
        1,
        "app.routes.handlers",
        "table",
        "table",
        "app/routes/route.py",
        None,
        None,
        1,
        1,
        "/table",
    )

    with pytest.raises(DispatchError) as captured:
        build_endpoint(
            handlers={"GET": lambda _: Page()},
            evidence={
                "GET": cast(Any, _evidence(path="/right", methods=("GET", "HEAD")))
            },
            parameters=(),
            rendering={
                "GET": (
                    template,
                    (),
                    marker,
                    (),
                    (("/table", cast(Any, tuple(fragment))),),
                )
            },
            embedded_expectations={
                "GET": (("/table", cast(Any, fragment_evidence), fragment_template),)
            },
        )

    assert captured.value.code == "PYGANINI015"
    assert captured.value.phase == "render-configuration"
    assert captured.value.path == "app/routes/users/route.py"
    assert captured.value.message == (
        "generated inspection facts disagree with captured route facts"
    )
    assert captured.value.details == tuple(
        sorted(
            (
                "method: GET",
                "route kind: page",
                "route path: /right",
                "route handler: app.routes.users.route:page",
                f"inspection marker: {marker!r}",
            )
        )
    )


def test_coherently_fabricated_embedded_fragment_facts_fail_closed() -> None:
    fabricated = (
        "fragment",
        "embedded-fragment",
        "/not-in-graph",
        "routes/fabricated.jinja",
        "app/routes/fabricated.jinja:1:1",
        "app/routes/fabricated.py:2:1",
        "app/routes/fabricated.py:1:1",
        "app.routes.fabricated:fragment",
        "none",
    )
    rendering = (None, (), None, (), (("/not-in-graph", fabricated),))
    real_template = (
        "routes/table.jinja",
        "app/routes/table.jinja",
        1,
        1,
        None,
        ("app/routes/route.py", 3, 1),
    )
    real_evidence = (
        "fragment",
        "/table",
        ("GET", "HEAD"),
        "app/routes/route.py",
        3,
        1,
        "app.routes.handlers",
        "table",
        "table",
        "app/routes/route.py",
        None,
        None,
        1,
        1,
        "/table",
    )

    with pytest.raises(DispatchError) as captured:
        build_endpoint(
            handlers={"GET": lambda _: Page()},
            evidence={"GET": cast(Any, _evidence(path="/right"))},
            parameters=(),
            rendering={"GET": cast(Any, rendering)},
            embedded_expectations={
                "GET": (("/table", cast(Any, real_evidence), real_template),)
            },
        )

    assert captured.value.code == "PYGANINI015"
    assert captured.value.phase == "render-configuration"


@pytest.mark.parametrize("defect", ["noncanonical-local-path", "other-owner"])
def test_embedded_fragment_expectation_must_match_enclosing_selection(
    defect: str,
) -> None:
    enclosing = cast(Any, _evidence(path="/users"))
    fragment_evidence = list(_evidence(kind="fragment", path="/users/table"))
    fragment_evidence[7] = "table"
    fragment_evidence[8] = "table"
    fragment_evidence[14] = "/users"
    local_path = "/table"
    if defect == "noncanonical-local-path":
        local_path = "//table"
    else:
        fragment_evidence[9] = "app/routes/other/route.py"
    fragment_template = (
        "routes/table.jinja",
        "app/routes/table.jinja",
        1,
        1,
        None,
        None,
    )
    fragment_marker = (
        "fragment",
        "embedded-fragment",
        "/users/table",
        "routes/table.jinja",
        "app/routes/table.jinja:1:1",
        "none",
        (
            "app/routes/other/route.py:4:20"
            if defect == "other-owner"
            else "app/routes/users/route.py:4:20"
        ),
        "app.routes.users.route:table",
        "none",
    )

    with pytest.raises(DispatchError) as captured:
        build_endpoint(
            handlers={"GET": lambda _: Page()},
            evidence={"GET": enclosing},
            parameters=(),
            rendering={"GET": (None, (), None, (), ((local_path, fragment_marker),))},
            embedded_expectations={
                "GET": (
                    (
                        local_path,
                        cast(Any, tuple(fragment_evidence)),
                        fragment_template,
                    ),
                )
            },
        )

    assert captured.value.code == "PYGANINI015"
    assert captured.value.phase == "render-configuration"


@pytest.mark.parametrize(
    "corruption",
    [
        "wrong-route-without-callback",
        "wrong-route-with-callback",
        "wrong-marker-owner",
        "obsolete-rendering-shape",
        "missing-owner",
        "missing-rendering",
        "malformed-owner-shape",
    ],
)
def test_root_error_inspection_corruptions_have_exact_diagnostics(
    corruption: str,
) -> None:
    page_template = (
        "routes/error_page.jinja",
        "app/routes/error_page.jinja",
        1,
        1,
        None,
        ("app/routes/route.py", 3, 25),
    )
    wrong_root_marker = (
        "page",
        "root-error-page",
        "/wrong",
        "routes/error_page.jinja",
        "app/routes/error_page.jinja:1:1",
        "app/routes/route.py:3:25",
        "app/routes/route.py:1:1",
        "route_error_handler",
        "none",
    )

    def error_handler(_: Request, __: Exception) -> Page:
        return Page(status_code=500)

    wrong_root_owner = (
        *wrong_root_marker[:2],
        "/",
        *wrong_root_marker[3:6],
        "app/routes/route.py:999:999",
        *wrong_root_marker[7:],
    )
    correct_root_marker = (*wrong_root_marker[:2], "/", *wrong_root_marker[3:])
    correct_rendering = (
        page_template,
        None,
        (),
        correct_root_marker,
        None,
        (),
    )
    selected_marker = wrong_root_marker
    raw_rendering: tuple[Any, ...] = (
        page_template,
        None,
        (),
        selected_marker,
        None,
        (),
    )
    owner: Any = ("app/routes/route.py", 1, 1)
    callback = error_handler if corruption == "wrong-route-with-callback" else None
    if corruption == "wrong-marker-owner":
        raw_rendering = (
            page_template,
            None,
            (),
            wrong_root_owner,
            None,
            (),
        )
        selected_marker = wrong_root_owner
    elif corruption == "obsolete-rendering-shape":
        raw_rendering = (page_template, None, ())
        owner = None
        callback = error_handler
    elif corruption == "missing-owner":
        raw_rendering = correct_rendering
        owner = None
    elif corruption == "missing-rendering":
        raw_rendering = (None, None, (), None, None, ())
    elif corruption == "malformed-owner-shape":
        raw_rendering = correct_rendering
        owner = ("app/routes/route.py", 1)

    with pytest.raises(DispatchError) as captured:
        prepare_route_error_handler(
            callback,
            rendering=cast(Any, raw_rendering),
            owner=cast(Any, owner),
        )

    if corruption in {
        "wrong-route-without-callback",
        "wrong-route-with-callback",
        "wrong-marker-owner",
    }:
        expected_details = (
            "error route: /",
            "page surface: root-error-page",
            "fragment surface: root-error-fragment",
            f"page marker: {selected_marker!r}",
            "fragment marker: None",
        )
    elif corruption == "malformed-owner-shape":
        expected_details = (f"root error owner: {owner!r}",)
    elif corruption == "obsolete-rendering-shape":
        expected_details = (f"root error rendering facts: {raw_rendering!r}",)
    else:
        expected_details = (
            f"root error owner: {owner!r}",
            f"root error rendering facts: {raw_rendering!r}",
        )
    assert captured.value.code == "PYGANINI015"
    assert captured.value.phase == "render-configuration"
    assert captured.value.path == "app/_pyganini/asgi.py"
    assert captured.value.message == (
        "generated inspection facts disagree with captured route facts"
    )
    assert captured.value.details == tuple(sorted(expected_details))


def test_matched_error_inspection_corruption_has_exact_diagnostic() -> None:
    page_template = (
        "routes/error_page.jinja",
        "app/routes/error_page.jinja",
        1,
        1,
        None,
        ("app/routes/route.py", 3, 25),
    )
    root_marker = (
        "page",
        "root-error-page",
        "/",
        "routes/error_page.jinja",
        "app/routes/error_page.jinja:1:1",
        "app/routes/route.py:3:25",
        "app/routes/route.py:1:1",
        "route_error_handler",
        "none",
    )

    def error_handler(_: Request, __: Exception) -> Page:
        return Page(status_code=500)

    prepared = prepare_route_error_handler(
        error_handler,
        rendering=(page_template, None, (), root_marker, None, ()),
        owner=("app/routes/route.py", 1, 1),
    )
    assert prepared is not None
    wrong_matched_marker = (
        "page",
        "matched-error-page",
        "/wrong",
        "routes/error_page.jinja",
        "app/routes/error_page.jinja:1:1",
        "app/routes/route.py:3:25",
        "app/routes/users/route.py:4:20",
        "route_error_handler",
        "none",
    )
    with pytest.raises(DispatchError) as matched:
        PathPriorityRoute(
            "/users/{user_id}",
            _endpoint(
                lambda _: Page(),
                error_rendering=(
                    page_template,
                    None,
                    (),
                    root_marker,
                    None,
                    (),
                ),
            ),
            methods=("GET",),
            error_handler=prepared,
            error_layouts={"GET": ()},
            error_inspection={"GET": (wrong_matched_marker, None, ())},
            error_evidence={"GET": cast(Any, _evidence())},
            error_templates=(page_template, None),
        )
    assert matched.value.code == "PYGANINI015"
    assert matched.value.phase == "render-configuration"
    assert matched.value.path == "app/_pyganini/asgi.py"
    assert matched.value.message == (
        "generated inspection facts disagree with captured route facts"
    )
    assert matched.value.details == tuple(
        sorted(
            (
                "error route: /users/{user_id}",
                "page surface: matched-error-page",
                "fragment surface: matched-error-fragment",
                f"page marker: {wrong_matched_marker!r}",
                "fragment marker: None",
            )
        )
    )


@pytest.mark.parametrize(
    ("field", "wrong"),
    [
        pytest.param(0, "fragment", id="kind"),
        pytest.param(1, "root-error-page", id="surface"),
        pytest.param(2, "/wrong", id="route"),
        pytest.param(3, "routes/wrong.jinja", id="template"),
        pytest.param(4, "app/routes/wrong.jinja:1:1", id="template-source"),
        pytest.param(5, "app/routes/route.py:9:9", id="template-declaration"),
        pytest.param(6, "app/routes/users/route.py:999:999", id="owner"),
        pytest.param(7, "wrong_error_handler", id="handler"),
        pytest.param(8, "directory:/", id="mount"),
    ],
)
@pytest.mark.parametrize("callback", [False, True])
def test_matched_error_inspection_correlates_template_owner_and_mount(
    field: int,
    wrong: str,
    callback: bool,
) -> None:
    page_template = (
        "routes/error_page.jinja",
        "app/routes/error_page.jinja",
        1,
        1,
        None,
        ("app/routes/route.py", 3, 25),
    )
    marker = [
        "page",
        "matched-error-page",
        "/users/{user_id}",
        "routes/error_page.jinja",
        "app/routes/error_page.jinja:1:1",
        "app/routes/route.py:3:25",
        "app/routes/users/route.py:4:20",
        "route_error_handler",
        "none",
    ]
    marker[field] = wrong

    def handler(_: Request, __: Exception) -> Page:
        return Page(status_code=500)

    root_marker = (
        "page",
        "root-error-page",
        "/",
        "routes/error_page.jinja",
        "app/routes/error_page.jinja:1:1",
        "app/routes/route.py:3:25",
        "app/routes/route.py:1:1",
        "route_error_handler",
        "none",
    )
    root_rendering = (page_template, None, (), root_marker, None, ())
    prepared = (
        prepare_route_error_handler(
            handler,
            rendering=root_rendering,
            owner=("app/routes/route.py", 1, 1),
        )
        if callback
        else None
    )
    with pytest.raises(DispatchError) as captured:
        PathPriorityRoute(
            "/users/{user_id}",
            _endpoint(lambda _: Page(), error_rendering=root_rendering),
            methods=("GET",),
            error_handler=prepared,
            error_layouts={"GET": ()},
            error_inspection={"GET": (cast(Any, tuple(marker)), None, ())},
            error_evidence={"GET": cast(Any, _evidence())},
            error_templates=(page_template, None),
        )

    assert captured.value.code == "PYGANINI015"
    assert captured.value.phase == "render-configuration"
    assert captured.value.path == "app/_pyganini/asgi.py"
    assert captured.value.message == (
        "generated inspection facts disagree with captured route facts"
    )
    assert captured.value.details == tuple(
        sorted(
            (
                "error route: /users/{user_id}",
                "page surface: matched-error-page",
                "fragment surface: matched-error-fragment",
                f"page marker: {tuple(marker)!r}",
                "fragment marker: None",
            )
        )
    )


@pytest.mark.parametrize(
    ("field", "wrong"),
    [
        pytest.param(0, "page", id="kind"),
        pytest.param(1, "root-error-fragment", id="surface"),
        pytest.param(2, "/wrong", id="route"),
        pytest.param(3, "routes/wrong.jinja", id="template"),
        pytest.param(4, "app/routes/wrong.jinja:1:1", id="template-source"),
        pytest.param(5, "app/routes/route.py:9:9", id="template-declaration"),
        pytest.param(6, "app/routes/users/route.py:999:999", id="owner"),
        pytest.param(7, "wrong_error_handler", id="handler"),
        pytest.param(8, "directory:/", id="mount"),
    ],
)
@pytest.mark.parametrize("callback", [False, True])
def test_matched_error_fragment_marker_fails_closed_for_every_field(
    field: int,
    wrong: str,
    callback: bool,
) -> None:
    fragment_template = (
        "routes/error_fragment.jinja",
        "app/routes/error_fragment.jinja",
        1,
        1,
        None,
        ("app/routes/route.py", 3, 25),
    )
    marker = [
        "fragment",
        "matched-error-fragment",
        "/users/{user_id}",
        "routes/error_fragment.jinja",
        "app/routes/error_fragment.jinja:1:1",
        "app/routes/route.py:3:25",
        "app/routes/users/route.py:4:20",
        "route_error_handler",
        "none",
    ]
    marker[field] = wrong
    root_marker = (
        "fragment",
        "root-error-fragment",
        "/",
        "routes/error_fragment.jinja",
        "app/routes/error_fragment.jinja:1:1",
        "app/routes/route.py:3:25",
        "app/routes/route.py:1:1",
        "route_error_handler",
        "none",
    )
    root_rendering = (None, fragment_template, (), None, root_marker, ())

    def handler(_: Request, __: Exception) -> FragmentResponse:
        return FragmentResponse(status_code=500)

    prepared = (
        prepare_route_error_handler(
            handler,
            rendering=root_rendering,
            owner=("app/routes/route.py", 1, 1),
        )
        if callback
        else None
    )
    with pytest.raises(DispatchError) as captured:
        PathPriorityRoute(
            "/users/{user_id}",
            _endpoint(lambda _: Page(), error_rendering=root_rendering),
            methods=("GET",),
            error_handler=prepared,
            error_layouts={"GET": ()},
            error_inspection={"GET": (None, cast(Any, tuple(marker)), ())},
            error_evidence={"GET": cast(Any, _evidence())},
            error_templates=(None, fragment_template),
        )

    assert captured.value.code == "PYGANINI015"
    assert captured.value.phase == "render-configuration"
    assert captured.value.path == "app/_pyganini/asgi.py"
    assert captured.value.message == (
        "generated inspection facts disagree with captured route facts"
    )
    assert captured.value.details == tuple(
        sorted(
            (
                "error route: /users/{user_id}",
                "page surface: matched-error-page",
                "fragment surface: matched-error-fragment",
                "page marker: None",
                f"fragment marker: {tuple(marker)!r}",
            )
        )
    )


def test_matched_error_inspection_facts_cannot_be_omitted() -> None:
    page_template = (
        "routes/error_page.jinja",
        "app/routes/error_page.jinja",
        1,
        1,
        None,
        ("app/routes/route.py", 3, 25),
    )
    with pytest.raises(DispatchError) as captured:
        PathPriorityRoute(
            "/right",
            lambda _: PlainTextResponse("unused"),
            methods=("GET",),
            error_evidence={
                "GET": cast(Any, _evidence(path="/right", methods=("GET", "HEAD")))
            },
            error_templates=(page_template, None),
        )

    assert captured.value.code == "PYGANINI015"
    assert captured.value.phase == "render-configuration"

    with pytest.raises(DispatchError) as missing_evidence:
        PathPriorityRoute(
            "/right",
            lambda _: PlainTextResponse("unused"),
            methods=("GET",),
            error_templates=(page_template, None),
        )

    assert missing_evidence.value.code == "PYGANINI015"
    assert missing_evidence.value.phase == "render-configuration"


@pytest.mark.parametrize("callback", [False, True])
def test_matched_error_inspection_requires_every_supported_method(
    callback: bool,
) -> None:
    page_template = (
        "routes/error_page.jinja",
        "app/routes/error_page.jinja",
        1,
        1,
        None,
        ("app/routes/route.py", 3, 25),
    )
    marker = (
        "page",
        "matched-error-page",
        "/right",
        "routes/error_page.jinja",
        "app/routes/error_page.jinja:1:1",
        "app/routes/route.py:3:25",
        "app/routes/users/route.py:4:20",
        "route_error_handler",
        "none",
    )

    def handler(_: Request, __: Exception) -> Page:
        return Page(status_code=500)

    prepared = prepare_route_error_handler(handler) if callback else None
    with pytest.raises(DispatchError) as captured:
        PathPriorityRoute(
            "/right",
            lambda _: PlainTextResponse("unused"),
            methods=("GET", "POST"),
            error_handler=prepared,
            error_layouts={"GET": ()},
            error_inspection={"GET": (marker, None, ())},
            error_evidence={
                "GET": cast(Any, _evidence(path="/right", methods=("GET", "POST")))
            },
            error_templates=(page_template, None),
        )

    assert captured.value.code == "PYGANINI015"
    assert captured.value.phase == "render-configuration"


@pytest.mark.parametrize("callback", [False, True])
def test_matched_error_evidence_must_match_endpoint_evidence(callback: bool) -> None:
    page_template = (
        "routes/error_page.jinja",
        "app/routes/error_page.jinja",
        1,
        1,
        None,
        ("app/routes/route.py", 3, 25),
    )
    wrong_evidence = cast(
        Any,
        _evidence(
            kind="fragment",
            path="/wrong",
            methods=("DELETE",),
            module="app.routes.wrong",
            symbol="wrong",
            binding="wrong",
        ),
    )
    wrong_marker = (
        "page",
        "matched-error-page",
        "/right",
        "routes/error_page.jinja",
        "app/routes/error_page.jinja:1:1",
        "app/routes/route.py:3:25",
        "app/routes/users/route.py:4:20",
        "route_error_handler",
        "none",
    )
    endpoint = _endpoint(lambda _: Page(), methods=("GET", "POST"))
    prepared = (
        prepare_route_error_handler(lambda _request, _error: None) if callback else None
    )

    with pytest.raises(DispatchError) as captured:
        PathPriorityRoute(
            "/right",
            endpoint,
            methods=("GET", "POST"),
            error_handler=prepared,
            error_layouts={"GET": (), "POST": ()},
            error_inspection={
                "GET": (wrong_marker, None, ()),
                "POST": (wrong_marker, None, ()),
            },
            error_evidence={
                "GET": cast(Any, _evidence(path="/right", methods=("GET", "POST"))),
                "POST": wrong_evidence,
            },
            error_templates=(page_template, None),
        )

    assert captured.value.code == "PYGANINI015"
    assert captured.value.phase == "render-configuration"


@pytest.mark.parametrize("callback", [False, True])
def test_matched_error_templates_must_match_retained_rendering(callback: bool) -> None:
    original_template = (
        "routes/error_page.jinja",
        "app/routes/error_page.jinja",
        1,
        1,
        None,
        None,
    )
    other_template = (
        "routes/other_error.jinja",
        "app/routes/other_error.jinja",
        1,
        1,
        None,
        None,
    )
    root_marker = (
        "page",
        "root-error-page",
        "/",
        "routes/error_page.jinja",
        "app/routes/error_page.jinja:1:1",
        "none",
        "app/routes/route.py:1:1",
        "route_error_handler",
        "none",
    )
    matched_marker = (
        "page",
        "matched-error-page",
        "/users/{user_id}",
        "routes/other_error.jinja",
        "app/routes/other_error.jinja:1:1",
        "none",
        "app/routes/users/route.py:4:20",
        "route_error_handler",
        "none",
    )
    root_rendering = (original_template, None, (), root_marker, None, ())
    prepared = (
        prepare_route_error_handler(
            lambda _request, _error: Page(status_code=500),
            rendering=root_rendering,
            owner=("app/routes/route.py", 1, 1),
        )
        if callback
        else None
    )
    endpoint = _endpoint(
        lambda _: Page(),
        error_rendering=root_rendering,
    )

    with pytest.raises(DispatchError) as captured:
        PathPriorityRoute(
            "/users/{user_id}",
            endpoint,
            methods=("GET",),
            error_handler=prepared,
            error_layouts={"GET": ()},
            error_inspection={"GET": (matched_marker, None, ())},
            error_evidence={"GET": cast(Any, _evidence())},
            error_templates=(other_template, None),
        )

    assert captured.value.code == "PYGANINI015"
    assert captured.value.phase == "render-configuration"


@pytest.mark.parametrize("retained_authority", ["empty", "missing"])
def test_matched_error_templates_require_endpoint_retained_authority(
    retained_authority: str,
) -> None:
    page_template = (
        "routes/error_page.jinja",
        "app/routes/error_page.jinja",
        1,
        1,
        None,
        None,
    )
    root_marker = (
        "page",
        "root-error-page",
        "/",
        "routes/error_page.jinja",
        "app/routes/error_page.jinja:1:1",
        "none",
        "app/routes/route.py:1:1",
        "route_error_handler",
        "none",
    )
    matched_marker = (
        "page",
        "matched-error-page",
        "/users/{user_id}",
        "routes/error_page.jinja",
        "app/routes/error_page.jinja:1:1",
        "none",
        "app/routes/users/route.py:4:20",
        "route_error_handler",
        "none",
    )
    root_rendering = (page_template, None, (), root_marker, None, ())
    prepared = prepare_route_error_handler(
        lambda _request, _error: Page(status_code=500),
        rendering=root_rendering,
        owner=("app/routes/route.py", 1, 1),
    )
    assert prepared is not None
    endpoint = _endpoint(lambda _: Page())
    if retained_authority == "missing":
        delattr(endpoint, "__pyganini_error_rendering__")

    with pytest.raises(DispatchError) as captured:
        PathPriorityRoute(
            "/users/{user_id}",
            endpoint,
            methods=("GET",),
            error_handler=prepared,
            error_layouts={"GET": ()},
            error_inspection={"GET": (matched_marker, None, ())},
            error_evidence={"GET": cast(Any, _evidence())},
            error_templates=(page_template, None),
        )

    assert captured.value.code == "PYGANINI015"
    assert captured.value.phase == "render-configuration"


def test_matched_error_layouts_must_match_endpoint_layouts() -> None:
    page_template = (
        "routes/error_page.jinja",
        "app/routes/error_page.jinja",
        1,
        1,
        None,
        None,
    )
    page_marker = (
        "page",
        "matched-error-page",
        "/users/{user_id}",
        "routes/error_page.jinja",
        "app/routes/error_page.jinja:1:1",
        "none",
        "app/routes/users/route.py:4:20",
        "route_error_handler",
        "none",
    )
    fake_layout = (
        "app/routes/fake.py",
        1,
        1,
        "/",
        ("routes/fake.jinja", "app/routes/fake.jinja", 1, 1, None, None),
    )
    fake_layout_marker = (
        "layout",
        "matched-error-page",
        "/",
        "routes/fake.jinja",
        "app/routes/fake.jinja:1:1",
        "none",
        "app/routes/fake.py:1:1",
        "none",
        "none",
    )
    root_marker = (
        "page",
        "root-error-page",
        "/",
        "routes/error_page.jinja",
        "app/routes/error_page.jinja:1:1",
        "none",
        "app/routes/route.py:1:1",
        "route_error_handler",
        "none",
    )
    endpoint = _endpoint(
        lambda _: Page(),
        rendering=_rendering_with_layout(),
        error_rendering=(page_template, None, (), root_marker, None, ()),
    )

    with pytest.raises(DispatchError) as captured:
        PathPriorityRoute(
            "/users/{user_id}",
            endpoint,
            methods=("GET",),
            error_layouts={"GET": (fake_layout,)},
            error_inspection={"GET": (page_marker, None, (fake_layout_marker,))},
            error_evidence={"GET": cast(Any, _evidence())},
            error_templates=(page_template, None),
        )

    assert captured.value.code == "PYGANINI015"
    assert captured.value.phase == "render-configuration"


@pytest.mark.parametrize("callback", [False, True])
@pytest.mark.parametrize(
    "error_templates", [(), (None,), (None, None, None), [None, None]]
)
def test_error_templates_require_exact_structure(
    callback: bool, error_templates: object
) -> None:
    prepared = (
        prepare_route_error_handler(lambda _request, _error: None) if callback else None
    )
    with pytest.raises(DispatchError) as captured:
        PathPriorityRoute(
            "/right",
            _endpoint(lambda _: Page()),
            methods=("GET",),
            error_handler=prepared,
            error_evidence={"GET": cast(Any, _evidence(path="/right"))},
            error_templates=cast(Any, error_templates),
        )

    assert captured.value.code == "PYGANINI015"
    assert captured.value.phase == "render-configuration"


@pytest.mark.parametrize("surface", ["root", "matched", "layout"])
def test_malformed_error_marker_arity_uses_render_configuration_diagnostic(
    surface: str,
) -> None:
    page_template = (
        "routes/error_page.jinja",
        "app/routes/error_page.jinja",
        1,
        1,
        None,
        ("app/routes/route.py", 3, 25),
    )
    root_marker = (
        "page",
        "root-error-page",
        "/",
        "routes/error_page.jinja",
        "app/routes/error_page.jinja:1:1",
        "app/routes/route.py:3:25",
        "app/routes/route.py:1:1",
        "route_error_handler",
        "none",
    )
    if surface == "root":

        def call() -> object:
            return prepare_route_error_handler(
                None,
                rendering=(page_template, None, (), root_marker[:-1], None, ()),
                owner=("app/routes/route.py", 1, 1),
            )

    else:
        marker: tuple[str, ...] = (
            "page",
            "matched-error-page",
            "/right",
            "routes/error_page.jinja",
            "app/routes/error_page.jinja:1:1",
            "app/routes/route.py:3:25",
            "app/routes/users/route.py:4:20",
            "route_error_handler",
            "none",
        )
        layout = (
            "app/routes/layout.py",
            1,
            1,
            "/",
            ("routes/layout.jinja", "app/routes/layout.jinja", 1, 1, None, None),
        )
        layout_marker = (
            "layout",
            "matched-error-page",
            "/",
            "routes/layout.jinja",
            "app/routes/layout.jinja:1:1",
            "none",
            "app/routes/layout.py:1:1",
            "none",
            "none",
        )
        selected_layouts = (layout,) if surface == "layout" else ()
        selected_layout_markers = (layout_marker[:-1],) if surface == "layout" else ()
        selected_marker = marker if surface == "layout" else marker[:-1]

        def call() -> object:
            return PathPriorityRoute(
                "/right",
                lambda _: PlainTextResponse("unused"),
                methods=("GET",),
                error_layouts={"GET": cast(Any, selected_layouts)},
                error_inspection={
                    "GET": (
                        cast(Any, selected_marker),
                        None,
                        cast(Any, selected_layout_markers),
                    )
                },
                error_evidence={"GET": cast(Any, _evidence(path="/right"))},
                error_templates=(page_template, None),
            )

    with pytest.raises(DispatchError) as captured:
        call()

    assert captured.value.code == "PYGANINI015"
    assert captured.value.phase == "render-configuration"


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("kind", "result", "accepted"),
    [
        ("page", Page(), True),
        ("page", FragmentResponse(), False),
        ("fragment", FragmentResponse(), True),
        ("fragment", Page(), False),
        ("action", Page(), True),
        ("action", FragmentResponse(), True),
    ],
)
async def test_render_value_surface_matrix(
    kind: str, result: object, accepted: bool
) -> None:
    def handler(_: Request) -> object:
        return result

    method = "POST" if kind == "action" else "GET"
    methods = ("POST",) if kind == "action" else ("GET", "HEAD")
    environment = create_environment(
        loader=DictLoader({"routes/page.jinja": "rendered"})
    )
    endpoint = _endpoint(
        handler,
        kind=kind,
        methods=methods,
        rendering=(
            _rendering(kind=kind) if accepted else _rendering_with_layout(kind=kind)
        ),
        environment=environment,
    )
    if accepted:
        response = await endpoint(_request(method))
        assert response.body == b"rendered"
    else:
        with pytest.raises(DispatchError) as captured:
            await endpoint(_request(method))
        assert captured.value.code == "PYGANINI014"
        assert captured.value.phase == "route-response"
        assert "wrong surface kind" in captured.value.message
        assert "template: routes/page.jinja" in captured.value.details
        assert "template source: app/routes/page.jinja:1:1" in captured.value.details
        expected_chain = (
            "selected layout chain: / (app/routes/layout.py:2:3)"
            if isinstance(result, Page)
            else "selected layout chain: <none>"
        )
        assert expected_chain in captured.value.details


@pytest.mark.anyio
async def test_render_value_requires_declared_template_and_validated_environment() -> (
    None
):
    def handler(_: Request) -> Page:
        return Page()

    with pytest.raises(DispatchError, match="declared template") as missing_template:
        await _endpoint(handler)(_request())
    assert missing_template.value.code == "PYGANINI014"

    with pytest.raises(DispatchError, match="validated Jinja") as missing_environment:
        await _endpoint(handler, rendering=_rendering())(_request())
    assert missing_environment.value.code == "PYGANINI014"


@pytest.mark.anyio
async def test_direct_response_bypasses_rendering_even_with_template() -> None:
    class FailingLoader(DictLoader):
        def get_source(self, environment: Environment, template: str) -> Any:
            raise AssertionError("Jinja must not load for a direct response")

    response = PlainTextResponse("direct", status_code=202, headers={"x-direct": "yes"})

    def handler(_: Request) -> Response:
        return response

    endpoint = _endpoint(
        handler,
        rendering=_rendering(),
        environment=create_environment(loader=FailingLoader({})),
    )
    assert await endpoint(_request()) is response


@pytest.mark.anyio
async def test_direct_response_escape_hatch_preserves_low_level_response_types(
    tmp_path: Path,
) -> None:
    file_path = tmp_path / "download.txt"
    file_path.write_text("file", encoding="ascii")
    responses: tuple[Response, ...] = (
        RedirectResponse("/next", status_code=303),
        PlainTextResponse("plain"),
        Response(status_code=204),
        StreamingResponse(iter((b"one", b"two"))),
        FileResponse(file_path),
        Response("background", background=BackgroundTask(lambda: None)),
    )
    for response in responses:

        def handler(_: Request, selected: Response = response) -> Response:
            return selected

        endpoint = _endpoint(
            handler,
            rendering=_rendering(),
            environment=create_environment(loader=DictLoader({})),
        )
        assert await endpoint(_request()) is response


@pytest.mark.anyio
async def test_render_contract_and_jinja_failures_are_localized() -> None:
    invalid = Page()
    object.__setattr__(invalid, "status_code", 204)

    def bad_value(_: Request) -> Page:
        return invalid

    environment = create_environment(
        loader=DictLoader({"routes/page.jinja": "{{ missing }}"})
    )
    rendering = {
        "GET": (
            (
                "routes/page.jinja",
                "app/routes/page.jinja",
                1,
                1,
                None,
                ("app/routes/route.py", 4, 10),
            ),
            (
                (
                    "app/routes/layout.py",
                    2,
                    3,
                    "/",
                    (
                        "routes/layout.jinja",
                        "app/routes/layout.jinja",
                        1,
                        1,
                        None,
                        None,
                    ),
                ),
            ),
            (
                "page",
                "page",
                "/users/{user_id}",
                "routes/page.jinja",
                "app/routes/page.jinja:1:1",
                "app/routes/route.py:4:10",
                "app/routes/users/route.py:4:20",
                "app.routes.users.route:page",
                "none",
            ),
            (
                (
                    "layout",
                    "page",
                    "/",
                    "routes/layout.jinja",
                    "app/routes/layout.jinja:1:1",
                    "none",
                    "app/routes/layout.py:2:3",
                    "none",
                    "none",
                ),
            ),
            (),
        ),
    }
    with pytest.raises(DispatchError) as bad_contract:
        await _endpoint(
            bad_value,
            rendering=rendering,
            environment=environment,
        )(_request())
    assert bad_contract.value.code == "PYGANINI014"
    assert isinstance(bad_contract.value.__cause__, ValueError)
    assert (
        "template declaration: app/routes/route.py:4:10" in bad_contract.value.details
    )
    assert "template: routes/page.jinja" in bad_contract.value.details
    assert "template source: app/routes/page.jinja:1:1" in bad_contract.value.details
    assert (
        "selected layout chain: / (app/routes/layout.py:2:3)"
        in bad_contract.value.details
    )

    def missing(_: Request) -> Page:
        return Page()

    with pytest.raises(DispatchError) as bad_template:
        await _endpoint(
            missing,
            rendering=rendering,
            environment=environment,
        )(_request())
    assert bad_template.value.code == "PYGANINI015"
    assert bad_template.value.phase == "render-template"
    assert isinstance(bad_template.value.__cause__, UndefinedError)
    assert "template: routes/page.jinja" in bad_template.value.details
    assert "surface: page" in bad_template.value.details


@pytest.mark.anyio
async def test_shared_template_diagnostics_include_root_and_file_source() -> None:
    def page(_: Request) -> Page:
        return Page()

    environment = create_environment(
        loader=DictLoader({"shared/contact_directory/page.jinja": "{{ missing }}"})
    )
    rendering = {
        "GET": (
            (
                "shared/contact_directory/page.jinja",
                "app/shared/contact_directory/page.jinja",
                1,
                1,
                "shared/contact_directory",
                ("app/routes/settings/users/route.py", 35, 10),
            ),
            (),
            (
                "page",
                "page",
                "/users/{user_id}",
                "shared/contact_directory/page.jinja",
                "app/shared/contact_directory/page.jinja:1:1",
                "app/routes/settings/users/route.py:35:10",
                "app/routes/users/route.py:4:20",
                "app.routes.users.route:page",
                "none",
            ),
            (),
            (),
        ),
    }
    with pytest.raises(DispatchError) as captured:
        await _endpoint(
            page,
            rendering=rendering,
            environment=environment,
        )(_request())

    assert captured.value.code == "PYGANINI015"
    assert (
        "template declaration: app/routes/settings/users/route.py:35:10"
        in captured.value.details
    )
    assert "template root: shared/contact_directory" in captured.value.details
    assert "template: shared/contact_directory/page.jinja" in captured.value.details
    assert (
        "template source: app/shared/contact_directory/page.jinja:1:1"
        in captured.value.details
    )


def test_prepare_environment_creates_default_and_localizes_configuration() -> None:
    environment = prepare_environment(
        create_environment(loader=DictLoader({"routes/page.jinja": "ok"})),
        template_names=("routes/page.jinja",),
        source_path="app/_pyganini/asgi.py",
    )
    assert environment.is_async is False

    invalid = Environment(
        loader=DictLoader({"routes/page.jinja": "ok"}),
        undefined=StrictUndefined,
        autoescape=False,
    )
    with pytest.raises(DispatchError) as captured:
        prepare_environment(
            invalid,
            template_names=("routes/page.jinja",),
            source_path="app/_pyganini/asgi.py",
        )
    assert captured.value.code == "PYGANINI015"
    assert captured.value.phase == "render-configuration"
    assert captured.value.path == "app/_pyganini/asgi.py"
