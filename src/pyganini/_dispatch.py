# pyright: reportPrivateUsage=false

"""Validate and invoke handlers for generated Starlette dispatch."""

from __future__ import annotations

import functools
import inspect
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from importlib import import_module
from types import ModuleType
from typing import Any, Literal, cast

from anyio.to_thread import run_sync as _run_sync
from jinja2 import Environment
from starlette.exceptions import HTTPException
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import BaseRoute, Match
from starlette.routing import Route as StarletteRoute
from starlette.routing import Router as StarletteRouter
from starlette.types import ASGIApp, Lifespan, Message, Receive, Scope, Send

from pyganini._declarations import KitRouteDef, KitRouteMount, RouteDef
from pyganini._navigation import NavigationFact, _prepare_navigation
from pyganini._render import (
    EmbeddedFragmentEvidence,
    FragmentResponse,
    InspectionMarkerEvidence,
    LayoutEvidence,
    Page,
    RenderFailure,
    RouteResponse,
    TemplateEvidence,
    TemplateInspectionMode,
    create_environment,
    render_response,
    validate_environment,
)
from pyganini.request_data import BodyCapture, FormCapture, _capture_request_data

type _Kind = Literal["page", "fragment", "action"]
type _CallableRole = Literal[
    "route handler",
    "kit creator",
    "kit handler",
    "sync request-data action",
    "route error handler",
]
type RouteErrorHandler = Callable[
    [Request, Exception],
    RouteResponse | Awaitable[RouteResponse | None] | None,
]
type _CreatorEvidence = tuple[str, str, str, str, int, int]
type _ExpectedSurface = tuple[
    _Kind,
    str,
    str,
    str,
    tuple[str, ...],
    str,
    str,
    str,
    str,
    int,
    int,
    str | None,
    str,
    str | None,
    str | None,
    tuple[str, tuple[int, ...]] | None,
    tuple[str, int, int] | None,
]
type _RequestDataLiteral = tuple[str, tuple[int, ...]]
type _Evidence = tuple[
    _Kind,
    str,
    tuple[str, ...],
    str,
    int,
    int,
    str,
    str,
    str,
    str,
    str | None,
    str | None,
    int,
    int,
    str,
]
type _RenderFacts = tuple[
    TemplateEvidence | None,
    tuple[LayoutEvidence, ...],
    InspectionMarkerEvidence | None,
    tuple[InspectionMarkerEvidence, ...],
    tuple[EmbeddedFragmentEvidence, ...],
]
type _EmbeddedExpectation = tuple[str, _Evidence, TemplateEvidence]
type _ErrorRenderFacts = tuple[
    TemplateEvidence | None,
    TemplateEvidence | None,
    tuple[LayoutEvidence, ...],
    InspectionMarkerEvidence | None,
    InspectionMarkerEvidence | None,
    tuple[InspectionMarkerEvidence, ...],
]
type _MatchedErrorInspection = tuple[
    InspectionMarkerEvidence | None,
    InspectionMarkerEvidence | None,
    tuple[InspectionMarkerEvidence, ...],
]
type _NavigationDeclaration = tuple[str | None, str | None]
type _DestinationDeclaration = tuple[str, str, str | None]
type _MountSelectionDeclaration = tuple[
    str,
    _NavigationDeclaration | None,
    tuple[_DestinationDeclaration, ...],
]
type _MiddlewareMarkerEvidence = tuple[
    str,
    int,
    int,
    str,
    tuple[tuple[int, int], ...],
]
type _MiddlewareConsumerEvidence = tuple[
    str,
    str,
    str,
    tuple[str, ...],
    str,
    int,
    int,
    str,
    str,
    str,
    tuple[_MiddlewareMarkerEvidence, ...],
]


class DispatchError(RuntimeError):
    """A localized generated-dispatch validation or response failure."""

    def __init__(
        self,
        code: Literal[
            "PYGANINI012",
            "PYGANINI013",
            "PYGANINI014",
            "PYGANINI015",
            "PYGANINI018",
            "PYGANINI019",
        ],
        phase: Literal[
            "route-import",
            "route-callable",
            "route-response",
            "render-configuration",
            "render-template",
            "route-middleware",
            "route-error-handler",
        ],
        path: str,
        message: str,
        *,
        details: Sequence[str] = (),
    ) -> None:
        super().__init__(message)
        self.code = code
        self.phase = phase
        self.path = path
        self.message = message
        self.details = tuple(sorted(details))


@dataclass(frozen=True, slots=True)
class _PreparedRouteErrorHandler:
    handler: Callable[..., object]
    mode: Literal["sync", "async"]
    environment: Environment | None
    page_template: TemplateEvidence | None
    fragment_template: TemplateEvidence | None
    root_layouts: tuple[LayoutEvidence, ...]
    template_inspection: TemplateInspectionMode
    page_marker: InspectionMarkerEvidence | None
    fragment_marker: InspectionMarkerEvidence | None
    root_layout_markers: tuple[InspectionMarkerEvidence, ...]
    source_path: str


@dataclass(frozen=True, slots=True)
class _RouteErrorContract:
    is_http: bool
    expected_status: int
    required_headers: tuple[tuple[str, str], ...]


class _ResponseStartTracker:
    def __init__(self, send: Send) -> None:
        self.started = False
        self._send = send

    async def __call__(self, message: Message) -> None:
        if message["type"] == "http.response.start":
            self.started = True
        await self._send(message)


def _route_error_handler_failure(
    message: str,
    *,
    source_path: str = "app/_pyganini/asgi.py",
    details: Sequence[str] = (),
    cause: BaseException | None = None,
) -> DispatchError:
    error = DispatchError(
        "PYGANINI019",
        "route-error-handler",
        source_path,
        message,
        details=details,
    )
    if cause is not None:
        error.__cause__ = cause
    return error


def prepare_route_error_handler(
    error_handler: RouteErrorHandler | None,
    *,
    environment: Environment | None = None,
    rendering: _ErrorRenderFacts = (None, None, (), None, None, ()),
    template_inspection: TemplateInspectionMode = TemplateInspectionMode.OFF,
    owner: tuple[str, int, int] | None = None,
    source_path: str = "app/_pyganini/asgi.py",
) -> _PreparedRouteErrorHandler | None:
    """Validate and capture one application-supplied route error callback."""
    raw_rendering = cast(tuple[object, ...], rendering)
    if not _is_error_render_facts(raw_rendering):
        _inspection_disagreement(
            source_path=source_path,
            details=(f"root error rendering facts: {raw_rendering!r}",),
        )
    if owner is not None and not _is_position_evidence(owner):
        _inspection_disagreement(
            source_path=source_path,
            details=(f"root error owner: {owner!r}",),
        )
    page_template = cast(TemplateEvidence | None, raw_rendering[0])
    fragment_template = cast(TemplateEvidence | None, raw_rendering[1])
    root_layouts = cast(tuple[LayoutEvidence, ...], raw_rendering[2])
    page_marker = cast(InspectionMarkerEvidence | None, raw_rendering[3])
    fragment_marker = cast(InspectionMarkerEvidence | None, raw_rendering[4])
    root_layout_markers = cast(tuple[InspectionMarkerEvidence, ...], raw_rendering[5])
    has_root_rendering = any(
        (
            page_template is not None,
            fragment_template is not None,
            bool(root_layouts),
            page_marker is not None,
            fragment_marker is not None,
            bool(root_layout_markers),
        )
    )
    if (owner is not None) != has_root_rendering:
        _inspection_disagreement(
            source_path=source_path,
            details=(
                f"root error owner: {owner!r}",
                f"root error rendering facts: {raw_rendering!r}",
            ),
        )
    _validate_error_inspection_facts(
        page_template=page_template,
        fragment_template=fragment_template,
        layouts=root_layouts,
        page_marker=page_marker,
        fragment_marker=fragment_marker,
        layout_markers=root_layout_markers,
        page_surface="root-error-page",
        fragment_surface="root-error-fragment",
        route="/",
        source_path=source_path,
        expected_owner=(None if owner is None else _position_text(*owner)),
    )
    if error_handler is None:
        return None
    details = (
        "callback role: route error handler",
        f"generated source: {source_path}",
    )
    try:
        mode = _callable_mode(
            error_handler,
            source_path=source_path,
            role="route error handler",
            arity=2,
            details=details,
        )
    except DispatchError as error:
        raise _route_error_handler_failure(
            "error handler must be a supported callable accepting (request, error)",
            source_path=source_path,
            details=(*details, error.message),
            cause=error,
        ) from error
    return _PreparedRouteErrorHandler(
        handler=cast(Callable[..., object], error_handler),
        mode=mode,
        environment=environment,
        page_template=page_template,
        fragment_template=fragment_template,
        root_layouts=root_layouts,
        template_inspection=template_inspection,
        page_marker=page_marker,
        fragment_marker=fragment_marker,
        root_layout_markers=root_layout_markers,
        source_path=source_path,
    )


def prepare_template_inspection(
    value: object,
    *,
    source_path: str = "app/_pyganini/asgi.py",
) -> TemplateInspectionMode:
    """Validate one generated router's fixed inspection mode."""
    if not isinstance(value, TemplateInspectionMode):
        raise DispatchError(
            "PYGANINI015",
            "render-configuration",
            source_path,
            "template_inspection must be a TemplateInspectionMode",
        )
    return value


class PathPriorityRoute(StarletteRoute):
    """Keep the first matching graph path ahead of later dynamic routes."""

    def __init__(
        self,
        path: str,
        endpoint: Callable[..., object],
        *,
        methods: Sequence[str] | None = None,
        name: str | None = None,
        include_in_schema: bool = True,
        middleware: Sequence[Middleware] | None = None,
        max_body_size: int | None = None,
        error_handler: _PreparedRouteErrorHandler | None = None,
        error_layouts: Mapping[str, tuple[LayoutEvidence, ...]] | None = None,
        error_inspection: Mapping[str, _MatchedErrorInspection] | None = None,
        error_evidence: Mapping[str, _Evidence] | None = None,
        error_templates: tuple[TemplateEvidence | None, TemplateEvidence | None] = (
            None,
            None,
        ),
    ) -> None:
        self._error_handler = error_handler
        self._error_layouts = {} if error_layouts is None else dict(error_layouts)
        self._error_inspection = (
            {} if error_inspection is None else dict(error_inspection)
        )
        captured_error_evidence = {} if error_evidence is None else dict(error_evidence)
        raw_endpoint_evidence = getattr(endpoint, "__pyganini_route_evidence__", None)
        captured_endpoint_evidence = (
            {} if raw_endpoint_evidence is None else dict(raw_endpoint_evidence)
        )
        raw_endpoint_rendering = getattr(endpoint, "__pyganini_route_rendering__", None)
        captured_endpoint_rendering = (
            {} if raw_endpoint_rendering is None else dict(raw_endpoint_rendering)
        )
        endpoint_error_rendering = getattr(
            endpoint, "__pyganini_error_rendering__", None
        )
        canonical_methods = (
            [method.upper() for method in methods] if methods is not None else []
        )
        if "GET" in canonical_methods and "HEAD" not in canonical_methods:
            canonical_methods.insert(canonical_methods.index("GET") + 1, "HEAD")
        self._canonical_methods = tuple(canonical_methods)
        expected_error_methods = {
            "GET" if method == "HEAD" else method for method in canonical_methods
        }
        raw_error_templates = _object_tuple(error_templates)
        if (
            raw_error_templates is None
            or len(raw_error_templates) != 2
            or not all(
                template is None or _is_template_evidence(template)
                for template in raw_error_templates
            )
        ):
            _inspection_disagreement(
                source_path=(
                    "app/_pyganini/asgi.py"
                    if error_handler is None
                    else error_handler.source_path
                ),
                details=(f"matched error templates: {error_templates!r}",),
            )
        selected_error_templates = cast(
            tuple[TemplateEvidence | None, TemplateEvidence | None],
            raw_error_templates,
        )
        has_error_rendering = any(
            template is not None for template in selected_error_templates
        )
        actual_method_sets = (
            set(self._error_layouts),
            set(self._error_inspection),
            set(captured_error_evidence),
        )
        for method, selected_evidence in captured_error_evidence.items():
            if not _is_route_evidence(selected_evidence):
                _inspection_disagreement(
                    source_path=(
                        "app/_pyganini/asgi.py"
                        if error_handler is None
                        else error_handler.source_path
                    ),
                    details=(
                        f"matched route: {path}",
                        f"method: {method}",
                        f"captured error evidence: {selected_evidence!r}",
                    ),
                )
        if captured_error_evidence and (
            set(captured_endpoint_evidence) != expected_error_methods
            or any(
                not _is_route_evidence(selected_evidence)
                for selected_evidence in captured_endpoint_evidence.values()
            )
            or any(
                captured_error_evidence.get(method)
                != captured_endpoint_evidence.get(method)
                for method in expected_error_methods
            )
        ):
            _inspection_disagreement(
                source_path=(
                    "app/_pyganini/asgi.py"
                    if error_handler is None
                    else error_handler.source_path
                ),
                details=(
                    f"matched route: {path}",
                    f"endpoint evidence: {captured_endpoint_evidence!r}",
                    f"captured error evidence: {captured_error_evidence!r}",
                ),
            )
        if has_error_rendering and (
            set(captured_endpoint_rendering) != expected_error_methods
            or any(
                not _is_render_facts(rendering)
                for rendering in captured_endpoint_rendering.values()
            )
            or any(
                self._error_layouts.get(method)
                != captured_endpoint_rendering.get(method, (None, (), None, (), ()))[1]
                for method in expected_error_methods
            )
        ):
            _inspection_disagreement(
                source_path=(
                    "app/_pyganini/asgi.py"
                    if error_handler is None
                    else error_handler.source_path
                ),
                details=(
                    f"matched route: {path}",
                    f"endpoint rendering: {captured_endpoint_rendering!r}",
                    f"matched error layouts: {self._error_layouts!r}",
                ),
            )
        retained_error_templates: (
            tuple[TemplateEvidence | None, TemplateEvidence | None] | None
        ) = None
        if endpoint_error_rendering is not None:
            if not _is_error_render_facts(endpoint_error_rendering):
                _inspection_disagreement(
                    source_path="app/_pyganini/asgi.py",
                    details=(
                        f"matched route: {path}",
                        f"retained root error rendering: {endpoint_error_rendering!r}",
                    ),
                )
            retained_error_templates = cast(
                tuple[TemplateEvidence | None, TemplateEvidence | None],
                endpoint_error_rendering[:2],
            )
        if error_handler is not None:
            prepared_templates = (
                error_handler.page_template,
                error_handler.fragment_template,
            )
            if (
                retained_error_templates is not None
                and retained_error_templates != prepared_templates
            ):
                _inspection_disagreement(
                    source_path=error_handler.source_path,
                    details=(
                        f"matched route: {path}",
                        f"retained root templates: {retained_error_templates!r}",
                        f"prepared root templates: {prepared_templates!r}",
                    ),
                )
        if has_error_rendering and retained_error_templates != selected_error_templates:
            _inspection_disagreement(
                source_path=(
                    "app/_pyganini/asgi.py"
                    if error_handler is None
                    else error_handler.source_path
                ),
                details=(
                    f"matched route: {path}",
                    f"retained root templates: {retained_error_templates!r}",
                    f"matched error templates: {selected_error_templates!r}",
                ),
            )
        if (
            has_error_rendering
            and (
                not expected_error_methods
                or any(
                    methods != expected_error_methods for methods in actual_method_sets
                )
            )
        ) or (
            not has_error_rendering
            and (bool(self._error_layouts) or bool(self._error_inspection))
        ):
            _inspection_disagreement(
                source_path=(
                    "app/_pyganini/asgi.py"
                    if error_handler is None
                    else error_handler.source_path
                ),
                details=(
                    f"matched route: {path}",
                    f"inspection methods: {tuple(sorted(self._error_inspection))!r}",
                    f"layout methods: {tuple(sorted(self._error_layouts))!r}",
                    "captured error methods: "
                    f"{tuple(sorted(captured_error_evidence))!r}",
                    f"supported methods: {tuple(sorted(expected_error_methods))!r}",
                ),
            )
        if self._error_inspection:
            for method, inspection in self._error_inspection.items():
                if _object_tuple(inspection) is None or len(inspection) != 3:
                    _inspection_disagreement(
                        source_path=(
                            "app/_pyganini/asgi.py"
                            if error_handler is None
                            else error_handler.source_path
                        ),
                        details=(
                            f"matched route: {path}",
                            f"method: {method}",
                            f"inspection facts: {inspection!r}",
                        ),
                    )
                _validate_error_inspection_facts(
                    page_template=selected_error_templates[0],
                    fragment_template=selected_error_templates[1],
                    layouts=self._error_layouts.get(method, ()),
                    page_marker=inspection[0],
                    fragment_marker=inspection[1],
                    layout_markers=inspection[2],
                    page_surface="matched-error-page",
                    fragment_surface="matched-error-fragment",
                    route=path,
                    source_path=(
                        "app/_pyganini/asgi.py"
                        if error_handler is None
                        else error_handler.source_path
                    ),
                    expected_evidence=captured_error_evidence.get(method),
                )
        selected_endpoint: Callable[..., object] = endpoint
        if error_handler is not None:
            selected_endpoint = _RouteErrorEndpoint(endpoint)
        super().__init__(
            path,
            selected_endpoint,
            methods=methods,
            name=name,
            include_in_schema=include_in_schema,
            middleware=middleware,
            max_body_size=max_body_size,
        )

    def matches(self, scope: Scope) -> tuple[Match, Scope]:
        match, child_scope = super().matches(scope)
        if match is Match.PARTIAL:
            return Match.FULL, child_scope
        return match, child_scope

    async def handle(self, scope: Scope, receive: Receive, send: Send) -> None:
        if self._error_handler is None:
            await super().handle(scope, receive, send)
            return
        if self.methods and scope["method"] not in self.methods:
            request = Request(scope, receive, send)
            error = HTTPException(
                status_code=405,
                headers={"Allow": ", ".join(self._canonical_methods)},
            )
            response = await _call_route_error_handler(
                self._error_handler,
                request,
                error,
                normalized_path=self.path,
                presentation="router error",
            )
            if response is None:
                await super().handle(scope, receive, send)
                return
            await _send_route_error_response(
                request,
                response,
                scope,
                receive,
                send,
            )
            return

        tracked_send = _ResponseStartTracker(send)
        try:
            await self.app(scope, receive, tracked_send)
        except Exception as error:
            if tracked_send.started:
                raise
            request = Request(scope, receive, tracked_send)
            response = await _call_route_error_handler(
                self._error_handler,
                request,
                error,
                normalized_path=self.path,
                layouts=self._error_layouts.get(
                    "GET" if request.method == "HEAD" else request.method,
                    (),
                ),
                inspection=self._error_inspection.get(
                    "GET" if request.method == "HEAD" else request.method
                ),
                presentation="matched route error",
            )
            if response is None:
                raise
            await _send_route_error_response(
                request,
                response,
                scope,
                receive,
                tracked_send,
            )
            if not isinstance(error, HTTPException):
                raise


class _RouteErrorEndpoint:
    def __init__(self, endpoint: Callable[..., object]) -> None:
        self._endpoint = endpoint

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        request = Request(scope, receive, send)
        response = await cast(Callable[[Request], Awaitable[Response]], self._endpoint)(
            request
        )
        await response(scope, receive, send)


class RouteErrorRouter(StarletteRouter):
    """Offer generated 404 errors to one configured application callback."""

    def __init__(
        self,
        *,
        routes: Sequence[BaseRoute] | None = None,
        redirect_slashes: bool = True,
        default: ASGIApp | None = None,
        lifespan: Lifespan[Any] | None = None,
        middleware: Sequence[Middleware] | None = None,
        max_body_size: int | None = None,
        error_handler: _PreparedRouteErrorHandler,
    ) -> None:
        self._error_handler = error_handler
        super().__init__(
            routes=routes,
            redirect_slashes=redirect_slashes,
            default=default,
            lifespan=lifespan,
            middleware=middleware,
            max_body_size=max_body_size,
        )

    async def not_found(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await super().not_found(scope, receive, send)
            return
        request = Request(scope, receive, send)
        response = await _call_route_error_handler(
            self._error_handler,
            request,
            HTTPException(status_code=404),
            presentation="router error",
        )
        if response is None:
            await super().not_found(scope, receive, send)
            return
        await _send_route_error_response(request, response, scope, receive, send)


def _format_details(
    *,
    kind: str,
    path: str,
    methods: tuple[str, ...],
    module: str,
    symbol: str,
    binding: str,
    source: str,
    line: int,
    column: int,
) -> tuple[str, ...]:
    return (
        f"handler binding: {binding}",
        f"handler symbol: {module}.{symbol}",
        f"methods: {', '.join(methods)}",
        f"normalized path: {path}",
        f"source: {source}:{line}:{column}",
        f"surface: {kind}",
    )


def _expected_details(surface: _ExpectedSurface) -> tuple[str, ...]:
    details = _format_details(
        kind=surface[0],
        path=surface[3],
        methods=surface[4],
        module=surface[5],
        symbol=surface[6],
        binding=surface[7],
        source=surface[8],
        line=surface[9],
        column=surface[10],
    )
    if len(surface) < 15 or surface[13] is None:
        return details
    return (
        *details,
        "evidence phase: route-import",
        f"live owner: {surface[12]}",
        f"mount identity: {surface[13]}",
        f"mounted source: {surface[8]}",
        f"selector: {surface[14]}",
        f"final path: {surface[3]}",
    )


def _creator_details(
    creator: _CreatorEvidence,
    surfaces: tuple[_ExpectedSurface, ...] = (),
) -> tuple[str, ...]:
    module, symbol, binding, source, line, column = creator
    details = (
        "callable role: kit creator",
        f"creator binding: {binding}",
        f"creator symbol: {module}.{symbol}",
        f"source: {source}:{line}:{column}",
    )
    return (
        *details,
        *(
            f"creator {detail}"
            for surface in surfaces
            for detail in _expected_details(surface)
        ),
    )


def _evidence_details(surface: _Evidence) -> tuple[str, ...]:
    details = _format_details(
        kind=surface[0],
        path=surface[1],
        methods=surface[2],
        source=surface[3],
        line=surface[4],
        column=surface[5],
        module=surface[6],
        symbol=surface[7],
        binding=surface[8],
    )
    if len(surface) < 12 or surface[10] is None:
        return details
    return (
        *details,
        "evidence phase: request dispatch",
        f"live owner: {surface[9]}",
        f"mount identity: {surface[10]}",
        f"mounted source: {surface[3]}",
        f"selector: {surface[11]}",
        f"final path: {surface[1]}",
    )


def _render_details(
    template: TemplateEvidence | None,
    layouts: tuple[LayoutEvidence, ...],
) -> tuple[str, ...]:
    template_details: tuple[str, ...]
    if template is None:
        template_details = ("declared template: <none>",)
    else:
        environment_name, source, line, column, template_root, declaration = template
        declaration_details: tuple[str, ...] = ()
        if declaration is not None:
            declaration_path, declaration_line, declaration_column = declaration
            declaration_details = (
                f"template declaration: "
                f"{declaration_path}:{declaration_line}:{declaration_column}",
            )
        template_details = (
            *declaration_details,
            f"template root: {template_root or '<none>'}",
            f"template: {environment_name}",
            f"template source: {source}:{line}:{column}",
        )
    chain = " -> ".join(
        f"{route_prefix} ({marker}:{line}:{column})"
        for marker, line, column, route_prefix, _ in layouts
    )
    return (*template_details, f"selected layout chain: {chain or '<none>'}")


def _result_contract(kind: _Kind) -> str:
    if kind == "page":
        return "a Starlette Response or Page"
    if kind == "fragment":
        return "a Starlette Response or FragmentResponse"
    return "a Starlette Response, Page, or FragmentResponse"


def _import_failure(
    source_path: str,
    message: str,
    *,
    surface: _ExpectedSurface | None = None,
    details: Sequence[str] = (),
    cause: BaseException | None = None,
) -> DispatchError:
    surface_details = () if surface is None else _expected_details(surface)
    error = DispatchError(
        "PYGANINI012",
        "route-import",
        source_path,
        message,
        details=(*surface_details, *details),
    )
    if cause is not None:
        error.__cause__ = cause
    return error


def _surface_key(surface: _ExpectedSurface) -> tuple[str, str, str]:
    return surface[0], surface[1], surface[2]


def _surface_request_data(
    surface: _ExpectedSurface,
) -> _RequestDataLiteral | None:
    if len(surface) < 16:
        return None
    return surface[15]


def _request_data_literal(
    value: BodyCapture | FormCapture | None,
) -> _RequestDataLiteral | None:
    if value is None:
        return None
    if isinstance(value, BodyCapture):
        return "body", (value.max_bytes,)
    return (
        "form",
        (value.max_files, value.max_fields, value.max_part_size, value.max_upload_size),
    )


def _request_data_details(
    value: _RequestDataLiteral | BodyCapture | FormCapture,
    *,
    arity: int,
) -> tuple[str, ...]:
    literal = value if isinstance(value, tuple) else _request_data_literal(value)
    assert literal is not None
    return (
        f"request-data mode: {literal[0]}",
        f"expected arity: {arity}",
    )


def _request_data_capture(
    value: _RequestDataLiteral | BodyCapture | FormCapture,
) -> BodyCapture | FormCapture:
    if isinstance(value, (BodyCapture, FormCapture)):
        return value
    mode, limits = value
    if mode == "body":
        return BodyCapture(limits[0])
    if mode == "form":
        return FormCapture(*limits)
    raise ValueError(f"unknown generated request-data mode {mode!r}")


def _runtime_surfaces(
    route: RouteDef | KitRouteDef[object],
) -> dict[
    tuple[str, str, str],
    tuple[Callable[..., object], str | None, _RequestDataLiteral | None],
]:
    surfaces: dict[
        tuple[str, str, str],
        tuple[Callable[..., object], str | None, _RequestDataLiteral | None],
    ] = {}
    if route.page is not None:
        surfaces[("page", "GET", "/")] = route.page, route.page_template, None
    for fragment in route.fragments:
        surfaces[("fragment", "GET", fragment.path)] = (
            fragment.handler,
            fragment.template,
            None,
        )
    for action in route.actions:
        surfaces[("action", action.method, action.path)] = (
            action.handler,
            action.template,
            _request_data_literal(action.request_data),
        )
    return surfaces


def _module_value(module: ModuleType, name: str) -> object:
    values = vars(module)
    if name not in values:
        raise KeyError(name)
    return values[name]


def _middleware_failure(
    source_path: str,
    message: str,
    *,
    details: Sequence[str] = (),
    cause: BaseException | None = None,
) -> DispatchError:
    error = DispatchError(
        "PYGANINI018",
        "route-middleware",
        source_path,
        message,
        details=details,
    )
    if cause is not None:
        error.__cause__ = cause
    return error


def _middleware_marker_label(marker: _MiddlewareMarkerEvidence) -> str:
    source, line, column, route_prefix, entries = marker
    return f"{source}:{line}:{column} route prefix: {route_prefix} entries: {entries!r}"


def _middleware_consumer_details(
    consumers: tuple[_MiddlewareConsumerEvidence, ...],
) -> tuple[str, ...]:
    details: list[str] = []
    for (
        method,
        kind,
        path,
        methods,
        owner,
        owner_line,
        owner_column,
        mount,
        source,
        selector,
        chain,
    ) in consumers:
        details.append(
            f"consumer: {method} {kind}; normalized path: {path}; "
            f"methods: {', '.join(methods)}; "
            f"live owner: {owner}:{owner_line}:{owner_column}; "
            f"mount identity: {mount}; mounted source: {source}; "
            f"selector: {selector}; effective chain: "
            f"{tuple(_middleware_marker_label(marker) for marker in chain)!r}"
        )
    return tuple(details)


def load_middleware(
    *,
    module: str,
    source_path: str,
    route_prefix: str,
    expected_entries: tuple[tuple[int, int], ...],
    binding: tuple[int, int],
    consumers: tuple[_MiddlewareConsumerEvidence, ...],
) -> tuple[Middleware, ...]:
    """Import and validate one generated live route middleware marker."""
    details = (
        f"middleware module: {module}",
        f"middleware source: {source_path}",
        f"middleware binding: {source_path}:{binding[0]}:{binding[1]}",
        f"route prefix: {route_prefix}",
        f"expected entries: {expected_entries!r}",
        *_middleware_consumer_details(consumers),
    )
    try:
        middleware_module = import_module(module)
    except BaseException as error:
        raise _middleware_failure(
            source_path,
            f"cannot import middleware module {module!r}",
            details=details,
            cause=error,
        ) from error
    try:
        value = _module_value(middleware_module, "MIDDLEWARE")
    except KeyError as error:
        raise _middleware_failure(
            source_path,
            "middleware module has no direct MIDDLEWARE binding",
            details=details,
            cause=error,
        ) from error
    if not isinstance(value, tuple):
        cause = TypeError("MIDDLEWARE must be a tuple")
        raise _middleware_failure(
            source_path,
            "runtime MIDDLEWARE binding is not a tuple",
            details=(*details, f"actual type: {type(value).__name__}"),
            cause=cause,
        ) from cause
    middleware_values = cast(tuple[object, ...], value)
    if len(middleware_values) != len(expected_entries):
        tuple_cause = ValueError(
            "expected "
            f"{len(expected_entries)} middleware entries, got {len(middleware_values)}"
        )
        raise _middleware_failure(
            source_path,
            "runtime MIDDLEWARE tuple count disagrees with generated evidence",
            details=(*details, f"actual entries: {len(middleware_values)}"),
            cause=tuple_cause,
        ) from tuple_cause
    captured: list[Middleware] = []
    for index, item in enumerate(middleware_values):
        if not isinstance(item, Middleware):
            member_cause = TypeError(
                f"MIDDLEWARE entry {index} is {type(item).__name__}, "
                "not starlette.middleware.Middleware"
            )
            raise _middleware_failure(
                source_path,
                "runtime MIDDLEWARE contains an invalid member",
                details=(*details, f"entry index: {index}"),
                cause=member_cause,
            ) from member_cause
        captured.append(item)
    return tuple(captured)


def middleware_construction_error(
    *,
    path: str,
    methods: tuple[str, ...],
    chain: tuple[_MiddlewareMarkerEvidence, ...],
    consumers: tuple[_MiddlewareConsumerEvidence, ...],
) -> DispatchError:
    """Build a localized error for one Starlette Route middleware stack."""
    return _middleware_failure(
        path,
        "Starlette could not construct the route middleware stack",
        details=(
            f"normalized path: {path}",
            f"methods: {', '.join(methods)}",
            *_middleware_consumer_details(consumers),
            *(
                detail
                for marker in chain
                for detail in (
                    f"middleware binding: {marker[0]}:{marker[1]}:{marker[2]}",
                    f"middleware marker: {_middleware_marker_label(marker)}",
                )
            ),
        ),
    )


def _outer_for_classification(value: object) -> object:
    current = value
    while isinstance(current, functools.partial):
        current = current.func
    return current


def _callable_mode(
    value: object,
    *,
    source_path: str,
    role: _CallableRole,
    arity: int,
    details: Sequence[str],
) -> Literal["sync", "async"]:
    outer = _outer_for_classification(value)
    descriptor: object | None = None
    if inspect.isfunction(outer) or inspect.ismethod(outer):
        candidate = outer
    else:
        try:
            descriptor = inspect.getattr_static(type(outer), "__call__")
        except AttributeError as error:
            raise DispatchError(
                "PYGANINI013",
                "route-callable",
                source_path,
                f"{role} is not a supported callable",
                details=details,
            ) from error
        if not inspect.isfunction(descriptor):
            raise DispatchError(
                "PYGANINI013",
                "route-callable",
                source_path,
                f"{role} has an unsupported __call__ descriptor",
                details=details,
            )
        candidate = descriptor

    if inspect.isasyncgenfunction(candidate):
        raise DispatchError(
            "PYGANINI013",
            "route-callable",
            source_path,
            f"{role} must not be an async generator",
            details=details,
        )
    try:
        if descriptor is None:
            signature = inspect.signature(
                cast(Callable[..., object], value),
                follow_wrapped=False,
                eval_str=False,
            )
            signature.bind(*([object()] * arity))
        elif isinstance(value, functools.partial):
            partials: list[tuple[tuple[object, ...], dict[str, object]]] = []
            current = cast(functools.partial[object], value)
            while True:
                partials.append(
                    (
                        cast(tuple[object, ...], current.args),
                        cast(dict[str, object], current.keywords or {}),
                    )
                )
                target = current.func
                if not isinstance(target, functools.partial):
                    break
                current = cast(functools.partial[object], target)
            signature_target: Callable[..., object] = functools.partial(
                cast(Callable[..., object], descriptor), object()
            )
            for args, keywords in reversed(partials):
                signature_target = functools.partial(
                    signature_target,
                    *args,
                    **keywords,
                )
            signature = inspect.signature(
                signature_target,
                follow_wrapped=False,
                eval_str=False,
            )
            signature.bind(*([object()] * arity))
        else:
            signature = inspect.signature(
                cast(Callable[..., object], descriptor),
                follow_wrapped=False,
                eval_str=False,
            )
            signature.bind(*([object()] * (arity + 1)))
    except (TypeError, ValueError) as error:
        raise DispatchError(
            "PYGANINI013",
            "route-callable",
            source_path,
            (
                "route handler must accept one positional request and require no "
                "other argument"
                if role == "route handler"
                else "kit creator must accept one positional request and require no "
                "other argument"
                if role == "kit creator"
                else "kit handler must accept two positional arguments "
                "(kit, request) and require no other argument"
                if role == "kit handler"
                else "sync request-data action must accept the original "
                "request and captured payload and require no other argument"
                if role == "sync request-data action"
                else "route error handler must accept two positional arguments "
                "(request, error) and require no other argument"
            ),
            details=details,
        ) from error
    return "async" if inspect.iscoroutinefunction(candidate) else "sync"


def _validate_binding(
    route_module: ModuleType,
    handler: Callable[..., object],
    surface: _ExpectedSurface,
    *,
    role: _CallableRole,
    arity: int,
) -> None:
    module_name, symbol, binding = surface[5], surface[6], surface[7]
    details = (*_expected_details(surface), f"callable role: {role}")
    request_data = _surface_request_data(surface)
    if request_data is not None:
        details = (*details, *_request_data_details(request_data, arity=arity))
    try:
        source_module = import_module(module_name)
    except BaseException as error:
        raise _import_failure(
            surface[8],
            f"cannot import handler module {module_name!r}",
            surface=surface,
            details=details,
            cause=error,
        ) from error
    try:
        route_binding = _module_value(route_module, binding)
    except KeyError as error:
        raise _import_failure(
            surface[8],
            f"route module is missing recorded binding {binding!r}",
            surface=surface,
            details=details,
            cause=error,
        ) from error
    try:
        source_symbol = _module_value(source_module, symbol)
    except KeyError as error:
        raise _import_failure(
            surface[8],
            f"handler module is missing recorded symbol {symbol!r}",
            surface=surface,
            details=details,
            cause=error,
        ) from error

    if route_binding is source_module:
        matches = source_symbol is handler
    else:
        matches = route_binding is handler and source_symbol is handler
    if not matches:
        raise _import_failure(
            surface[8],
            "runtime handler identity disagrees with the recorded source binding",
            surface=surface,
            details=details,
        )
    mode = _callable_mode(
        handler,
        source_path=surface[8],
        role=role,
        arity=arity,
        details=details,
    )
    if role == "sync request-data action" and mode != "sync":
        raise DispatchError(
            "PYGANINI013",
            "route-callable",
            surface[8],
            "sync request-data action must be synchronous",
            details=(
                *details,
                "callable mode: async",
            ),
        )


def _validate_creator_binding(
    route_module: ModuleType,
    creator: Callable[..., object],
    expected: _CreatorEvidence,
    surfaces: tuple[_ExpectedSurface, ...],
    extra_details: Sequence[str] = (),
) -> None:
    module_name, symbol, binding, source_path, _, _ = expected
    details = (*_creator_details(expected, surfaces), *extra_details)
    try:
        source_module = import_module(module_name)
    except BaseException as error:
        raise _import_failure(
            source_path,
            f"cannot import creator module {module_name!r}",
            details=details,
            cause=error,
        ) from error
    try:
        route_binding = _module_value(route_module, binding)
    except KeyError as error:
        raise _import_failure(
            source_path,
            f"route module is missing recorded creator binding {binding!r}",
            details=details,
            cause=error,
        ) from error
    try:
        source_symbol = _module_value(source_module, symbol)
    except KeyError as error:
        raise _import_failure(
            source_path,
            f"creator module is missing recorded symbol {symbol!r}",
            details=details,
            cause=error,
        ) from error

    if route_binding is source_module:
        matches = source_symbol is creator
    else:
        matches = route_binding is creator and source_symbol is creator
    if not matches:
        raise _import_failure(
            source_path,
            "runtime creator identity disagrees with the recorded source binding",
            details=details,
        )
    _callable_mode(
        creator,
        source_path=source_path,
        role="kit creator",
        arity=1,
        details=details,
    )


def load_route(
    *,
    module: str,
    source_path: str,
    expected: tuple[_ExpectedSurface, ...],
    expected_creator: _CreatorEvidence | None = None,
    expected_template_root: str | None = None,
    expected_kit: bool = False,
    expected_nav: _NavigationDeclaration | None = None,
    expected_destinations: tuple[_DestinationDeclaration, ...] = (),
    expected_error_page_template: str | None = None,
    expected_error_fragment_template: str | None = None,
) -> RouteDef | KitRouteDef[object]:
    """Import and validate one generated route owner without retaining state."""
    route_details = _expected_details(expected[0]) if expected else ()
    try:
        route_module = import_module(module)
    except BaseException as error:
        raise _import_failure(
            source_path,
            f"cannot import route module {module!r}",
            details=route_details,
            cause=error,
        ) from error
    try:
        value = _module_value(route_module, "Route")
    except KeyError as error:
        raise _import_failure(
            source_path,
            "route module has no direct Route binding",
            details=route_details,
            cause=error,
        ) from error
    kit_route = expected_kit or expected_creator is not None
    if not kit_route:
        if not isinstance(value, RouteDef):
            raise _import_failure(
                source_path,
                "runtime Route is not a pyganini.RouteDef value",
                details=route_details,
            )
        route_value: RouteDef | KitRouteDef[object] = value
    else:
        if not isinstance(value, KitRouteDef):
            raise _import_failure(
                source_path,
                "runtime Route is not a pyganini.KitRouteDef value",
                details=route_details,
            )
        route_value = cast(KitRouteDef[object], value)
        if route_value.template_root != expected_template_root:
            creator_details = (
                _creator_details(expected_creator, expected)
                if expected_creator is not None
                else ()
            )
            raise _import_failure(
                source_path,
                "runtime kit template root disagrees with generated evidence",
                details=(
                    *route_details,
                    *creator_details,
                    f"actual template root: {value.template_root!r}",
                    f"expected template root: {expected_template_root!r}",
                ),
            )
        if expected_kit and route_value.create is not None and expected_creator is None:
            raise _import_failure(
                source_path,
                "runtime mounted source Route unexpectedly has a creator",
                details=route_details,
            )
        if route_value.create is None:
            if expected_creator is None:
                pass
            else:
                raise _import_failure(
                    source_path,
                    "runtime kit Route has no creator",
                    details=(
                        *route_details,
                        *_creator_details(expected_creator, expected),
                    ),
                )
        elif expected_creator is not None:
            _validate_creator_binding(
                route_module,
                cast(Callable[..., object], route_value.create),
                expected_creator,
                expected,
            )

    actual_nav = (
        None
        if route_value.nav is None
        else (
            route_value.nav.label,
            route_value.nav.key,
        )
    )
    if actual_nav != expected_nav:
        raise _import_failure(
            source_path,
            "runtime Route navigation declaration disagrees with generated evidence",
            details=(
                *route_details,
                f"actual nav: {actual_nav!r}",
                f"expected nav: {expected_nav!r}",
            ),
        )
    actual_destinations = tuple(
        (destination.name, destination.target.route_pattern, destination.trail_key)
        for destination in route_value.destinations
    )
    if actual_destinations != expected_destinations:
        raise _import_failure(
            source_path,
            "runtime Route destinations disagree with generated evidence",
            details=(
                *route_details,
                f"actual destinations: {actual_destinations!r}",
                f"expected destinations: {expected_destinations!r}",
            ),
        )

    actual_error_templates = (
        route_value.error_page_template,
        route_value.error_fragment_template,
    )
    expected_error_templates = (
        expected_error_page_template,
        expected_error_fragment_template,
    )
    if actual_error_templates != expected_error_templates:
        raise _import_failure(
            source_path,
            "runtime Route error templates disagree with generated evidence",
            details=(
                *route_details,
                f"actual error templates: {actual_error_templates!r}",
                f"expected error templates: {expected_error_templates!r}",
            ),
        )

    actual = _runtime_surfaces(route_value)
    expected_keys = {_surface_key(surface) for surface in expected}
    actual_keys = set(actual)
    if len(expected) != len(actual) or expected_keys != actual_keys:
        raise _import_failure(
            source_path,
            "runtime Route surface disagrees with generated route ownership",
            details=(
                *route_details,
                f"actual surface keys: {sorted(actual_keys)!r}",
                f"expected surface keys: {sorted(expected_keys)!r}",
            ),
        )
    for surface in expected:
        handler, template, request_data = actual[_surface_key(surface)]
        if template != surface[11]:
            raise _import_failure(
                source_path,
                "runtime template declaration disagrees with generated evidence",
                surface=surface,
                details=(
                    f"actual template: {template!r}",
                    f"expected template: {surface[11]!r}",
                ),
            )
        expected_request_data = _surface_request_data(surface)
        if request_data != expected_request_data:
            raise _import_failure(
                surface[8],
                "runtime request-data declaration disagrees with generated evidence",
                surface=surface,
                details=(
                    f"actual request data: {request_data!r}",
                    f"expected request data: {expected_request_data!r}",
                ),
            )
        captured = expected_request_data is not None
        _validate_binding(
            route_module,
            handler,
            surface,
            role=(
                "sync request-data action"
                if captured
                else "kit handler"
                if kit_route
                else "route handler"
            ),
            arity=(3 if kit_route else 2) if captured else (2 if kit_route else 1),
        )
    return route_value


def load_mount_owner(
    *,
    module: str,
    source_path: str,
    expected_creator: _CreatorEvidence,
    expected_mount: str,
    expected_routes: tuple[str, ...] | None,
    expected_bindings: tuple[tuple[str, str, str], ...],
    expected_selections: tuple[_MountSelectionDeclaration, ...] | None = None,
    expected_error_page_template: str | None = None,
    expected_error_fragment_template: str | None = None,
) -> KitRouteMount[object]:
    """Import and validate one generated mounted route owner."""
    mount_details = (
        "evidence phase: route-import",
        f"live owner: {source_path}",
        f"mount identity: {expected_mount}",
        *(
            detail
            for selector, mounted_source, final_path in expected_bindings
            for detail in (
                f"mounted source: {mounted_source}",
                f"selector: {selector}",
                f"final path: {final_path}",
            )
        ),
    )
    try:
        route_module = import_module(module)
    except BaseException as error:
        raise _import_failure(
            source_path,
            f"cannot import route module {module!r}",
            details=mount_details,
            cause=error,
        ) from error
    try:
        value = _module_value(route_module, "Route")
    except KeyError as error:
        raise _import_failure(
            source_path,
            "route module has no direct Route binding",
            details=mount_details,
            cause=error,
        ) from error
    if not isinstance(value, KitRouteMount):
        raise _import_failure(
            source_path,
            "runtime Route is not a pyganini.KitRouteMount value",
            details=mount_details,
        )
    owner = cast(KitRouteMount[object], value)
    actual_routes = (
        None if owner.routes is None else tuple(item.path for item in owner.routes)
    )
    if owner.mount != expected_mount or actual_routes != expected_routes:
        raise _import_failure(
            source_path,
            "runtime mount owner disagrees with generated evidence",
            details=(
                *mount_details,
                f"actual mount: {value.mount!r}",
                f"expected mount: {expected_mount!r}",
                f"actual routes: {actual_routes!r}",
                f"expected routes: {expected_routes!r}",
            ),
        )
    actual_error_templates = (
        owner.error_page_template,
        owner.error_fragment_template,
    )
    expected_error_templates = (
        expected_error_page_template,
        expected_error_fragment_template,
    )
    if actual_error_templates != expected_error_templates:
        raise _import_failure(
            source_path,
            "runtime mount owner error templates disagree with generated evidence",
            details=(
                *mount_details,
                f"actual error templates: {actual_error_templates!r}",
                f"expected error templates: {expected_error_templates!r}",
            ),
        )
    actual_selections = tuple(
        (
            selection.path,
            None if selection.nav is None else (selection.nav.label, selection.nav.key),
            tuple(
                (
                    destination.name,
                    destination.target.route_pattern,
                    destination.trail_key,
                )
                for destination in selection.destinations
            ),
        )
        for selection in (() if owner.routes is None else owner.routes)
    )
    selection_evidence = (
        expected_selections
        if expected_selections is not None
        else tuple((path, None, ()) for path, _, _ in actual_selections)
    )
    if actual_selections != selection_evidence:
        raise _import_failure(
            source_path,
            "runtime mounted selections disagree with generated evidence",
            details=(
                *mount_details,
                f"actual selections: {actual_selections!r}",
                f"expected selections: {selection_evidence!r}",
            ),
        )
    _validate_creator_binding(
        route_module,
        cast(Callable[..., object], owner.create),
        expected_creator,
        (),
        mount_details,
    )
    return owner


def select_handler(
    route: RouteDef | KitRouteDef[object],
    *,
    kind: _Kind,
    method: str,
    local_path: str,
) -> Callable[..., object]:
    """Select one exact handler from an already validated route value."""
    key = (kind, method, local_path)
    try:
        return _runtime_surfaces(route)[key][0]
    except KeyError as error:
        raise DispatchError(
            "PYGANINI012",
            "route-import",
            local_path,
            "validated Route no longer contains the selected surface",
        ) from error


def select_creator(
    route: RouteDef | KitRouteDef[object] | KitRouteMount[object],
) -> Callable[..., object]:
    """Select the validated creator from one generated kit route value."""
    if not isinstance(route, (KitRouteDef, KitRouteMount)):
        raise DispatchError(
            "PYGANINI012",
            "route-import",
            "Route",
            "validated Route is not a pyganini.KitRouteDef value",
        )
    return cast(Callable[..., object], route.create)


async def _invoke(
    handler: Callable[..., object],
    arguments: tuple[object, ...],
    *,
    role: _CallableRole,
    source_path: str,
    details: Sequence[str],
) -> object:
    mode = _callable_mode(
        handler,
        source_path=source_path,
        role=role,
        arity=len(arguments),
        details=details,
    )
    if mode == "async":
        result = handler(*arguments)
    else:
        call = functools.partial(handler, *arguments)
        result = await _run_sync(call, abandon_on_cancel=True)
    if inspect.isawaitable(result):
        return await cast(Awaitable[object], result)
    return result


class _HeadResponse(Response):
    def __init__(self, response: Response) -> None:
        self._response = response
        self.status_code = response.status_code
        self.raw_headers = response.raw_headers
        self.background = response.background
        self.body = b""

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        async def suppress_body(message: Message) -> None:
            if message["type"] == "http.response.body":
                message = {**message, "body": b""}
            await send(message)

        await self._response(scope, receive, suppress_body)


async def _invoke_prepared_route_error_handler(
    prepared: _PreparedRouteErrorHandler,
    request: Request,
    error: Exception,
) -> object:
    arguments = (request, error)
    if prepared.mode == "async":
        result = prepared.handler(*arguments)
    else:
        call = functools.partial(prepared.handler, *arguments)
        result = await _run_sync(call, abandon_on_cancel=True)
    if inspect.isawaitable(result):
        return await cast(Awaitable[object], result)
    return result


def _snapshot_route_error_contract(error: Exception) -> _RouteErrorContract:
    if not isinstance(error, HTTPException):
        return _RouteErrorContract(
            is_http=False,
            expected_status=500,
            required_headers=(),
        )
    return _RouteErrorContract(
        is_http=True,
        expected_status=error.status_code,
        required_headers=tuple(
            (name, value) for name, value in (error.headers or {}).items()
        ),
    )


def _route_error_result_details(
    request: Request,
    error: Exception,
    *,
    contract: _RouteErrorContract,
    source_path: str,
    normalized_path: str | None,
    presentation: str,
) -> tuple[str, ...]:
    diagnostic_path = (
        normalized_path
        if normalized_path is not None
        else (
            error.path
            if isinstance(error, DispatchError)
            else str(request.scope.get("path", "<unknown>"))
        )
    )
    return (
        "callback role: route error handler",
        f"method: {request.method}",
        f"normalized path: {diagnostic_path}",
        f"error category: {type(error).__name__}",
        f"expected status: {contract.expected_status}",
        f"generated source: {source_path}",
        "selected error outcome: "
        + (
            f"HTTP {contract.expected_status}"
            if contract.is_http
            else "non-HTTP exception"
        ),
        f"selected presentation boundary: {presentation}",
    )


def _validate_route_error_response(
    request: Request,
    error: Exception,
    result: object,
    *,
    contract: _RouteErrorContract,
    normalized_path: str | None,
    source_path: str,
    presentation: str,
) -> Response | None:
    details = _route_error_result_details(
        request,
        error,
        contract=contract,
        source_path=source_path,
        normalized_path=normalized_path,
        presentation=presentation,
    )
    if result is None:
        return None
    if not isinstance(result, Response):
        raise _route_error_handler_failure(
            "error handler must return Page, FragmentResponse, a Starlette Response, "
            "or None",
            source_path=source_path,
            details=(*details, f"actual result type: {type(result).__name__}"),
        )
    if contract.is_http:
        if result.status_code != contract.expected_status:
            raise _route_error_handler_failure(
                "handled HTTPException response has the wrong status",
                source_path=source_path,
                details=(
                    *details,
                    f"actual status: {result.status_code}",
                ),
            )
        for name, value in contract.required_headers:
            actual = result.headers.get(name)
            if actual is None:
                result.headers[name] = value
            elif actual != value:
                raise _route_error_handler_failure(
                    "handled HTTPException response has an invalid required header",
                    source_path=source_path,
                    details=(
                        *details,
                        f"required header: {name}",
                        f"expected header value: {value}",
                        f"actual header value: {actual}",
                        f"actual status: {result.status_code}",
                    ),
                )
    elif result.status_code != contract.expected_status:
        raise _route_error_handler_failure(
            "handled non-HTTP exception response must have status 500",
            source_path=source_path,
            details=(
                *details,
                f"actual status: {result.status_code}",
            ),
        )
    return result


async def _call_route_error_handler(
    prepared: _PreparedRouteErrorHandler,
    request: Request,
    error: Exception,
    *,
    normalized_path: str | None = None,
    layouts: tuple[LayoutEvidence, ...] | None = None,
    inspection: _MatchedErrorInspection | None = None,
    presentation: str,
) -> Response | None:
    contract = _snapshot_route_error_contract(error)
    result = await _invoke_prepared_route_error_handler(prepared, request, error)
    selected_presentation = presentation
    if isinstance(result, Page):
        selected_presentation = f"{presentation} page"
        template = prepared.page_template
        if template is None:
            details = _route_error_result_details(
                request,
                error,
                contract=contract,
                source_path=prepared.source_path,
                normalized_path=normalized_path,
                presentation=selected_presentation,
            )
            raise _route_error_handler_failure(
                "error handler returned Page without a declared root error page "
                "template",
                source_path=prepared.source_path,
                details=(
                    *details,
                    "actual result type: Page",
                    "missing root declaration field: error_page_template",
                ),
            )
        selected_layouts = prepared.root_layouts if layouts is None else layouts
        selected_marker = prepared.page_marker
        selected_layout_markers = prepared.root_layout_markers
        if inspection is not None:
            selected_marker, _, selected_layout_markers = inspection
        result = await _render_route_error_result(
            prepared,
            request,
            error,
            result,
            template=template,
            layouts=selected_layouts,
            marker=selected_marker,
            layout_markers=selected_layout_markers,
            contract=contract,
            normalized_path=normalized_path,
            presentation=selected_presentation,
        )
    elif isinstance(result, FragmentResponse):
        selected_presentation = f"{presentation} fragment"
        template = prepared.fragment_template
        if template is None:
            details = _route_error_result_details(
                request,
                error,
                contract=contract,
                source_path=prepared.source_path,
                normalized_path=normalized_path,
                presentation=selected_presentation,
            )
            raise _route_error_handler_failure(
                "error handler returned FragmentResponse without a declared root error "
                "fragment template",
                source_path=prepared.source_path,
                details=(
                    *details,
                    "actual result type: FragmentResponse",
                    "missing root declaration field: error_fragment_template",
                ),
            )
        result = await _render_route_error_result(
            prepared,
            request,
            error,
            result,
            template=template,
            layouts=(),
            marker=(prepared.fragment_marker if inspection is None else inspection[1]),
            layout_markers=(),
            contract=contract,
            normalized_path=normalized_path,
            presentation=selected_presentation,
        )
    return _validate_route_error_response(
        request,
        error,
        result,
        contract=contract,
        normalized_path=normalized_path,
        source_path=prepared.source_path,
        presentation=selected_presentation,
    )


async def _render_route_error_result(
    prepared: _PreparedRouteErrorHandler,
    request: Request,
    error: Exception,
    result: Page | FragmentResponse,
    *,
    template: TemplateEvidence,
    layouts: tuple[LayoutEvidence, ...],
    marker: InspectionMarkerEvidence | None,
    layout_markers: tuple[InspectionMarkerEvidence, ...],
    contract: _RouteErrorContract,
    normalized_path: str | None,
    presentation: str,
) -> Response:
    details = _route_error_result_details(
        request,
        error,
        contract=contract,
        source_path=prepared.source_path,
        normalized_path=normalized_path,
        presentation=presentation,
    )
    render_details = _render_details(template, layouts)
    assert prepared.environment is not None
    try:
        return await render_response(
            environment=prepared.environment,
            result=result,
            template=template,
            layouts=layouts,
            template_inspection=prepared.template_inspection,
            marker=marker,
            layout_markers=layout_markers,
        )
    except (TypeError, ValueError) as render_error:
        raise _route_error_handler_failure(
            "error handler returned an invalid render value",
            source_path=prepared.source_path,
            details=(*details, *render_details, str(render_error)),
            cause=render_error,
        ) from render_error
    except RenderFailure as render_error:
        rendered = DispatchError(
            "PYGANINI015",
            render_error.phase,
            prepared.source_path,
            render_error.message,
            details=(*details, *render_details, *render_error.details),
        )
        rendered.__cause__ = render_error.__cause__
        raise rendered from render_error.__cause__


async def _send_route_error_response(
    request: Request,
    response: Response,
    scope: Scope,
    receive: Receive,
    send: Send,
) -> None:
    selected = _HeadResponse(response) if request.method == "HEAD" else response
    await selected(scope, receive, send)


def _position_text(path: str, line: int, column: int) -> str:
    return f"{path}:{line}:{column}"


def _object_tuple(value: object) -> tuple[object, ...] | None:
    if not isinstance(value, tuple):
        return None
    return cast(tuple[object, ...], value)


def _is_position_evidence(value: object) -> bool:
    fields = _object_tuple(value)
    return (
        fields is not None
        and len(fields) == 3
        and isinstance(fields[0], str)
        and isinstance(fields[1], int)
        and isinstance(fields[2], int)
    )


def _is_template_evidence(value: object) -> bool:
    fields = _object_tuple(value)
    return (
        fields is not None
        and len(fields) == 6
        and isinstance(fields[0], str)
        and isinstance(fields[1], str)
        and isinstance(fields[2], int)
        and isinstance(fields[3], int)
        and (fields[4] is None or isinstance(fields[4], str))
        and (fields[5] is None or _is_position_evidence(fields[5]))
    )


def _is_layout_evidence(value: object) -> bool:
    fields = _object_tuple(value)
    return (
        fields is not None
        and len(fields) == 5
        and isinstance(fields[0], str)
        and isinstance(fields[1], int)
        and isinstance(fields[2], int)
        and isinstance(fields[3], str)
        and _is_template_evidence(fields[4])
    )


def _is_marker_evidence(value: object) -> bool:
    fields = _object_tuple(value)
    return (
        fields is not None
        and len(fields) == 9
        and all(isinstance(field, str) for field in fields)
    )


def _is_embedded_evidence(value: object) -> bool:
    fields = _object_tuple(value)
    return (
        fields is not None
        and len(fields) == 2
        and isinstance(fields[0], str)
        and _is_marker_evidence(fields[1])
    )


def _is_embedded_expectation(value: object) -> bool:
    fields = _object_tuple(value)
    return (
        fields is not None
        and len(fields) == 3
        and isinstance(fields[0], str)
        and _is_route_evidence(fields[1])
        and _is_template_evidence(fields[2])
    )


def _is_route_evidence(value: object) -> bool:
    fields = _object_tuple(value)
    methods = None if fields is None or len(fields) != 15 else _object_tuple(fields[2])
    return (
        fields is not None
        and len(fields) == 15
        and isinstance(fields[0], str)
        and isinstance(fields[1], str)
        and methods is not None
        and all(isinstance(method, str) for method in methods)
        and isinstance(fields[3], str)
        and isinstance(fields[4], int)
        and isinstance(fields[5], int)
        and isinstance(fields[6], str)
        and isinstance(fields[7], str)
        and isinstance(fields[8], str)
        and isinstance(fields[9], str)
        and (fields[10] is None or isinstance(fields[10], str))
        and (fields[11] is None or isinstance(fields[11], str))
        and isinstance(fields[12], int)
        and isinstance(fields[13], int)
        and isinstance(fields[14], str)
    )


def _is_render_facts(value: object) -> bool:
    fields = _object_tuple(value)
    if fields is None or len(fields) != 5:
        return False
    layouts = _object_tuple(fields[1])
    layout_markers = _object_tuple(fields[3])
    embedded = _object_tuple(fields[4])
    return (
        (fields[0] is None or _is_template_evidence(fields[0]))
        and layouts is not None
        and all(_is_layout_evidence(layout) for layout in layouts)
        and (fields[2] is None or _is_marker_evidence(fields[2]))
        and layout_markers is not None
        and all(_is_marker_evidence(marker) for marker in layout_markers)
        and embedded is not None
        and all(_is_embedded_evidence(fragment) for fragment in embedded)
    )


def _is_error_render_facts(value: object) -> bool:
    fields = _object_tuple(value)
    if fields is None or len(fields) != 6:
        return False
    layouts = _object_tuple(fields[2])
    layout_markers = _object_tuple(fields[5])
    return (
        (fields[0] is None or _is_template_evidence(fields[0]))
        and (fields[1] is None or _is_template_evidence(fields[1]))
        and layouts is not None
        and all(_is_layout_evidence(layout) for layout in layouts)
        and (fields[3] is None or _is_marker_evidence(fields[3]))
        and (fields[4] is None or _is_marker_evidence(fields[4]))
        and layout_markers is not None
        and all(_is_marker_evidence(marker) for marker in layout_markers)
    )


def _template_marker_fields_match(
    marker: InspectionMarkerEvidence,
    template: TemplateEvidence,
) -> bool:
    declaration = template[5]
    expected_declaration = (
        "none"
        if declaration is None
        else _position_text(declaration[0], declaration[1], declaration[2])
    )
    return (
        marker[3] == template[0]
        and marker[4] == _position_text(template[1], template[2], template[3])
        and marker[5] == expected_declaration
    )


def _layout_marker_fields_match(
    marker: InspectionMarkerEvidence,
    layout: LayoutEvidence,
    *,
    surface: str,
    route: str,
    mount: str,
) -> bool:
    return (
        marker[0] == "layout"
        and marker[1] == surface
        and marker[2] == route
        and _template_marker_fields_match(marker, layout[4])
        and marker[5] == "none"
        and marker[6] == _position_text(layout[0], layout[1], layout[2])
        and marker[7] == "none"
        and marker[8] == mount
    )


def _expected_mount(evidence: _Evidence) -> str:
    return "none" if evidence[10] is None else f"{evidence[10]}:{evidence[11] or '/'}"


def _expected_owner(evidence: _Evidence) -> str:
    return _position_text(evidence[9], evidence[12], evidence[13])


def _expected_layout_route(evidence: _Evidence, layout: LayoutEvidence) -> str:
    if evidence[10] is None or not layout[0].startswith("app/mounts/"):
        return layout[3]
    mount_root = evidence[14]
    if layout[3] == "/":
        return mount_root
    return layout[3] if mount_root == "/" else mount_root.rstrip("/") + layout[3]


def _inspection_disagreement(
    *,
    source_path: str,
    details: tuple[str, ...],
) -> None:
    raise DispatchError(
        "PYGANINI015",
        "render-configuration",
        source_path,
        "generated inspection facts disagree with captured route facts",
        details=details,
    )


def _normalized_route_path(value: str) -> bool:
    return (
        value.startswith("/")
        and not value.startswith("//")
        and (value == "/" or not value.endswith("/"))
        and "//" not in value
        and all(segment not in {".", ".."} for segment in value.split("/"))
    )


def _local_path_from_evidence(evidence: _Evidence) -> str | None:
    route = evidence[1]
    root = evidence[14]
    if not _normalized_route_path(route) or not _normalized_route_path(root):
        return None
    if route == root:
        return "/"
    if root == "/":
        return route
    prefix = root + "/"
    if not route.startswith(prefix):
        return None
    return route[len(root) :]


def _validate_endpoint_inspection_facts(
    *,
    method: str,
    evidence: _Evidence,
    rendering: _RenderFacts,
    embedded_expectations: tuple[_EmbeddedExpectation, ...],
) -> None:
    template, layouts, marker, layout_markers, embedded_fragments = rendering
    kind = evidence[0]
    expected_layout_surface = "action-page" if kind == "action" else "page"
    expected_handler = f"{evidence[6]}:{evidence[7]}"
    expected_mount = _expected_mount(evidence)
    valid = len(layout_markers) == len(layouts) and (template is None) == (
        marker is None
    )
    if marker is not None and template is not None:
        valid = valid and (
            marker[0] == kind
            and marker[1] == kind
            and marker[2] == evidence[1]
            and _template_marker_fields_match(marker, template)
            and marker[6] == _expected_owner(evidence)
            and marker[7] == expected_handler
            and marker[8] == expected_mount
        )
    valid = valid and all(
        _layout_marker_fields_match(
            layout_marker,
            layout,
            surface=expected_layout_surface,
            route=_expected_layout_route(evidence, layout),
            mount=(expected_mount if layout[0].startswith("app/mounts/") else "none"),
        )
        for layout_marker, layout in zip(layout_markers, layouts, strict=True)
    )
    expectation_by_path = {
        local_path: (fragment_evidence, fragment_template)
        for local_path, fragment_evidence, fragment_template in embedded_expectations
    }
    local_paths: set[str] = set()
    valid = valid and len(expectation_by_path) == len(embedded_expectations)
    valid = valid and set(expectation_by_path) == {
        local_path for local_path, _marker in embedded_fragments
    }
    for local_path, fragment_marker in embedded_fragments:
        if local_path in local_paths:
            valid = False
        local_paths.add(local_path)
        expected_fragment = expectation_by_path.get(local_path)
        if expected_fragment is None:
            valid = False
            continue
        fragment_evidence, fragment_template = expected_fragment
        canonical_local_path = _local_path_from_evidence(fragment_evidence)
        valid = valid and (
            canonical_local_path == local_path
            and fragment_evidence[3:6] == evidence[3:6]
            and fragment_evidence[9] == evidence[9]
            and fragment_evidence[10] == evidence[10]
            and fragment_evidence[11] == evidence[11]
            and fragment_evidence[12:14] == evidence[12:14]
            and fragment_evidence[14] == evidence[14]
            and fragment_evidence[0] == "fragment"
            and fragment_marker[0] == "fragment"
            and fragment_marker[1] == "embedded-fragment"
            and fragment_marker[2] == fragment_evidence[1]
            and _template_marker_fields_match(fragment_marker, fragment_template)
            and fragment_marker[6] == _expected_owner(fragment_evidence)
            and fragment_marker[7] == f"{fragment_evidence[6]}:{fragment_evidence[7]}"
            and fragment_marker[8] == _expected_mount(fragment_evidence)
            and fragment_marker[8] == expected_mount
        )
    if not valid:
        _inspection_disagreement(
            source_path=evidence[3],
            details=(
                f"method: {method}",
                f"route kind: {kind}",
                f"route path: {evidence[1]}",
                f"route handler: {expected_handler}",
                f"inspection marker: {marker!r}",
            ),
        )


def _validate_error_inspection_facts(
    *,
    page_template: TemplateEvidence | None,
    fragment_template: TemplateEvidence | None,
    layouts: tuple[LayoutEvidence, ...],
    page_marker: InspectionMarkerEvidence | None,
    fragment_marker: InspectionMarkerEvidence | None,
    layout_markers: tuple[InspectionMarkerEvidence, ...],
    page_surface: str,
    fragment_surface: str,
    route: str,
    source_path: str,
    expected_evidence: _Evidence | None = None,
    expected_owner: str | None = None,
) -> None:
    structurally_valid = (
        (page_template is None or _is_template_evidence(page_template))
        and (fragment_template is None or _is_template_evidence(fragment_template))
        and _object_tuple(layouts) is not None
        and all(_is_layout_evidence(layout) for layout in layouts)
        and (page_marker is None or _is_marker_evidence(page_marker))
        and (fragment_marker is None or _is_marker_evidence(fragment_marker))
        and _object_tuple(layout_markers) is not None
        and all(_is_marker_evidence(marker) for marker in layout_markers)
        and (expected_evidence is None or _is_route_evidence(expected_evidence))
    )
    if not structurally_valid:
        _inspection_disagreement(
            source_path=source_path,
            details=(
                f"error route: {route}",
                f"page template: {page_template!r}",
                f"fragment template: {fragment_template!r}",
                f"layouts: {layouts!r}",
                f"page marker: {page_marker!r}",
                f"fragment marker: {fragment_marker!r}",
                f"layout markers: {layout_markers!r}",
                f"captured route evidence: {expected_evidence!r}",
            ),
        )
    endpoint_mount = (
        _expected_mount(expected_evidence) if expected_evidence is not None else "none"
    )
    selected_expected_owner = (
        _expected_owner(expected_evidence)
        if expected_evidence is not None
        else expected_owner
    )
    valid = (
        len(layout_markers) == len(layouts)
        and ((page_template is None) == (page_marker is None))
        and ((fragment_template is None) == (fragment_marker is None))
        and (
            (page_marker is None and fragment_marker is None)
            or selected_expected_owner is not None
        )
    )
    if page_marker is not None:
        valid = valid and (
            page_marker[0] == "page"
            and page_marker[1] == page_surface
            and page_marker[2] == route
            and page_marker[6] == selected_expected_owner
            and page_marker[7] == "route_error_handler"
            and page_marker[8] == endpoint_mount
            and (
                page_template is None
                or _template_marker_fields_match(page_marker, page_template)
            )
        )
    if fragment_marker is not None:
        valid = valid and (
            fragment_marker[0] == "fragment"
            and fragment_marker[1] == fragment_surface
            and fragment_marker[2] == route
            and fragment_marker[6] == selected_expected_owner
            and fragment_marker[7] == "route_error_handler"
            and fragment_marker[8] == endpoint_mount
            and (
                fragment_template is None
                or _template_marker_fields_match(fragment_marker, fragment_template)
            )
        )
    valid = valid and all(
        _layout_marker_fields_match(
            layout_marker,
            layout,
            surface=page_surface,
            route=(
                _expected_layout_route(expected_evidence, layout)
                if expected_evidence is not None
                else layout[3]
            ),
            mount=(endpoint_mount if layout[0].startswith("app/mounts/") else "none"),
        )
        for layout_marker, layout in zip(layout_markers, layouts, strict=True)
    )
    if page_surface == "root-error-page":
        valid = valid and endpoint_mount == "none"
    if not valid:
        _inspection_disagreement(
            source_path=source_path,
            details=(
                f"error route: {route}",
                f"page surface: {page_surface}",
                f"fragment surface: {fragment_surface}",
                f"page marker: {page_marker!r}",
                f"fragment marker: {fragment_marker!r}",
            ),
        )


def build_endpoint(
    *,
    handlers: Mapping[str, Callable[..., object]],
    creators: Mapping[str, Callable[..., object]] | None = None,
    evidence: Mapping[str, _Evidence],
    parameters: tuple[str, ...],
    rendering: Mapping[str, _RenderFacts],
    navigation: (
        Mapping[str, tuple[NavigationFact, ...]] | tuple[NavigationFact, ...]
    ) = (),
    trail_keys: Mapping[str, tuple[str, ...]] | tuple[str, ...] = (),
    environment: Environment | None = None,
    template_inspection: TemplateInspectionMode = TemplateInspectionMode.OFF,
    embedded_expectations: Mapping[str, tuple[_EmbeddedExpectation, ...]],
    error_rendering: _ErrorRenderFacts = (None, None, (), None, None, ()),
    request_data: (
        Mapping[
            str,
            _RequestDataLiteral | BodyCapture | FormCapture,
        ]
        | None
    ) = None,
) -> Callable[[Request], Awaitable[Response]]:
    """Build one Starlette endpoint from generated method and source facts."""
    captured_handlers = dict(handlers)
    captured_creators = {} if creators is None else dict(creators)
    captured_request_data = {} if request_data is None else dict(request_data)
    captured_evidence = dict(evidence)
    captured_rendering = dict(rendering)
    captured_embedded_expectations = dict(embedded_expectations)
    if not _is_error_render_facts(error_rendering):
        _inspection_disagreement(
            source_path="app/_pyganini/asgi.py",
            details=(f"retained root error rendering: {error_rendering!r}",),
        )
    captured_error_rendering = error_rendering
    if set(captured_rendering) != set(captured_evidence) or set(
        captured_embedded_expectations
    ) != set(captured_evidence):
        _inspection_disagreement(
            source_path="app/_pyganini/asgi.py",
            details=(
                f"route methods: {tuple(sorted(captured_evidence))!r}",
                f"rendering methods: {tuple(sorted(captured_rendering))!r}",
                "embedded expectation methods: "
                f"{tuple(sorted(captured_embedded_expectations))!r}",
            ),
        )
    for method, selected_evidence in captured_evidence.items():
        if not _is_route_evidence(selected_evidence):
            _inspection_disagreement(
                source_path="app/_pyganini/asgi.py",
                details=(
                    f"method: {method}",
                    f"route evidence: {selected_evidence!r}",
                ),
            )
    for method, expected_fragments in captured_embedded_expectations.items():
        if _object_tuple(expected_fragments) is None or not all(
            _is_embedded_expectation(fragment) for fragment in expected_fragments
        ):
            _inspection_disagreement(
                source_path="app/_pyganini/asgi.py",
                details=(
                    f"method: {method}",
                    f"embedded expectations: {expected_fragments!r}",
                ),
            )
    for method, render_facts in captured_rendering.items():
        if not _is_render_facts(render_facts):
            _inspection_disagreement(
                source_path="app/_pyganini/asgi.py",
                details=(
                    f"method: {method}",
                    f"rendering facts: {render_facts!r}",
                ),
            )
        selected_evidence = captured_evidence[method]
        _validate_endpoint_inspection_facts(
            method=method,
            evidence=selected_evidence,
            rendering=render_facts,
            embedded_expectations=captured_embedded_expectations[method],
        )
    if isinstance(navigation, Mapping):
        captured_navigation = {
            method: tuple(facts) for method, facts in navigation.items()
        }
    else:
        captured_navigation = {"GET": tuple(navigation)}
    if isinstance(trail_keys, Mapping):
        captured_trail_keys = {
            method: tuple(keys) for method, keys in trail_keys.items()
        }
    else:
        captured_trail_keys = {"GET": tuple(trail_keys)}
    expected_parameters = frozenset(parameters)

    async def endpoint(request: Request) -> Response:
        selected_method = "GET" if request.method == "HEAD" else request.method
        selected_evidence = captured_evidence[selected_method]
        template, layouts, marker, layout_markers, embedded_fragments = (
            captured_rendering[selected_method]
        )
        generated_response_details = (
            *_evidence_details(selected_evidence),
            *_render_details(template, layouts),
        )
        if frozenset(request.path_params) != expected_parameters:
            raise DispatchError(
                "PYGANINI014",
                "route-response",
                selected_evidence[1],
                "matched path parameters disagree with generated route evidence",
                details=(
                    f"actual parameters: {', '.join(sorted(request.path_params))}",
                    f"expected parameters: {', '.join(parameters)}",
                    *generated_response_details,
                ),
            )
        try:
            _prepare_navigation(
                request,
                facts=captured_navigation.get(selected_method, ()),
                accepted_keys=captured_trail_keys.get(selected_method, ()),
            )
        except (TypeError, UnicodeError, ValueError) as error:
            raise DispatchError(
                "PYGANINI014",
                "route-response",
                selected_evidence[1],
                "generated navigation state could not be prepared",
                details=(str(error), *generated_response_details),
            ) from error
        selected_handler = captured_handlers[selected_method]
        callable_details = (
            *_evidence_details(selected_evidence),
            "callable role: route handler",
        )
        selected_creator = captured_creators.get(selected_method)
        selected_request_data = captured_request_data.get(selected_method)
        if selected_creator is None:
            if selected_request_data is None:
                result = await _invoke(
                    selected_handler,
                    (request,),
                    role="route handler",
                    source_path=selected_evidence[3],
                    details=callable_details,
                )
            else:
                data = await _capture_request_data(
                    request,
                    _request_data_capture(selected_request_data),
                )
                result = await _invoke(
                    selected_handler,
                    (request, data),
                    role="sync request-data action",
                    source_path=selected_evidence[3],
                    details=(
                        *callable_details,
                        "callable role: sync request-data action",
                        *_request_data_details(selected_request_data, arity=2),
                    ),
                )
        else:
            kit = await _invoke(
                selected_creator,
                (request,),
                role="kit creator",
                source_path=selected_evidence[3],
                details=(
                    *_evidence_details(selected_evidence),
                    "callable role: kit creator",
                ),
            )
            if selected_request_data is None:
                result = await _invoke(
                    selected_handler,
                    (kit, request),
                    role="kit handler",
                    source_path=selected_evidence[3],
                    details=(
                        *_evidence_details(selected_evidence),
                        "callable role: kit handler",
                    ),
                )
            else:
                data = await _capture_request_data(
                    request,
                    _request_data_capture(selected_request_data),
                )
                result = await _invoke(
                    selected_handler,
                    (kit, request, data),
                    role="sync request-data action",
                    source_path=selected_evidence[3],
                    details=(
                        *_evidence_details(selected_evidence),
                        "callable role: sync request-data action",
                        *_request_data_details(selected_request_data, arity=3),
                    ),
                )
        if isinstance(result, Response):
            response = result
        elif isinstance(result, (Page, FragmentResponse)):
            kind = selected_evidence[0]
            selected_layouts = layouts if isinstance(result, Page) else ()
            response_details = (
                *_evidence_details(selected_evidence),
                *_render_details(template, selected_layouts),
            )
            if (kind == "page" and not isinstance(result, Page)) or (
                kind == "fragment" and not isinstance(result, FragmentResponse)
            ):
                raise DispatchError(
                    "PYGANINI014",
                    "route-response",
                    selected_evidence[1],
                    "route handler returned a render value for the wrong surface kind",
                    details=response_details,
                )
            if template is None:
                raise DispatchError(
                    "PYGANINI014",
                    "route-response",
                    selected_evidence[1],
                    "route handler returned a render value without a declared template",
                    details=response_details,
                )
            if environment is None:
                raise DispatchError(
                    "PYGANINI014",
                    "route-response",
                    selected_evidence[1],
                    "route rendering has no validated Jinja environment",
                    details=response_details,
                )
            try:
                selected_marker = marker
                if marker is not None and selected_evidence[0] == "action":
                    selected_marker = (
                        "page" if isinstance(result, Page) else "fragment",
                        "action-page"
                        if isinstance(result, Page)
                        else "action-fragment",
                        *marker[2:],
                    )
                response = await render_response(
                    environment=environment,
                    result=result,
                    template=template,
                    layouts=selected_layouts,
                    template_inspection=template_inspection,
                    marker=selected_marker,
                    layout_markers=(layout_markers if isinstance(result, Page) else ()),
                    embedded_fragments=embedded_fragments,
                )
            except (TypeError, ValueError) as error:
                raise DispatchError(
                    "PYGANINI014",
                    "route-response",
                    selected_evidence[1],
                    "route render value violates the response contract",
                    details=(*response_details, str(error)),
                ) from error
            except RenderFailure as error:
                rendered = DispatchError(
                    "PYGANINI015",
                    error.phase,
                    selected_evidence[1],
                    error.message,
                    details=(*_evidence_details(selected_evidence), *error.details),
                )
                rendered.__cause__ = error.__cause__
                raise rendered from error.__cause__
        else:
            raise DispatchError(
                "PYGANINI014",
                "route-response",
                selected_evidence[1],
                f"route handler must return {_result_contract(selected_evidence[0])}",
                details=generated_response_details,
            )
        if request.method == "HEAD":
            return _HeadResponse(response)
        return response

    cast(Any, endpoint).__pyganini_route_evidence__ = captured_evidence
    cast(Any, endpoint).__pyganini_route_rendering__ = captured_rendering
    cast(Any, endpoint).__pyganini_error_rendering__ = captured_error_rendering

    return endpoint


def prepare_environment(
    environment: Environment | None,
    *,
    template_names: tuple[str, ...],
    source_path: str,
) -> Environment:
    """Create or validate the environment used by one generated router."""
    selected = create_environment() if environment is None else environment
    try:
        return validate_environment(selected, template_names=template_names)
    except RenderFailure as error:
        configured = DispatchError(
            "PYGANINI015",
            error.phase,
            source_path,
            error.message,
            details=error.details,
        )
        configured.__cause__ = error.__cause__
        raise configured from error.__cause__
