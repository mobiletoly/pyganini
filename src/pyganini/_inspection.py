# pyright: reportPrivateUsage=false, reportUnusedFunction=false

"""Build deterministic, read-only route inventory output from one graph."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from typing import Literal, cast
from urllib.parse import unquote_to_bytes, urlsplit

from starlette.routing import Match
from starlette.types import Scope

from pyganini._dispatch import PathPriorityRoute
from pyganini._generation import GenerationError
from pyganini._route_graph import (
    DestinationSource,
    Endpoint,
    HandlerReference,
    LayoutSource,
    MountedRouteCandidate,
    NormalizedRoute,
    RouteGraph,
    RouteLabelSource,
    RouteNavSource,
    SourcePosition,
    TemplateSource,
    _endpoint_node,
    _group_methods,
    _groups,
    _join_route,
    _method_endpoints,
    _PathGroup,
    _root_error_render_facts,
    _selected_layouts,
    iter_endpoints,
)
from pyganini._url_generation import (
    _owner_anchor,
    _URLHelperPlan,
)
from pyganini.request_data import BodyCapture, FormCapture

type _InventoryKind = Literal["layout", "route", "page", "fragment", "action"]
type _Selection = Literal["included", "excluded"]
type _DeclarationKind = Literal["route", "route-kit", "mounted-route-kit"]


@dataclass(frozen=True, slots=True)
class _InboundDestinationEvidence:
    source_route: str
    name: str
    trail_key: str | None
    source: SourcePosition


@dataclass(frozen=True, slots=True)
class _RequestDataEvidence:
    kind: Literal["body", "form"]
    source: SourcePosition


@dataclass(frozen=True, slots=True)
class _ImplementationEvidence:
    kind: Literal["page", "fragment", "action"]
    handler: HandlerReference
    declaration: SourcePosition
    template: TemplateSource | None
    request_data: _RequestDataEvidence | None


@dataclass(frozen=True, slots=True)
class _MountEvidence:
    identity: str
    owner: SourcePosition
    source_path: str


@dataclass(frozen=True, slots=True)
class _RouteDeclarationEvidence:
    source: SourcePosition
    kind: _DeclarationKind
    name: str | None
    title: str | None
    labels: tuple[RouteLabelSource, ...]
    nav: RouteNavSource | None
    trail_keys: tuple[str, ...]
    destinations: tuple[DestinationSource, ...]
    inbound_destinations: tuple[_InboundDestinationEvidence, ...]
    mount: _MountEvidence | None
    implementation: _ImplementationEvidence | None


@dataclass(frozen=True, slots=True)
class _ErrorRenderEvidence:
    page_template: TemplateSource | None
    fragment_template: TemplateSource | None
    root_layouts: tuple[LayoutSource, ...]


@dataclass(frozen=True, slots=True)
class RouteInventoryRow:
    kind: _InventoryKind
    methods: tuple[str, ...]
    path: str
    parameters: tuple[str, ...]
    source: SourcePosition
    owner: SourcePosition
    mount: str | None
    source_path: str | None
    helper: str | None
    selection: _Selection | None = None
    declaration: _RouteDeclarationEvidence | None = None


type _RenderUnitKind = Literal["page", "fragment", "action"]
type _RenderUnitLayoutMode = Literal["page", "none", "page-result"]


@dataclass(frozen=True, slots=True)
class _RenderUnitLayout:
    source: SourcePosition
    template: TemplateSource


@dataclass(frozen=True, slots=True)
class _RenderUnitRow:
    kind: _RenderUnitKind
    methods: tuple[str, ...]
    route: str
    template: TemplateSource
    source: SourcePosition
    owner: SourcePosition
    mount: str | None
    source_path: str | None
    layout_mode: _RenderUnitLayoutMode
    effective_layouts: tuple[_RenderUnitLayout, ...]


class InspectionError(ValueError):
    """A reachable route-inventory projection or encoding failure."""


def _require_route_graph(value: object) -> RouteGraph:
    if not isinstance(value, RouteGraph):
        raise InspectionError("route inventory requires RouteGraph authority")
    return value


def _require_error_render(value: object) -> _ErrorRenderEvidence:
    if not isinstance(value, _ErrorRenderEvidence):
        raise InspectionError("route inventory error-render authority is invalid")
    return value


type _ExplainStatus = Literal["matched", "method_not_allowed", "not_found"]
type _ExplainSelection = tuple[
    _ExplainStatus,
    str | None,
    Endpoint | None,
    tuple[tuple[str, str], ...],
    tuple[str, ...],
]

_ASCII_WHITESPACE = " \t\n\r\v\f"
_HEX_DIGITS = frozenset("0123456789abcdefABCDEF")
_HTTP_TOKEN_SYMBOLS = frozenset("!#$%&'*+-.^_`|~")
_URI_UNRESERVED_SYMBOLS = frozenset("-._~")
_URI_SUB_DELIMITERS = frozenset("!$&'()*+,;=")


def _trim_ascii_whitespace(value: str) -> str:
    return value.strip(_ASCII_WHITESPACE)


def _validate_url_text(value: str) -> None:
    if any(ord(character) <= 0x20 or ord(character) == 0x7F for character in value):
        raise ValueError("URL or path contains embedded ASCII control text")


def _path_without_query_or_fragment(value: str) -> str:
    boundaries = [
        boundary for marker in ("?", "#") if (boundary := value.find(marker)) >= 0
    ]
    return value[: min(boundaries)] if boundaries else value


def _valid_scheme(value: str) -> bool:
    if not value or not ("A" <= value[0] <= "Z" or "a" <= value[0] <= "z"):
        return False
    return all(
        "A" <= character <= "Z"
        or "a" <= character <= "z"
        or "0" <= character <= "9"
        or character in "+-."
        for character in value[1:]
    )


def _validate_percent_escapes(value: str, message: str) -> None:
    for index, character in enumerate(value):
        if character != "%":
            continue
        if (
            index + 2 >= len(value)
            or value[index + 1] not in _HEX_DIGITS
            or value[index + 2] not in _HEX_DIGITS
        ):
            raise ValueError(message)


def _valid_authority_component(
    value: str,
    symbols: frozenset[str],
    *,
    allow_percent: bool = True,
) -> bool:
    index = 0
    while index < len(value):
        character = value[index]
        if character == "%":
            if not allow_percent or (
                index + 2 >= len(value)
                or value[index + 1] not in _HEX_DIGITS
                or value[index + 2] not in _HEX_DIGITS
            ):
                return False
            index += 3
            continue
        if not (
            ("A" <= character <= "Z")
            or ("a" <= character <= "z")
            or ("0" <= character <= "9")
            or character in _URI_UNRESERVED_SYMBOLS
            or character in symbols
        ):
            return False
        index += 1
    return True


def _validate_explain_authority(authority: str) -> None:
    if not authority or authority.count("@") > 1:
        raise ValueError("URL authority is invalid")

    userinfo, separator, host_port = authority.rpartition("@")
    if not separator:
        host_port = authority
    elif not _valid_authority_component(userinfo, _URI_SUB_DELIMITERS | frozenset(":")):
        raise ValueError("URL authority is invalid")

    if host_port.startswith("["):
        closing = host_port.find("]")
        if closing < 0:
            raise ValueError("URL authority is invalid")
        host = host_port[1:closing]
        remainder = host_port[closing + 1 :]
        if not host or not _valid_authority_component(
            host,
            _URI_SUB_DELIMITERS | frozenset(":"),
            allow_percent=not host.startswith(("v", "V")),
        ):
            raise ValueError("URL authority is invalid")
        if remainder and (
            not remainder.startswith(":")
            or not all("0" <= character <= "9" for character in remainder[1:])
        ):
            raise ValueError("URL authority is invalid")
        return

    if host_port.count(":") > 1:
        raise ValueError("URL authority is invalid")
    host, port_separator, port = host_port.rpartition(":")
    if not port_separator:
        host = port
    elif not all("0" <= character <= "9" for character in port):
        raise ValueError("URL authority is invalid")
    if not host or not _valid_authority_component(host, _URI_SUB_DELIMITERS):
        raise ValueError("URL authority is invalid")


def _extract_explain_path(value: str) -> str:
    if value.startswith("/"):
        return _path_without_query_or_fragment(value)

    separator = value.find("://")
    scheme = value[:separator] if separator >= 0 else ""
    if separator <= 0 or not _valid_scheme(scheme):
        raise ValueError("URL or path must be an absolute path or hierarchical URL")

    try:
        parsed = urlsplit(value)
        _validate_explain_authority(parsed.netloc)
        hostname = parsed.hostname
        _port = parsed.port
    except ValueError as error:
        raise ValueError("URL authority is invalid") from error
    if not parsed.netloc or hostname is None or parsed.scheme != scheme.lower():
        raise ValueError("URL authority is invalid")
    return parsed.path or "/"


def _decode_explain_path(path: str) -> str:
    _validate_percent_escapes(path, "URL path contains a malformed percent escape")
    try:
        return unquote_to_bytes(path).decode("utf-8", errors="strict")
    except (UnicodeDecodeError, UnicodeEncodeError) as error:
        raise ValueError("URL path is not valid strict UTF-8") from error


def _parse_explain_target(value: str) -> tuple[str, str]:
    target = _trim_ascii_whitespace(value)
    if not target:
        raise ValueError("URL or path must not be empty")
    _validate_url_text(target)
    path = _extract_explain_path(target)
    return path, _decode_explain_path(path)


def _normalize_explain_method(value: str | None) -> str:
    method = "GET" if value is None else _trim_ascii_whitespace(value)
    if not method:
        raise ValueError("HTTP method must not be empty")
    if not all(
        ("A" <= character <= "Z")
        or ("a" <= character <= "z")
        or ("0" <= character <= "9")
        or character in _HTTP_TOKEN_SYMBOLS
        for character in method
    ):
        raise ValueError("HTTP method must be an ASCII token")
    return method.upper()


def _never_called_explain_endpoint(*args: object, **kwargs: object) -> None:
    raise AssertionError("Route Explain matcher endpoint was called")


def _explain_scope(path: str, method: str) -> Scope:
    return {
        "type": "http",
        "path": path,
        "root_path": "",
        "method": method,
    }


def _captured_explain_parameters(
    scope: Scope, group: _PathGroup
) -> tuple[tuple[str, str], ...]:
    raw_parameters = scope.get("path_params")
    if not isinstance(raw_parameters, Mapping):
        raise InspectionError("matcher returned no path parameter mapping")
    raw_parameters = cast(Mapping[str, object], raw_parameters)
    values: list[tuple[str, str]] = []
    for name in group.parameters:
        value = raw_parameters.get(name)
        if not isinstance(value, str):
            raise InspectionError(f"matcher did not return string parameter {name!r}")
        values.append((name, value))
    return tuple(values)


def _select_explain_route(
    graph: RouteGraph, path: str, method: str
) -> _ExplainSelection:
    endpoints = tuple(iter_endpoints(graph))
    for group in _groups(endpoints):
        methods = _group_methods(group)
        route = PathPriorityRoute(
            group.path,
            _never_called_explain_endpoint,
            methods=list(methods),
        )
        match, child_scope = route.matches(_explain_scope(path, method))
        if match is Match.NONE:
            continue
        if match is not Match.FULL:
            raise InspectionError("PathPriorityRoute returned a partial match")
        parameters = _captured_explain_parameters(child_scope, group)
        if method not in methods:
            return "method_not_allowed", group.path, None, parameters, methods

        method_endpoints = _method_endpoints(group)
        dispatch_method = "GET" if method == "HEAD" else method
        endpoint = method_endpoints.get(dispatch_method)
        if endpoint is None:
            raise InspectionError(
                f"dispatch group {group.path!r} has no endpoint for {dispatch_method}"
            )
        return "matched", group.path, endpoint, parameters, methods
    return "not_found", None, None, (), ()


_EXPLAIN_RULES = (
    "  Page results with a declared endpoint template use the displayed layout chain.",
    "  Fragment results are not layout-wrapped.",
    "  Direct Response results bypass templates and layouts.",
    "  HEAD selects the GET handler and suppresses response body payloads.",
    "  Route declaration metadata is static, display-only, and does not affect "
    "matching or runtime policy.",
    "  Excluded mounted candidates are inspection evidence and are never live "
    "endpoints.",
    "  Error Page results use the listed root template and selected page layouts.",
    "  Error FragmentResponse results use the listed root fragment template "
    "without layouts.",
)


def _json_explain_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=True)


def _explain_destination_text(destination: DestinationSource) -> str:
    trail_key = (
        "-"
        if destination.trail_key is None
        else _json_explain_string(destination.trail_key)
    )
    return (
        f"{_json_explain_string(destination.name)}->"
        f"{_json_explain_string(destination.target_path)}#{trail_key}@"
        f"{_position_text(destination.source)}"
    )


def _explain_inbound_text(destination: _InboundDestinationEvidence) -> str:
    trail_key = (
        "-"
        if destination.trail_key is None
        else _json_explain_string(destination.trail_key)
    )
    return (
        f"{_json_explain_string(destination.source_route)}:"
        f"{_json_explain_string(destination.name)}#{trail_key}@"
        f"{_position_text(destination.source)}"
    )


def _explain_declaration_lines(
    declaration: _RouteDeclarationEvidence,
) -> list[str]:
    labels = (
        "-"
        if not declaration.labels
        else _compact_json({label.key: label.value for label in declaration.labels})
    )
    trail_keys = (
        "["
        + ",".join(_json_explain_string(key) for key in declaration.trail_keys)
        + "]"
    )
    destinations = (
        "["
        + ",".join(
            _explain_destination_text(destination)
            for destination in declaration.destinations
        )
        + "]"
    )
    inbound = (
        "["
        + ",".join(
            _explain_inbound_text(destination)
            for destination in declaration.inbound_destinations
        )
        + "]"
    )
    mount = "-"
    if declaration.mount is not None:
        mount = (
            f"{declaration.mount.identity}@"
            f"{_position_text(declaration.mount.owner)}@"
            f"{declaration.mount.source_path}"
        )
    return [
        f"kind={declaration.kind}",
        f"source={_position_text(declaration.source)}",
        "name="
        + ("-" if declaration.name is None else _json_explain_string(declaration.name)),
        "title="
        + (
            "-"
            if declaration.title is None
            else _json_explain_string(declaration.title)
        ),
        f"labels={labels}",
        f"nav={_nav_text(declaration.nav)}",
        f"trail_keys={trail_keys}",
        f"destinations={destinations}",
        f"inbound_destinations={inbound}",
        f"mount={mount}",
    ]


def _explain_implementation_lines(
    implementation: _ImplementationEvidence,
) -> list[str]:
    request_data = "-"
    if implementation.request_data is not None:
        request_data = (
            f"{implementation.request_data.kind}@"
            f"{_position_text(implementation.request_data.source)}"
        )
    return [
        f"kind={implementation.kind}",
        f"handler={implementation.handler.module}.{implementation.handler.symbol}",
        f"binding={implementation.handler.binding}",
        f"handler_source={_position_text(implementation.handler.source)}",
        f"declaration={_position_text(implementation.declaration)}",
        f"template={_template_text(implementation.template)}",
        f"request_data={request_data}",
    ]


def _render_explain(
    graph: RouteGraph,
    *,
    url_path: str,
    asgi_path: str,
    method: str,
    endpoint: Endpoint,
    parameters: tuple[tuple[str, str], ...],
) -> bytes:
    owner = endpoint.owner or endpoint.source
    owner_text = (
        "-" if _same_position(endpoint.source, owner) else _position_text(owner)
    )
    if endpoint.kind == "fragment":
        layout_text = "[] (not wrapped)"
    else:
        layouts = _selected_layouts(graph, endpoint)
        layout_text = (
            "[" + " > ".join(_position_text(item.source) for item in layouts) + "]"
        )
        if endpoint.kind == "action":
            layout_text += " (valid Page results only)"
    params_text = (
        "["
        + ", ".join(
            f"{name}={_json_explain_string(value)}" for name, value in parameters
        )
        + "]"
    )
    inbound = _inbound_destinations(graph)
    declaration = _route_declaration_evidence(graph, endpoint, inbound)
    implementation = declaration.implementation
    if implementation is None:
        raise InspectionError(f"live endpoint {endpoint.path!r} has no implementation")
    errors = _error_render_evidence(graph)
    error_layouts = _selected_layouts(graph, endpoint)
    error_layout_text = (
        "[" + " > ".join(_layout_text(layout) for layout in error_layouts) + "]"
    )
    lines = [
        "ROUTE EXPLAIN",
        f"url_path={_json_explain_string(url_path)}",
        f"asgi_path={_json_explain_string(asgi_path)}",
        f"method={method}",
        "status=matched",
        "",
        "MATCH",
        f"kind={endpoint.kind}",
        f"methods={','.join(endpoint.methods)}",
        f"route={endpoint.path}",
        f"dispatch_method={'GET' if method == 'HEAD' else method}",
        f"params={params_text}",
        f"handler={endpoint.handler.module}.{endpoint.handler.symbol}",
        f"source={_position_text(endpoint.source)}",
        f"owner={owner_text}",
        f"mount={endpoint.mount or '-'}",
        f"source_path={endpoint.source_path or '-'}",
        f"layouts={layout_text}",
        "",
        "DECLARATION",
        *_explain_declaration_lines(declaration),
        "",
        "IMPLEMENTATION",
        *_explain_implementation_lines(implementation),
        "",
        "ERROR_RENDER",
        f"page={_template_text(errors.page_template)}",
        f"fragment={_template_text(errors.fragment_template)}",
        f"page_layouts={error_layout_text}",
        "fragment_layouts=[] (not wrapped)",
        "",
        "RULES",
        *_EXPLAIN_RULES,
    ]
    try:
        return ("\n".join(lines) + "\n").encode("ascii")
    except UnicodeEncodeError as error:
        raise InspectionError(f"route explanation is not ASCII: {error}") from error


def _render_explain_negative(
    *,
    graph: RouteGraph,
    status: _ExplainStatus,
    method: str,
    url_path: str,
    asgi_path: str,
    route: str | None,
    allowed: tuple[str, ...],
) -> bytes:
    errors = _error_render_evidence(graph)
    root_layouts = (
        "[" + " > ".join(_layout_text(layout) for layout in errors.root_layouts) + "]"
    )
    if status == "not_found":
        message = (
            "pyganini routes explain: PYGANINI017 route-inspection: "
            f"method={method} url_path={_json_explain_string(url_path)} "
            f"asgi_path={_json_explain_string(asgi_path)} status=404 "
            "no route matches path"
        )
    elif status == "method_not_allowed" and route is not None:
        message = (
            "pyganini routes explain: PYGANINI017 route-inspection: "
            f"method={method} url_path={_json_explain_string(url_path)} "
            f"asgi_path={_json_explain_string(asgi_path)} status=405 "
            f"route={route} method not allowed; allowed={','.join(allowed)}"
        )
    else:
        raise InspectionError("negative route explanation lacks selection evidence")
    message += (
        f" error_page={_template_text(errors.page_template)}"
        f" error_fragment={_template_text(errors.fragment_template)}"
        f" root_layouts={root_layouts}"
    )
    try:
        return message.encode("ascii")
    except UnicodeEncodeError as error:
        raise InspectionError(f"route explanation is not ASCII: {error}") from error


_KIND_ORDER = {"layout": 0, "route": 1, "page": 2, "fragment": 3, "action": 4}
_METHOD_ORDER = {
    "GET": 0,
    "HEAD": 1,
    "POST": 2,
    "PUT": 3,
    "PATCH": 4,
    "DELETE": 5,
}
_HEADER = (
    "KIND",
    "METHOD",
    "PATH",
    "PARAMS",
    "SOURCE",
    "OWNER",
    "MOUNT",
    "SOURCE_PATH",
    "DECL",
    "NAME",
    "TITLE",
    "LABELS",
    "NAV",
    "TRAIL_KEYS",
    "DESTINATIONS",
    "INBOUND",
    "IMPLEMENTATION",
    "HELPER",
)


def _inspection_path_sort_key(path: str) -> tuple[tuple[int, str], ...]:
    if path == "/":
        return ()
    return tuple(
        (1, segment[1:-1])
        if segment.startswith("{") and segment.endswith("}")
        else (0, segment)
        for segment in path[1:].split("/")
    )


def _position_key(position: SourcePosition) -> tuple[str, int, int]:
    return (position.path.as_posix(), position.line, position.column)


def _same_position(left: SourcePosition, right: SourcePosition) -> bool:
    return _position_key(left) == _position_key(right)


def _position_text(position: SourcePosition) -> str:
    return f"{position.path.as_posix()}:{position.line}:{position.column}"


def _parameters(path: str) -> tuple[str, ...]:
    if path == "/":
        return ()
    return tuple(
        segment[1:-1]
        for segment in path[1:].split("/")
        if segment.startswith("{") and segment.endswith("}")
    )


def _helper_expression(plan: _URLHelperPlan, path: str) -> str:
    for expression_path, expression in plan.expressions:
        if expression_path == path:
            return expression
    raise InspectionError(f"no URL helper expression exists for endpoint path {path!r}")


def _error_render_evidence(graph: RouteGraph) -> _ErrorRenderEvidence:
    page_template, fragment_template, root_layouts = _root_error_render_facts(graph)
    return _ErrorRenderEvidence(page_template, fragment_template, root_layouts)


def _inbound_destinations(
    graph: RouteGraph,
) -> dict[str, tuple[_InboundDestinationEvidence, ...]]:
    inbound: dict[str, list[_InboundDestinationEvidence]] = {}
    for node in graph.nodes:
        declaration = node.declaration
        if declaration is None:
            continue
        for destination in declaration.destinations:
            inbound.setdefault(destination.target_path, []).append(
                _InboundDestinationEvidence(
                    node.route_path,
                    destination.name,
                    destination.trail_key,
                    destination.source,
                )
            )
    return {
        path: tuple(
            sorted(
                values,
                key=lambda value: (
                    _inspection_path_sort_key(value.source_route),
                    value.name,
                    value.trail_key or "",
                    _position_key(value.source),
                ),
            )
        )
        for path, values in inbound.items()
    }


def _request_data_kind(value: object) -> Literal["body", "form"]:
    if isinstance(value, BodyCapture):
        return "body"
    if isinstance(value, FormCapture):
        return "form"
    raise InspectionError("endpoint has unsupported request data")


def _request_data_evidence(endpoint: Endpoint) -> _RequestDataEvidence | None:
    request_data = endpoint.request_data
    if request_data is None:
        return None
    source = endpoint.request_data_source
    if source is None:
        raise InspectionError(
            f"{endpoint.kind} {endpoint.path!r} has no request-data source"
        )
    try:
        kind = _request_data_kind(request_data)
    except InspectionError as error:
        raise InspectionError(
            f"{endpoint.kind} {endpoint.path!r} has unsupported request data"
        ) from error
    return _RequestDataEvidence(kind, source)


def _metadata_values(
    declaration: NormalizedRoute,
) -> tuple[str | None, str | None, tuple[RouteLabelSource, ...]]:
    metadata = declaration.metadata
    if metadata is None:
        return None, None, ()
    return metadata.name, metadata.title, metadata.labels


def _route_declaration_evidence(
    graph: RouteGraph,
    endpoint: Endpoint,
    inbound: dict[str, tuple[_InboundDestinationEvidence, ...]],
) -> _RouteDeclarationEvidence:
    node = _endpoint_node(graph, endpoint)
    declaration = node.declaration
    if declaration is None:
        raise InspectionError(f"live endpoint {endpoint.path!r} has no declaration")
    name, title, labels = _metadata_values(declaration)
    inbound_destinations = inbound.get(node.route_path, ())
    trail_keys = tuple(
        sorted(
            {
                destination.trail_key
                for destination in inbound_destinations
                if destination.trail_key is not None
            }
        )
    )
    if node.mount is not None:
        if node.owner is None or node.source_path is None:
            raise InspectionError(
                f"mounted endpoint {endpoint.path!r} lacks owner evidence"
            )
        kind: _DeclarationKind = "mounted-route-kit"
        mount = _MountEvidence(node.mount, node.owner, node.source_path)
    elif declaration.kit is not None:
        kind = "route-kit"
        mount = None
    else:
        kind = "route"
        mount = None
    declaration_source = endpoint.handler_source
    if declaration_source is None:
        raise InspectionError(
            f"live endpoint {endpoint.path!r} has no declaration surface"
        )
    return _RouteDeclarationEvidence(
        endpoint.source,
        kind,
        name,
        title,
        labels,
        declaration.nav,
        trail_keys,
        tuple(
            sorted(
                declaration.destinations,
                key=lambda value: (
                    value.name,
                    value.target_path,
                    value.trail_key or "",
                    _position_key(value.source),
                ),
            )
        ),
        inbound_destinations,
        mount,
        _ImplementationEvidence(
            endpoint.kind,
            endpoint.handler,
            declaration_source,
            endpoint.template,
            _request_data_evidence(endpoint),
        ),
    )


def _candidate_declaration_evidence(
    candidate: MountedRouteCandidate,
    inbound: dict[str, tuple[_InboundDestinationEvidence, ...]],
) -> _RouteDeclarationEvidence:
    declaration = candidate.declaration
    name, title, labels = _metadata_values(declaration)
    inbound_destinations = inbound.get(candidate.final_path, ())
    trail_keys = tuple(
        sorted(
            {
                destination.trail_key
                for destination in inbound_destinations
                if destination.trail_key is not None
            }
        )
    )
    return _RouteDeclarationEvidence(
        candidate.source_route,
        "mounted-route-kit",
        name,
        title,
        labels,
        declaration.nav,
        trail_keys,
        declaration.destinations,
        inbound_destinations,
        _MountEvidence(candidate.mount, candidate.owner, candidate.source_path),
        None,
    )


def _endpoint_row(
    endpoint: Endpoint,
    helper_plan: _URLHelperPlan | None,
    declaration: _RouteDeclarationEvidence | None = None,
) -> RouteInventoryRow:
    source = endpoint.source
    owner = endpoint.owner or source
    helper = (
        None if helper_plan is None else _helper_expression(helper_plan, endpoint.path)
    )
    return RouteInventoryRow(
        endpoint.kind,
        endpoint.methods,
        endpoint.path,
        endpoint.parameters,
        source,
        owner,
        endpoint.mount,
        endpoint.source_path,
        helper,
        declaration=declaration,
    )


def _endpoint_rows(
    graph: RouteGraph, helper_plan: _URLHelperPlan | None
) -> list[RouteInventoryRow]:
    inbound = _inbound_destinations(graph)
    return [
        _endpoint_row(
            endpoint,
            helper_plan,
            _route_declaration_evidence(graph, endpoint, inbound),
        )
        for endpoint in iter_endpoints(graph)
    ]


def _ordinary_layout_rows(graph: RouteGraph) -> list[RouteInventoryRow]:
    rows: list[RouteInventoryRow] = []
    for node in graph.nodes:
        if node.mount is not None or node.layout is None:
            continue
        layout = node.layout
        rows.append(
            RouteInventoryRow(
                "layout",
                (),
                layout.route_prefix,
                _parameters(layout.route_prefix),
                layout.source,
                layout.source,
                None,
                None,
                None,
            )
        )
    return rows


def _mounted_layout_rows(graph: RouteGraph) -> list[RouteInventoryRow]:
    rows: list[RouteInventoryRow] = []
    seen: set[
        tuple[
            tuple[str, int, int],
            str,
            tuple[str, int, int],
            str,
        ]
    ] = set()
    for node in graph.nodes:
        if node.mount is None:
            continue
        owner = node.owner
        if owner is None:
            raise InspectionError(
                f"mounted URL node {node.route_path!r} has no live owner evidence"
            )
        owner_node = _owner_anchor(graph, owner)
        for layout in node.layouts:
            if layout.source.path.parts[:2] != ("app", "mounts"):
                continue
            final_path = _join_route(owner_node.route_path, layout.route_prefix)
            key = (
                _position_key(owner),
                node.mount,
                _position_key(layout.source),
                final_path,
            )
            if key in seen:
                continue
            seen.add(key)
            rows.append(
                RouteInventoryRow(
                    "layout",
                    (),
                    final_path,
                    _parameters(final_path),
                    layout.source,
                    owner,
                    node.mount,
                    layout.route_prefix,
                    None,
                )
            )
    return rows


def _row_key(row: RouteInventoryRow) -> tuple[object, ...]:
    return (
        _inspection_path_sort_key(row.path),
        _KIND_ORDER[row.kind],
        tuple(_METHOD_ORDER[method] for method in row.methods),
        _position_key(row.owner),
        _position_key(row.source),
        row.mount or "",
        row.source_path or "",
        row.helper or "",
        row.selection or "",
    )


def _validate_inventory_rows(
    rows: tuple[RouteInventoryRow, ...], *, mount_selection: bool
) -> None:
    for row in rows:
        if mount_selection:
            if row.selection is None:
                raise InspectionError("mount-selection row has no status")
        elif row.selection is not None:
            raise InspectionError("normal route inventory row has a selection status")
        if row.selection == "excluded" and row.kind != "route":
            raise InspectionError(f"live {row.kind} row is marked excluded")
        if row.selection == "included" and row.mount is None:
            raise InspectionError(f"included {row.kind} row has no mount")

        declaration = row.declaration
        if row.kind == "layout":
            if declaration is not None:
                raise InspectionError("layout row has declaration evidence")
            if row.methods:
                raise InspectionError("layout row has methods")
            if row.helper is not None:
                raise InspectionError("layout row has a helper")
            continue

        if declaration is None:
            raise InspectionError(f"{row.kind} row has no declaration")

        implementation = declaration.implementation
        if row.kind == "route":
            if row.selection != "excluded":
                raise InspectionError("route candidate row is not excluded")
            if row.methods:
                raise InspectionError("excluded route candidate has methods")
            if row.helper is not None:
                raise InspectionError("excluded route candidate has a helper")
            if implementation is not None:
                raise InspectionError("excluded route candidate has implementation")
            continue

        if implementation is None:
            raise InspectionError(f"{row.kind} row has no implementation")
        if implementation.kind != row.kind:
            raise InspectionError(
                f"{row.kind} row has {implementation.kind} implementation"
            )


def _occurrence_rows(
    graph: RouteGraph, helper_plan: _URLHelperPlan | None
) -> tuple[RouteInventoryRow, ...]:
    rows = [
        *_ordinary_layout_rows(graph),
        *_mounted_layout_rows(graph),
        *_endpoint_rows(graph, helper_plan),
    ]
    return tuple(sorted(rows, key=_row_key))


def inventory_rows(
    graph: RouteGraph, helper_plan: _URLHelperPlan
) -> tuple[RouteInventoryRow, ...]:
    """Project one canonical graph and helper plan into immutable inventory rows."""
    rows = _occurrence_rows(graph, helper_plan)
    _validate_inventory_rows(rows, mount_selection=False)
    return rows


def _mount_candidate_key(
    owner: SourcePosition,
    mount: str,
    source_path: str,
    source: SourcePosition,
) -> tuple[tuple[str, int, int], str, str, tuple[str, int, int]]:
    return (_position_key(owner), mount, source_path, _position_key(source))


def _reconcile_mount_candidates(
    rows: tuple[RouteInventoryRow, ...],
    mount: str,
    graph: RouteGraph,
) -> None:
    candidate_states: dict[
        tuple[tuple[str, int, int], str, str, tuple[str, int, int]], bool
    ] = {}
    for candidate in graph.mounted_candidates:
        if candidate.mount != mount:
            continue
        key = _mount_candidate_key(
            candidate.owner,
            candidate.mount,
            candidate.source_path,
            candidate.source_route,
        )
        if key in candidate_states:
            raise InspectionError(
                f"mounted source {mount!r} has duplicate candidate evidence"
            )
        candidate_states[key] = candidate.included

    live_keys = {
        _mount_candidate_key(row.owner, mount, row.source_path, row.source)
        for row in rows
        if row.mount == mount
        and row.kind in {"page", "fragment", "action"}
        and row.source_path is not None
    }
    included_keys = {key for key, included in candidate_states.items() if included}

    missing = included_keys - live_keys
    if missing:
        raise InspectionError(
            f"mounted source {mount!r} included candidate has no live endpoint"
        )
    extra = live_keys - included_keys
    if extra:
        raise InspectionError(
            f"mounted source {mount!r} live endpoint has no included candidate"
        )


def filter_mount(
    rows: tuple[RouteInventoryRow, ...],
    mount: str | None,
    *,
    graph: RouteGraph,
) -> tuple[RouteInventoryRow, ...]:
    graph = _require_route_graph(graph)
    _validate_inventory_rows(rows, mount_selection=False)
    if mount is None:
        return rows
    selected = [
        replace(row, selection="included") for row in rows if row.mount == mount
    ]
    _reconcile_mount_candidates(rows, mount, graph)
    inbound = _inbound_destinations(graph)
    for candidate in graph.mounted_candidates:
        if candidate.mount != mount or candidate.included:
            continue
        selected.append(
            RouteInventoryRow(
                "route",
                (),
                candidate.final_path,
                _parameters(candidate.final_path),
                candidate.source_route,
                candidate.owner,
                candidate.mount,
                candidate.source_path,
                None,
                "excluded",
                _candidate_declaration_evidence(candidate, inbound),
            )
        )
    result = tuple(sorted(selected, key=_row_key))
    _validate_inventory_rows(result, mount_selection=True)
    return result


def _position_json(position: SourcePosition) -> dict[str, object]:
    return {
        "path": position.path.as_posix(),
        "line": position.line,
        "column": position.column,
    }


def _compact_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"))


def _template_json(template: TemplateSource) -> dict[str, object]:
    return {
        "name": template.environment_name,
        "declaration": (
            None
            if template.declaration is None
            else _position_json(template.declaration)
        ),
        "source": _position_json(template.source),
    }


def _layout_json(layout: LayoutSource) -> dict[str, object]:
    return {
        "source": _position_json(layout.source),
        "template": _template_json(layout.template),
    }


def _destination_json(destination: DestinationSource) -> dict[str, object]:
    return {
        "name": destination.name,
        "target": destination.target_path,
        "trail_key": destination.trail_key,
        "source": _position_json(destination.source),
    }


def _inbound_destination_json(
    destination: _InboundDestinationEvidence,
) -> dict[str, object]:
    return {
        "source_route": destination.source_route,
        "name": destination.name,
        "trail_key": destination.trail_key,
        "source": _position_json(destination.source),
    }


def _request_data_json(value: _RequestDataEvidence) -> dict[str, object]:
    return {
        "kind": value.kind,
        "source": _position_json(value.source),
    }


def _implementation_json(value: _ImplementationEvidence) -> dict[str, object]:
    return {
        "kind": value.kind,
        "handler": {
            "module": value.handler.module,
            "symbol": value.handler.symbol,
            "binding": value.handler.binding,
            "source": _position_json(value.handler.source),
        },
        "declaration": _position_json(value.declaration),
        "template": None if value.template is None else _template_json(value.template),
        "request_data": (
            None
            if value.request_data is None
            else _request_data_json(value.request_data)
        ),
    }


def _declaration_json(value: _RouteDeclarationEvidence) -> dict[str, object]:
    nav: dict[str, object] | None = None
    if value.nav is not None:
        nav = {
            "label": value.nav.value.label,
            "key": value.nav.value.key,
            "source": _position_json(value.nav.source),
        }
    mount: dict[str, object] | None = None
    if value.mount is not None:
        mount = {
            "identity": value.mount.identity,
            "owner": _position_json(value.mount.owner),
            "source_path": value.mount.source_path,
        }
    return {
        "source": _position_json(value.source),
        "kind": value.kind,
        "name": value.name,
        "title": value.title,
        "labels": [
            {
                "key": label.key,
                "value": label.value,
                "source": _position_json(label.source),
            }
            for label in value.labels
        ],
        "nav": nav,
        "trail_keys": list(value.trail_keys),
        "destinations": [
            _destination_json(destination) for destination in value.destinations
        ],
        "inbound_destinations": [
            _inbound_destination_json(destination)
            for destination in value.inbound_destinations
        ],
        "mount": mount,
        "implementation": (
            None
            if value.implementation is None
            else _implementation_json(value.implementation)
        ),
    }


def _error_render_json(value: _ErrorRenderEvidence) -> dict[str, object]:
    return {
        "page_template": (
            None if value.page_template is None else _template_json(value.page_template)
        ),
        "fragment_template": (
            None
            if value.fragment_template is None
            else _template_json(value.fragment_template)
        ),
        "root_layouts": [_layout_json(layout) for layout in value.root_layouts],
    }


def _template_text(template: TemplateSource | None) -> str:
    if template is None:
        return "-"
    declaration = (
        "-" if template.declaration is None else _position_text(template.declaration)
    )
    return (
        f"{template.environment_name}@{declaration}@{_position_text(template.source)}"
    )


def _layout_text(layout: LayoutSource) -> str:
    return (
        f"{layout.template.environment_name}@{_position_text(layout.source)}@"
        f"{_position_text(layout.template.source)}"
    )


def _nav_text(nav: RouteNavSource | None) -> str:
    if nav is None:
        return "-"
    if nav.value.label is not None:
        return f"label={_compact_json(nav.value.label)}"
    if nav.value.key is not None:
        return f"key={_compact_json(nav.value.key)}"
    raise InspectionError("route navigation has neither label nor key")


def _declaration_display_values(
    declaration: _RouteDeclarationEvidence | None,
) -> tuple[str, ...]:
    if declaration is None:
        return ("-",) * 9
    labels = (
        "-"
        if not declaration.labels
        else _compact_json({label.key: label.value for label in declaration.labels})
    )
    destinations = (
        "-"
        if not declaration.destinations
        else _compact_json(
            [_destination_json(destination) for destination in declaration.destinations]
        )
    )
    inbound = (
        "-"
        if not declaration.inbound_destinations
        else _compact_json(
            [
                _inbound_destination_json(destination)
                for destination in declaration.inbound_destinations
            ]
        )
    )
    implementation = (
        "-"
        if declaration.implementation is None
        else _compact_json(_implementation_json(declaration.implementation))
    )
    return (
        declaration.kind,
        "-" if declaration.name is None else _compact_json(declaration.name),
        "-" if declaration.title is None else _compact_json(declaration.title),
        labels,
        _nav_text(declaration.nav),
        ",".join(declaration.trail_keys) or "-",
        destinations,
        inbound,
        implementation,
    )


def _display_values(
    row: RouteInventoryRow, *, mount_selection: bool
) -> tuple[str, ...]:
    owner = "-" if _same_position(row.source, row.owner) else _position_text(row.owner)
    values = (
        row.kind,
        ",".join(row.methods) or "-",
        row.path,
        ",".join(row.parameters) or "-",
        _position_text(row.source),
        owner,
        row.mount or "-",
        row.source_path or "-",
        *_declaration_display_values(row.declaration),
        row.helper or "-",
    )
    if mount_selection:
        if row.selection is None:
            raise InspectionError("mount-selection row has no status")
        return (*values, row.selection)
    if row.selection is not None:
        raise InspectionError("normal route inventory row has a selection status")
    return values


def render_text(
    rows: tuple[RouteInventoryRow, ...],
    *,
    error_render: _ErrorRenderEvidence,
    mount_selection: bool = False,
) -> bytes:
    """Render the exact deterministic ASCII table payload."""
    error_render = _require_error_render(error_render)
    _validate_inventory_rows(rows, mount_selection=mount_selection)
    header = (*_HEADER, "STATUS") if mount_selection else _HEADER
    values = [
        header,
        *(_display_values(row, mount_selection=mount_selection) for row in rows),
    ]
    widths = tuple(
        max(len(row[index]) for row in values) for index in range(len(header))
    )
    lines = [
        "  ".join(
            value.ljust(widths[index]) if index < len(widths) - 1 else value
            for index, value in enumerate(row)
        )
        for row in values
    ]
    layouts = (
        "[" + " > ".join(_layout_text(item) for item in error_render.root_layouts) + "]"
    )
    lines.append(
        f"ERROR_RENDER page={_template_text(error_render.page_template)} "
        f"fragment={_template_text(error_render.fragment_template)} "
        f"root_layouts={layouts}"
    )
    try:
        return ("\n".join(lines) + "\n").encode("ascii")
    except UnicodeEncodeError as error:
        raise InspectionError(f"route inventory table is not ASCII: {error}") from error


def render_json(
    rows: tuple[RouteInventoryRow, ...],
    *,
    error_render: _ErrorRenderEvidence,
    mount_selection: bool = False,
) -> bytes:
    """Render the exact enriched ``pyganini.routes.v1`` JSON payload."""
    error_render = _require_error_render(error_render)
    _validate_inventory_rows(rows, mount_selection=mount_selection)
    route_values: list[dict[str, object]] = []
    for row in rows:
        route_values.append(
            {
                "kind": row.kind,
                "methods": list(row.methods),
                "path": row.path,
                "parameters": list(row.parameters),
                "source": _position_json(row.source),
                "owner": _position_json(row.owner),
                "mount": row.mount,
                "source_path": row.source_path,
                "helper": row.helper,
                "selection": row.selection,
                "declaration": (
                    None
                    if row.declaration is None
                    else _declaration_json(row.declaration)
                ),
            }
        )
    payload: dict[str, object] = {
        "schema": "pyganini.routes.v1",
        "error_render": _error_render_json(error_render),
        "routes": route_values,
    }
    try:
        return (json.dumps(payload, ensure_ascii=True, indent=2) + "\n").encode("utf-8")
    except (TypeError, UnicodeEncodeError) as error:
        raise InspectionError(
            f"route inventory JSON encoding failed: {error}"
        ) from error


def render_payload(
    rows: tuple[RouteInventoryRow, ...],
    *,
    json_output: bool,
    graph: RouteGraph,
    mount_selection: bool = False,
) -> bytes:
    graph = _require_route_graph(graph)
    error_render = _error_render_evidence(graph)
    if json_output:
        return render_json(
            rows,
            error_render=error_render,
            mount_selection=mount_selection,
        )
    return render_text(
        rows,
        error_render=error_render,
        mount_selection=mount_selection,
    )


_RENDER_UNIT_HEADER = (
    "KIND",
    "METHOD",
    "ROUTE",
    "TEMPLATE",
    "TEMPLATE_SOURCE",
    "SOURCE",
    "OWNER",
    "MOUNT",
    "SOURCE_PATH",
    "LAYOUT_MODE",
    "EFFECTIVE_LAYOUTS",
)


def _render_unit_layout_key(
    layout: _RenderUnitLayout,
) -> tuple[object, ...]:
    return (
        _position_key(layout.source),
        *_render_unit_template_key(layout.template),
    )


def _render_unit_template_key(template: TemplateSource) -> tuple[object, ...]:
    return (
        template.environment_name,
        _position_key(template.source),
        template.template_root or "",
        (
            _position_key(template.declaration)
            if template.declaration is not None
            else ("", 0, 0)
        ),
    )


def _render_unit_row_key(row: _RenderUnitRow) -> tuple[object, ...]:
    return (
        _inspection_path_sort_key(row.route),
        _KIND_ORDER[row.kind],
        tuple(_METHOD_ORDER[method] for method in row.methods),
        _position_key(row.owner),
        _position_key(row.source),
        row.mount or "",
        row.source_path or "",
        *_render_unit_template_key(row.template),
        row.layout_mode,
        tuple(_render_unit_layout_key(layout) for layout in row.effective_layouts),
    )


def _render_unit_rows(graph: RouteGraph) -> tuple[_RenderUnitRow, ...]:
    rows: list[_RenderUnitRow] = []
    for endpoint in iter_endpoints(graph):
        template = endpoint.template
        if template is None:
            continue
        if endpoint.kind == "fragment":
            layout_mode: _RenderUnitLayoutMode = "none"
            effective_layouts: tuple[_RenderUnitLayout, ...] = ()
        else:
            layout_mode = "page" if endpoint.kind == "page" else "page-result"
            effective_layouts = tuple(
                _RenderUnitLayout(layout.source, layout.template)
                for layout in _selected_layouts(graph, endpoint)
            )
        rows.append(
            _RenderUnitRow(
                endpoint.kind,
                endpoint.methods,
                endpoint.path,
                template,
                endpoint.source,
                endpoint.owner or endpoint.source,
                endpoint.mount,
                endpoint.source_path,
                layout_mode,
                effective_layouts,
            )
        )
    return tuple(sorted(rows, key=_render_unit_row_key))


def _render_unit_layout_text(layout: _RenderUnitLayout) -> str:
    return (
        f"{layout.template.environment_name}@{_position_text(layout.source)}@"
        f"{_position_text(layout.template.source)}"
    )


def _render_unit_display_values(row: _RenderUnitRow) -> tuple[str, ...]:
    owner = "-" if _same_position(row.source, row.owner) else _position_text(row.owner)
    layouts = (
        "["
        + " > ".join(
            _render_unit_layout_text(layout) for layout in row.effective_layouts
        )
        + "]"
    )
    return (
        row.kind,
        ",".join(row.methods),
        row.route,
        row.template.environment_name,
        _position_text(row.template.source),
        _position_text(row.source),
        owner,
        row.mount or "-",
        row.source_path or "-",
        row.layout_mode,
        layouts,
    )


def _render_unit_text(rows: tuple[_RenderUnitRow, ...]) -> bytes:
    """Render the exact deterministic ASCII render-unit table payload."""
    values = [_RENDER_UNIT_HEADER, *(_render_unit_display_values(row) for row in rows)]
    widths = tuple(
        max(len(row[index]) for row in values)
        for index in range(len(_RENDER_UNIT_HEADER))
    )
    lines = [
        "  ".join(
            value.ljust(widths[index]) if index < len(widths) - 1 else value
            for index, value in enumerate(row)
        )
        for row in values
    ]
    try:
        return ("\n".join(lines) + "\n").encode("ascii")
    except UnicodeEncodeError as error:
        raise InspectionError(f"render-unit table is not ASCII: {error}") from error


def _render_unit_template_json(template: TemplateSource) -> dict[str, object]:
    return {
        "name": template.environment_name,
        "source": _position_json(template.source),
    }


def _render_unit_layout_json(layout: _RenderUnitLayout) -> dict[str, object]:
    return {
        "source": _position_json(layout.source),
        "template": _render_unit_template_json(layout.template),
    }


def _render_unit_json(rows: tuple[_RenderUnitRow, ...]) -> bytes:
    """Render the exact ``pyganini.render_units.v1`` JSON payload."""
    render_units: list[dict[str, object]] = []
    for row in rows:
        render_units.append(
            {
                "kind": row.kind,
                "methods": list(row.methods),
                "route": row.route,
                "template": _render_unit_template_json(row.template),
                "source": _position_json(row.source),
                "owner": _position_json(row.owner),
                "mount": row.mount,
                "source_path": row.source_path,
                "layout_mode": row.layout_mode,
                "effective_layouts": [
                    _render_unit_layout_json(layout) for layout in row.effective_layouts
                ],
            }
        )
    payload: dict[str, object] = {
        "schema": "pyganini.render_units.v1",
        "render_units": render_units,
    }
    try:
        return (json.dumps(payload, ensure_ascii=True, indent=2) + "\n").encode("utf-8")
    except (TypeError, UnicodeEncodeError) as error:
        raise InspectionError(f"render-unit JSON encoding failed: {error}") from error


def _render_unit_payload(
    rows: tuple[_RenderUnitRow, ...], *, json_output: bool
) -> bytes:
    return _render_unit_json(rows) if json_output else _render_unit_text(rows)


@dataclass(frozen=True, slots=True)
class _LayoutMapEntry:
    row: RouteInventoryRow
    layouts: tuple[SourcePosition, ...] = ()


@dataclass(slots=True)
class _LayoutMapNode:
    path: str
    segment: str
    layouts: list[_LayoutMapEntry] = field(
        default_factory=lambda: list[_LayoutMapEntry]()
    )
    endpoints: list[_LayoutMapEntry] = field(
        default_factory=lambda: list[_LayoutMapEntry]()
    )
    children: dict[str, _LayoutMapNode] = field(
        default_factory=lambda: dict[str, _LayoutMapNode]()
    )


def _row_identity(row: RouteInventoryRow) -> tuple[object, ...]:
    return (
        row.kind,
        row.methods,
        row.path,
        _position_key(row.source),
        _position_key(row.owner),
        row.mount,
        row.source_path,
    )


def _layout_row_for_source(
    graph: RouteGraph,
    layout_rows: tuple[RouteInventoryRow, ...],
    endpoint: Endpoint,
    layout: LayoutSource,
) -> RouteInventoryRow:
    layout_source = layout.source
    route_prefix = layout.route_prefix
    mounted_source = layout_source.path.parts[:2] == ("app", "mounts")
    if mounted_source:
        owner = endpoint.owner
        mount = endpoint.mount
        if owner is None or mount is None:
            raise InspectionError(
                "mounted layout "
                f"{layout_source.path.as_posix()!r} has no owner or mount"
            )
        owner_node = _owner_anchor(graph, owner)
        final_path = _join_route(owner_node.route_path, route_prefix)
        candidates = tuple(
            row
            for row in layout_rows
            if _position_key(row.source) == _position_key(layout_source)
            and _position_key(row.owner) == _position_key(owner)
            and row.mount == mount
            and row.source_path == route_prefix
            and row.path == final_path
        )
    else:
        candidates = tuple(
            row
            for row in layout_rows
            if _position_key(row.source) == _position_key(layout_source)
            and _position_key(row.owner) == _position_key(layout_source)
            and row.mount is None
            and row.source_path is None
            and row.path == route_prefix
        )
    if len(candidates) != 1:
        raise InspectionError(
            "layout selection does not reconcile to one effective occurrence: "
            f"{layout_source.path.as_posix()}"
        )
    return candidates[0]


def _layout_map_projection(
    graph: RouteGraph,
) -> tuple[
    _LayoutMapNode,
    dict[str, dict[tuple[object, ...], set[tuple[object, ...]]]],
    dict[tuple[object, ...], tuple[int, int]],
]:
    try:
        occurrences = _occurrence_rows(graph, None)
    except GenerationError as error:
        raise InspectionError(str(error)) from error

    layout_rows = tuple(row for row in occurrences if row.kind == "layout")
    endpoint_rows = tuple(row for row in occurrences if row.kind != "layout")
    endpoint_entries: dict[tuple[object, ...], _LayoutMapEntry] = {}
    predecessors: dict[str, dict[tuple[object, ...], set[tuple[object, ...]]]] = {}
    first_layout_order: dict[tuple[object, ...], tuple[int, int]] = {}

    for endpoint_index, endpoint in enumerate(iter_endpoints(graph)):
        row = _endpoint_row(endpoint, None)
        endpoint_key = _row_identity(row)
        if endpoint_key in endpoint_entries:
            raise InspectionError(f"duplicate endpoint occurrence at {endpoint.path!r}")
        resolved_layouts: list[RouteInventoryRow] = []
        if endpoint.kind != "fragment":
            try:
                selected = _selected_layouts(graph, endpoint)
                for layout_index, layout in enumerate(selected):
                    resolved = _layout_row_for_source(
                        graph, layout_rows, endpoint, layout
                    )
                    layout_key = _row_identity(resolved)
                    if layout_key in {_row_identity(item) for item in resolved_layouts}:
                        raise InspectionError(
                            "duplicate layout occurrence in chain for "
                            f"{endpoint.path!r}"
                        )
                    resolved_layouts.append(resolved)
                    first_layout_order.setdefault(
                        layout_key, (endpoint_index, layout_index)
                    )
            except GenerationError as error:
                raise InspectionError(str(error)) from error

        endpoint_entries[endpoint_key] = _LayoutMapEntry(
            row,
            tuple(item.source for item in resolved_layouts),
        )
        by_path: dict[str, list[tuple[object, ...]]] = {}
        for item in resolved_layouts:
            by_path.setdefault(item.path, []).append(_row_identity(item))
        for path, path_layouts in by_path.items():
            path_predecessors = predecessors.setdefault(path, {})
            for index, current in enumerate(path_layouts):
                current_predecessors = path_predecessors.setdefault(current, set())
                current_predecessors.update(path_layouts[:index])

    expected_endpoint_keys = {_row_identity(row) for row in endpoint_rows}
    if set(endpoint_entries) != expected_endpoint_keys:
        raise InspectionError("endpoint occurrences do not reconcile to the graph")

    root = _LayoutMapNode("/", "/")

    def node_for_path(path: str) -> _LayoutMapNode:
        if path == "/":
            return root
        current = root
        segments = path[1:].split("/")
        for index, segment in enumerate(segments):
            child_path = "/" + "/".join(segments[: index + 1])
            current = current.children.setdefault(
                segment, _LayoutMapNode(child_path, segment)
            )
        return current

    for row in layout_rows:
        node_for_path(row.path).layouts.append(_LayoutMapEntry(row))
    for entry in endpoint_entries.values():
        node_for_path(entry.row.path).endpoints.append(entry)
    return root, predecessors, first_layout_order


def _layout_fallback_key(row: RouteInventoryRow) -> tuple[object, ...]:
    return (
        _position_key(row.owner),
        _position_key(row.source),
        row.mount or "",
        row.source_path or "",
    )


def _ordered_layout_entries(
    entries: list[_LayoutMapEntry],
    predecessors: dict[tuple[object, ...], set[tuple[object, ...]]],
    first_layout_order: dict[tuple[object, ...], tuple[int, int]],
) -> list[_LayoutMapEntry]:
    by_key: dict[tuple[object, ...], _LayoutMapEntry] = {}
    for entry in entries:
        key = _row_identity(entry.row)
        if key in by_key:
            raise InspectionError(f"duplicate layout occurrence at {entry.row.path!r}")
        by_key[key] = entry

    remaining = set(by_key)
    ordered: list[_LayoutMapEntry] = []

    def sort_key(key: tuple[object, ...]) -> tuple[object, ...]:
        entry = by_key[key]
        first = first_layout_order.get(key)
        return (
            0 if first is not None else 1,
            first or (0, 0),
            _layout_fallback_key(entry.row),
        )

    while remaining:
        available = tuple(
            key for key in remaining if not (predecessors.get(key, set()) & remaining)
        )
        if not available:
            raise InspectionError(
                f"conflicting layout order at {entries[0].row.path!r}"
            )
        selected = min(available, key=sort_key)
        ordered.append(by_key[selected])
        remaining.remove(selected)
    return ordered


def _endpoint_entry_sort_key(entry: _LayoutMapEntry) -> tuple[object, ...]:
    row = entry.row
    return (
        _KIND_ORDER[row.kind],
        tuple(_METHOD_ORDER[method] for method in row.methods),
        _position_key(row.owner),
        _position_key(row.source),
        row.mount or "",
        row.source_path or "",
    )


def _layout_map_entry_text(entry: _LayoutMapEntry) -> str:
    row = entry.row
    owner = "-" if _same_position(row.source, row.owner) else _position_text(row.owner)
    mount = row.mount or "-"
    source_path = row.source_path or "-"
    if row.kind == "layout":
        return (
            f"layout {row.path} source={_position_text(row.source)} "
            f"owner={owner} mount={mount} source_path={source_path}"
        )

    chain = "[" + " > ".join(_position_text(source) for source in entry.layouts) + "]"
    suffix = ""
    if row.kind == "fragment":
        suffix = " (not wrapped)"
    elif row.kind == "action":
        suffix = " (valid Page results only)"
    return (
        f"{row.kind} {','.join(row.methods)} {row.path} "
        f"source={_position_text(row.source)} owner={owner} mount={mount} "
        f"source_path={source_path} layouts={chain}{suffix}"
    )


def _render_layout_map_contents(
    node: _LayoutMapNode,
    prefix: str,
    predecessors: dict[str, dict[tuple[object, ...], set[tuple[object, ...]]]],
    first_layout_order: dict[tuple[object, ...], tuple[int, int]],
    lines: list[str],
) -> None:
    path_predecessors = predecessors.get(node.path, {})
    entries = [
        *_ordered_layout_entries(
            node.layouts,
            path_predecessors,
            first_layout_order,
        ),
        *sorted(node.endpoints, key=_endpoint_entry_sort_key),
    ]
    children = tuple(
        sorted(
            node.children.values(),
            key=lambda child: _inspection_path_sort_key(child.path),
        )
    )
    total = len(entries) + len(children)
    index = 0
    for entry in entries:
        index += 1
        last = index == total
        connector = "`-- " if last else "|-- "
        lines.append(prefix + connector + _layout_map_entry_text(entry))
    for child in children:
        index += 1
        last = index == total
        connector = "`-- " if last else "|-- "
        lines.append(prefix + connector + child.segment + "/")
        child_prefix = prefix + ("    " if last else "|   ")
        _render_layout_map_contents(
            child,
            child_prefix,
            predecessors,
            first_layout_order,
            lines,
        )


def render_layout_map(graph: RouteGraph) -> bytes:
    """Render the complete source-only ASCII layout map."""
    root, predecessors, first_layout_order = _layout_map_projection(graph)
    lines = ["LAYOUT MAP", "/"]
    _render_layout_map_contents(
        root,
        "",
        predecessors,
        first_layout_order,
        lines,
    )
    lines.extend(
        [
            "",
            "RULES",
            "  Page results with a declared endpoint template use the displayed "
            "layout chain.",
            "  Fragment results are not layout-wrapped.",
            "  Direct Response results bypass templates and layouts.",
        ]
    )
    try:
        return ("\n".join(lines) + "\n").encode("ascii")
    except UnicodeEncodeError as error:
        raise InspectionError(f"layout map is not ASCII: {error}") from error
