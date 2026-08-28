# pyright: reportPrivateUsage=false

"""Render deterministic generated ASGI dispatch from the route graph."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath

from pyganini._generation import GeneratedArtifact
from pyganini._route_graph import (
    _METHOD_ORDER,
    Endpoint,
    HandlerReference,
    LayoutSource,
    MiddlewareSource,
    MountOwner,
    RouteGraph,
    RouteNode,
    SourcePosition,
    TemplateSource,
    _group_methods,
    _groups,
    _method_endpoints,
    _root_error_render_facts,
    _selected_layouts,
    iter_endpoints,
)
from pyganini.request_data import BodyCapture, FormCapture


@dataclass(frozen=True, slots=True)
class _Owner:
    node: RouteNode
    endpoints: tuple[Endpoint, ...]
    mounted: bool


def _local_path(node: RouteNode, endpoint: Endpoint) -> str:
    route_path = endpoint.node_path or node.route_path
    if endpoint.path == route_path:
        return "/"
    if route_path == "/":
        return endpoint.path
    return endpoint.path.removeprefix(route_path)


def _owners(graph: RouteGraph, endpoints: tuple[Endpoint, ...]) -> tuple[_Owner, ...]:
    anchors: dict[PurePosixPath, RouteNode] = {}
    for node in graph.nodes:
        position = node.owner
        if position is None or node.mount is not None:
            continue
        anchors.setdefault(position.path, node)
    grouped: dict[PurePosixPath, list[Endpoint]] = {}
    for endpoint in endpoints:
        owner = endpoint.owner or endpoint.source
        grouped.setdefault(owner.path, []).append(endpoint)
    owners: list[_Owner] = []
    for owner_path in sorted(grouped):
        owner_node = anchors.get(owner_path)
        if owner_node is None:
            raise ValueError(f"endpoint owner is absent from graph: {owner_path!r}")
        owned = tuple(grouped[owner_path])
        owners.append(
            _Owner(owner_node, owned, any(item.mount is not None for item in owned))
        )
    missing = set(grouped).difference(anchors)
    if missing:
        raise ValueError(f"endpoint owner is absent from graph: {sorted(missing)!r}")
    return tuple(owners)


def _surface_literal(node: RouteNode, endpoint: Endpoint) -> str:
    method = "GET" if endpoint.kind in {"page", "fragment"} else endpoint.methods[0]
    handler_source = endpoint.handler_source or endpoint.source
    values: tuple[object, ...] = (
        endpoint.kind,
        method,
        _local_path(node, endpoint),
        endpoint.path,
        endpoint.methods,
        endpoint.handler.module,
        endpoint.handler.symbol,
        endpoint.handler.binding,
        handler_source.path.as_posix(),
        handler_source.line,
        handler_source.column,
        None
        if endpoint.template is None
        else PurePosixPath(endpoint.template.environment_name).name,
        (endpoint.owner or endpoint.source).path.as_posix(),
        endpoint.mount,
        endpoint.source_path,
    )
    capture_literal: tuple[str, tuple[int, ...]] | None = None
    source_literal: tuple[str, int, int] | None = None
    if endpoint.request_data is not None:
        capture = endpoint.request_data
        capture_literal = (
            ("body", (capture.max_bytes,))
            if isinstance(capture, BodyCapture)
            else (
                "form",
                (
                    capture.max_files,
                    capture.max_fields,
                    capture.max_part_size,
                    capture.max_upload_size,
                ),
            )
        )
        source = endpoint.request_data_source
        if source is not None:
            source_literal = (source.path.as_posix(), source.line, source.column)
    values = (*values, capture_literal, source_literal)
    return ascii(values)


def _request_data_literal(endpoint: Endpoint) -> str:
    capture = endpoint.request_data
    if capture is None:
        return "None"
    if isinstance(capture, BodyCapture):
        return repr(("body", (capture.max_bytes,)))
    assert isinstance(capture, FormCapture)
    return repr(
        (
            "form",
            (
                capture.max_files,
                capture.max_fields,
                capture.max_part_size,
                capture.max_upload_size,
            ),
        )
    )


def _template_evidence_literal(template: TemplateSource) -> tuple[object, ...]:
    declaration = (
        None
        if template.declaration is None
        else (
            template.declaration.path.as_posix(),
            template.declaration.line,
            template.declaration.column,
        )
    )
    return (
        template.environment_name,
        template.source.path.as_posix(),
        template.source.line,
        template.source.column,
        template.template_root,
        declaration,
    )


def _template_literal(template: TemplateSource | None) -> str:
    if template is None:
        return "None"
    return ascii(_template_evidence_literal(template))


def _creator_literal(creator: HandlerReference | None) -> str:
    if creator is None:
        return "None"
    return ascii(
        (
            creator.module,
            creator.symbol,
            creator.binding,
            creator.source.path.as_posix(),
            creator.source.line,
            creator.source.column,
        )
    )


def _navigation_declaration_literal(
    node: RouteNode,
) -> tuple[str | None, str | None] | None:
    declaration = node.declaration
    if node.mount is not None:
        nav = node.source_nav
    elif declaration is None:
        nav = None
    else:
        nav = declaration.nav
    if nav is None:
        return None
    return nav.value.label, nav.value.key


def _destination_declarations_literal(
    node: RouteNode,
) -> tuple[tuple[str, str, str | None], ...]:
    declaration = node.declaration
    destinations = (
        node.source_destinations
        if node.mount is not None
        else ()
        if declaration is None
        else declaration.destinations
    )
    if not destinations:
        return ()
    return tuple(
        (destination.name, destination.target_path, destination.trail_key)
        for destination in destinations
    )


def _navigation_validation_lines(node: RouteNode) -> tuple[str, ...]:
    declaration = node.declaration
    expected_nav = _navigation_declaration_literal(node)
    expected_destinations = _destination_declarations_literal(node)
    if declaration is None or (expected_nav is None and not expected_destinations):
        return ()
    return (
        f"    expected_nav={expected_nav!a},",
        f"    expected_destinations={expected_destinations!a},",
    )


def _error_template_value(
    node: RouteNode, template: TemplateSource | None
) -> str | None:
    if template is None:
        return None
    return template.source.path.relative_to(node.source_directory).as_posix()


def _error_validation_lines(node: RouteNode) -> tuple[str, ...]:
    if node.error_page_template is None and node.error_fragment_template is None:
        return ()
    return (
        "    expected_error_page_template="
        f"{_error_template_value(node, node.error_page_template)!a},",
        "    expected_error_fragment_template="
        f"{_error_template_value(node, node.error_fragment_template)!a},",
    )


def _root_owner(graph: RouteGraph) -> RouteNode | None:
    return next(
        (
            node
            for node in graph.nodes
            if node.source_directory == PurePosixPath("app/routes")
            and node.mount is None
            and node.owner is not None
            and node.owner.path == PurePosixPath("app/routes/route.py")
        ),
        None,
    )


def _mount_selection_literals(
    mount_owner: MountOwner,
) -> tuple[
    tuple[
        str,
        tuple[str | None, str | None] | None,
        tuple[tuple[str, str, str | None], ...],
    ],
    ...,
]:
    selections = mount_owner.selections
    return tuple(
        (
            selection.path,
            None
            if selection.nav is None
            else (selection.nav.value.label, selection.nav.value.key),
            tuple(
                (destination.name, destination.target_path, destination.trail_key)
                for destination in selection.destinations
            ),
        )
        for selection in selections
    )


def _mount_has_navigation(graph: RouteGraph, owner: _Owner) -> bool:
    owner_path = owner.node.owner
    return any(
        node.owner == owner_path
        and node.mount is not None
        and node.declaration is not None
        and (node.declaration.nav is not None or node.declaration.destinations)
        for node in graph.nodes
    )


def _layout_literal(layout: LayoutSource) -> tuple[object, ...]:
    template = (
        layout.template.environment_name,
        layout.template.source.path.as_posix(),
        layout.template.source.line,
        layout.template.source.column,
        layout.template.template_root,
        None,
    )
    return (
        layout.source.path.as_posix(),
        layout.source.line,
        layout.source.column,
        layout.route_prefix,
        template,
    )


def _position_literal(position: SourcePosition) -> str:
    return f"{position.path.as_posix()}:{position.line}:{position.column}"


def _mount_evidence(endpoint: Endpoint) -> str:
    if endpoint.mount is None:
        return "none"
    return f"{endpoint.mount}:{endpoint.source_path or '/'}"


def _endpoint_evidence_literal(endpoint: Endpoint) -> tuple[object, ...]:
    owner = endpoint.owner or endpoint.source
    node_path = endpoint.node_path or endpoint.path
    source_path = endpoint.source_path or "/"
    mount_root = (
        node_path if source_path == "/" else node_path[: -len(source_path)] or "/"
    )
    return (
        endpoint.kind,
        endpoint.path,
        endpoint.methods,
        endpoint.source.path.as_posix(),
        endpoint.source.line,
        endpoint.source.column,
        endpoint.handler.module,
        endpoint.handler.symbol,
        endpoint.handler.binding,
        owner.path.as_posix(),
        endpoint.mount,
        endpoint.source_path,
        owner.line,
        owner.column,
        mount_root,
    )


def _marker_literal(
    endpoint: Endpoint,
    *,
    kind: str | None = None,
    surface: str | None = None,
    template: TemplateSource | None = None,
    route: str | None = None,
    handler: str | None = None,
) -> tuple[str, ...] | None:
    selected_template = endpoint.template if template is None else template
    if selected_template is None:
        return None
    declaration = selected_template.declaration
    owner = endpoint.owner or endpoint.source
    return (
        endpoint.kind if kind is None else kind,
        endpoint.kind if surface is None else surface,
        endpoint.path if route is None else route,
        selected_template.environment_name,
        _position_literal(selected_template.source),
        "none" if declaration is None else _position_literal(declaration),
        _position_literal(owner),
        (
            f"{endpoint.handler.module}:{endpoint.handler.symbol}"
            if handler is None
            else handler
        ),
        _mount_evidence(endpoint),
    )


def _rebased_layout_prefix(endpoint: Endpoint, layout: LayoutSource) -> str:
    if endpoint.mount is None or not layout.source.path.is_relative_to("app/mounts"):
        return layout.route_prefix
    node_path = endpoint.node_path or endpoint.path
    source_path = endpoint.source_path or "/"
    mount_root = (
        node_path if source_path == "/" else node_path[: -len(source_path)] or "/"
    )
    if layout.route_prefix == "/":
        return mount_root
    return (
        layout.route_prefix
        if mount_root == "/"
        else mount_root.rstrip("/") + layout.route_prefix
    )


def _layout_marker_literal(
    endpoint: Endpoint,
    layout: LayoutSource,
    *,
    surface: str,
) -> tuple[str, ...]:
    template = layout.template
    mount = (
        _mount_evidence(endpoint)
        if layout.source.path.is_relative_to("app/mounts")
        else "none"
    )
    return (
        "layout",
        surface,
        _rebased_layout_prefix(endpoint, layout),
        template.environment_name,
        _position_literal(template.source),
        "none",
        _position_literal(layout.source),
        "none",
        mount,
    )


def _embedded_fragment_literals(
    graph: RouteGraph,
    endpoint: Endpoint,
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    owner = endpoint.owner or endpoint.source
    selected: list[tuple[str, tuple[str, ...]]] = []
    for candidate in iter_endpoints(graph):
        if candidate.kind != "fragment" or candidate.template is None:
            continue
        if (candidate.owner or candidate.source).path != owner.path:
            continue
        if (
            candidate.mount != endpoint.mount
            or candidate.source_path != endpoint.source_path
        ):
            continue
        node = _source_node(graph, candidate)
        local_path = _local_path(node, candidate)
        marker = _marker_literal(
            candidate,
            kind="fragment",
            surface="embedded-fragment",
        )
        assert marker is not None
        selected.append((local_path, marker))
    return tuple(sorted(selected))


def _embedded_fragment_expectation_literals(
    graph: RouteGraph,
    endpoint: Endpoint,
) -> tuple[tuple[str, tuple[object, ...], tuple[object, ...]], ...]:
    owner = endpoint.owner or endpoint.source
    selected: list[tuple[str, tuple[object, ...], tuple[object, ...]]] = []
    for candidate in iter_endpoints(graph):
        if candidate.kind != "fragment" or candidate.template is None:
            continue
        if (candidate.owner or candidate.source).path != owner.path:
            continue
        if (
            candidate.mount != endpoint.mount
            or candidate.source_path != endpoint.source_path
        ):
            continue
        node = _source_node(graph, candidate)
        selected.append(
            (
                _local_path(node, candidate),
                _endpoint_evidence_literal(candidate),
                _template_evidence_literal(candidate.template),
            )
        )
    return tuple(sorted(selected))


def _root_error_marker_literal(
    root_owner: RouteNode | None,
    template: TemplateSource | None,
    *,
    kind: str,
    surface: str,
) -> tuple[str, ...] | None:
    if root_owner is None or root_owner.owner is None or template is None:
        return None
    declaration = template.declaration
    return (
        kind,
        surface,
        "/",
        template.environment_name,
        _position_literal(template.source),
        "none" if declaration is None else _position_literal(declaration),
        _position_literal(root_owner.owner),
        "route_error_handler",
        "none",
    )


def _root_layout_marker_literal(
    layout: LayoutSource,
    *,
    surface: str,
) -> tuple[str, ...]:
    return (
        "layout",
        surface,
        layout.route_prefix,
        layout.template.environment_name,
        _position_literal(layout.template.source),
        "none",
        _position_literal(layout.source),
        "none",
        "none",
    )


def _module_for_route_source(source: PurePosixPath) -> str:
    return ".".join((*source.parts[:-1], "route"))


def _source_groups(
    endpoints: tuple[Endpoint, ...],
) -> tuple[tuple[PurePosixPath, tuple[Endpoint, ...]], ...]:
    grouped: dict[PurePosixPath, list[Endpoint]] = {}
    for endpoint in endpoints:
        grouped.setdefault(endpoint.source.path, []).append(endpoint)
    return tuple(
        (source, tuple(grouped[source]))
        for source in sorted(grouped, key=lambda value: value.as_posix())
    )


def _source_node(graph: RouteGraph, endpoint: Endpoint) -> RouteNode:
    for node in graph.nodes:
        if (
            node.route_path == endpoint.node_path
            and node.source == endpoint.source
            and node.mount == endpoint.mount
        ):
            return node
    raise ValueError(f"endpoint source is absent from graph: {endpoint.source.path!r}")


def _module_for_middleware_source(source: PurePosixPath) -> str:
    return ".".join((*source.parts[:-1], "middleware"))


def _middleware_entries_literal(marker: MiddlewareSource) -> str:
    return repr(
        tuple((entry.source.line, entry.source.column) for entry in marker.entries)
    )


def _middleware_chain_literal(
    chain: tuple[MiddlewareSource, ...],
) -> tuple[tuple[str, int, int, str, tuple[tuple[int, int], ...]], ...]:
    return tuple(
        (
            marker.source.path.as_posix(),
            marker.source.line,
            marker.source.column,
            marker.route_prefix,
            tuple((entry.source.line, entry.source.column) for entry in marker.entries),
        )
        for marker in chain
    )


def _middleware_consumer_literal(
    endpoint: Endpoint,
    *,
    method: str,
    chain: tuple[MiddlewareSource, ...],
) -> tuple[
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
    tuple[tuple[str, int, int, str, tuple[tuple[int, int], ...]], ...],
]:
    owner = endpoint.owner or endpoint.source
    return (
        method,
        endpoint.kind,
        endpoint.path,
        endpoint.methods,
        owner.path.as_posix(),
        owner.line,
        owner.column,
        endpoint.mount or "<live>",
        endpoint.source.path.as_posix(),
        endpoint.source_path or "<live>",
        _middleware_chain_literal(chain),
    )


def _middleware_consumers_literal(
    graph: RouteGraph,
    endpoints: tuple[Endpoint, ...],
    marker: MiddlewareSource,
) -> str:
    consumers: list[
        tuple[
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
            tuple[tuple[str, int, int, str, tuple[tuple[int, int], ...]], ...],
        ]
    ] = []
    for endpoint in endpoints:
        chain = _source_node(graph, endpoint).middleware_chain
        if marker not in chain:
            continue
        method = "GET" if endpoint.kind in {"page", "fragment"} else endpoint.methods[0]
        consumers.append(
            _middleware_consumer_literal(endpoint, method=method, chain=chain)
        )
    return repr(tuple(consumers))


def _used_middleware_sources(
    graph: RouteGraph, endpoints: tuple[Endpoint, ...]
) -> tuple[MiddlewareSource, ...]:
    used: dict[PurePosixPath, MiddlewareSource] = {}
    for endpoint in endpoints:
        node = _source_node(graph, endpoint)
        for marker in node.middleware_chain:
            used.setdefault(marker.source.path, marker)
    return tuple(used.values())


def _navigation_facts(
    graph: RouteGraph,
    endpoint: Endpoint,
) -> tuple[tuple[tuple[object, ...], ...], tuple[str, ...]]:
    owner = _source_node(graph, endpoint)
    candidates = tuple(
        node
        for node in graph.nodes
        if node.declaration is not None
        and (
            node.route_path == "/"
            or node.route_path == owner.route_path
            or (
                node.route_path != "/"
                and owner.route_path.startswith(node.route_path + "/")
            )
        )
    )
    ordered = sorted(
        candidates,
        key=lambda node: (
            len(node.route_path.strip("/").split("/")) if node.route_path != "/" else 0,
            node.route_path,
            node.source.path.as_posix()
            if node.source is not None
            else node.owner.path.as_posix()
            if node.owner is not None
            else "",
        ),
    )
    facts: list[tuple[object, ...]] = []
    for node in ordered:
        declaration = node.declaration
        assert declaration is not None
        if declaration.nav is None:
            continue
        facts.append(
            (
                declaration.nav.value.label,
                declaration.nav.value.key,
                node.route_path,
                node.route_path == owner.route_path,
            )
        )
    accepted_keys = tuple(
        sorted(
            {
                destination.trail_key
                for node in graph.nodes
                if node.declaration is not None
                for destination in node.declaration.destinations
                if destination.target_path == owner.route_path
                and destination.trail_key is not None
            }
        )
    )
    return tuple(facts), accepted_keys


def _render(graph: RouteGraph) -> bytes:
    endpoints = tuple(iter_endpoints(graph))
    owners = _owners(graph, endpoints)
    root_owner = _root_owner(graph)
    root_error_owner = (
        None
        if root_owner is None or root_owner.owner is None
        else (
            root_owner.owner.path.as_posix(),
            root_owner.owner.line,
            root_owner.owner.column,
        )
    )
    error_page_template, error_fragment_template, error_root_layouts = (
        _root_error_render_facts(graph)
    )
    has_error_rendering = (
        error_page_template is not None or error_fragment_template is not None
    )
    has_mounted_owners = any(owner.mounted for owner in owners)
    has_creators = any(endpoint.creator is not None for endpoint in endpoints)
    groups = _groups(endpoints)
    middleware_sources = _used_middleware_sources(graph, endpoints)
    middleware_indexes = {
        marker.source.path: index for index, marker in enumerate(middleware_sources)
    }
    owner_indexes = {
        (endpoint.owner or endpoint.source).path: index
        for index, owner in enumerate(owners)
        for endpoint in owner.endpoints
    }
    endpoint_indexes = {id(endpoint): index for index, endpoint in enumerate(endpoints)}
    lines = [
        "# Code generated by pyganini; DO NOT EDIT.",
        '"""Generated Pyganini ASGI routing surface."""',
        "",
        "from jinja2 import Environment as _Environment",
        "from starlette.routing import Router as _Router",
        *(
            ("from typing import TYPE_CHECKING as _TYPE_CHECKING",)
            if has_mounted_owners
            else ()
        ),
        "",
        *(
            (
                "from pyganini import KitRouteDef as _KitRouteDef",
                "from pyganini import KitRouteMount as _KitRouteMount",
            )
            if has_mounted_owners
            else ()
        ),
        "from pyganini import RouteErrorHandler as _RouteErrorHandler",
        "from pyganini import TemplateInspectionMode as _TemplateInspectionMode",
        *(
            ("from pyganini._dispatch import DispatchError as _DispatchError",)
            if middleware_sources
            else ()
        ),
        "from pyganini._dispatch import build_endpoint as _build_endpoint",
        "from pyganini._dispatch import load_route as _load_route",
        *(
            ("from pyganini._dispatch import load_middleware as _load_middleware",)
            if middleware_sources
            else ()
        ),
        *(
            (
                "from pyganini._dispatch import "
                "middleware_construction_error as _middleware_construction_error",
            )
            if middleware_sources
            else ()
        ),
        *(
            ("from pyganini._dispatch import load_mount_owner as _load_mount_owner",)
            if has_mounted_owners
            else ()
        ),
        "from pyganini._dispatch import PathPriorityRoute as _Route",
        "from pyganini._dispatch import RouteErrorRouter as _ErrorRouter",
        "from pyganini._dispatch import prepare_environment as _prepare_environment",
        "from pyganini._dispatch import prepare_route_error_handler as "
        "_prepare_route_error_handler",
        "from pyganini._dispatch import prepare_template_inspection as "
        "_prepare_template_inspection",
        *(
            ("from pyganini._dispatch import select_creator as _select_creator",)
            if has_creators
            else ()
        ),
        "from pyganini._dispatch import select_handler as _select_handler",
        "",
    ]

    template_names = tuple(
        sorted(
            {
                template.environment_name
                for template in (
                    *(endpoint.template for endpoint in endpoints),
                    *(
                        layout.template
                        for endpoint in endpoints
                        for layout in _selected_layouts(graph, endpoint)
                    ),
                    *(
                        (
                            error_page_template,
                            error_fragment_template,
                            *(layout.template for layout in error_root_layouts),
                        )
                        if has_error_rendering
                        else ()
                    ),
                )
                if template is not None
            }
        )
    )
    lines.append(f"_template_names = {template_names!a}")
    if has_error_rendering:
        error_rendering = (
            _template_literal(error_page_template),
            _template_literal(error_fragment_template),
            tuple(_layout_literal(layout) for layout in error_root_layouts),
            _root_error_marker_literal(
                root_owner,
                error_page_template,
                kind="page",
                surface="root-error-page",
            ),
            _root_error_marker_literal(
                root_owner,
                error_fragment_template,
                kind="fragment",
                surface="root-error-fragment",
            ),
            tuple(
                _root_layout_marker_literal(layout, surface="root-error-page")
                for layout in error_root_layouts
            ),
        )
        lines.extend(
            [
                "_error_rendering = (",
                f"    {error_rendering[0]},",
                f"    {error_rendering[1]},",
                f"    {error_rendering[2]!a},",
                f"    {error_rendering[3]!a},",
                f"    {error_rendering[4]!a},",
                f"    {error_rendering[5]!a},",
                ")",
            ]
        )
    lines.append("")

    source_capture: dict[tuple[int, PurePosixPath], int] = {}
    source_groups: dict[
        int, tuple[tuple[PurePosixPath, tuple[Endpoint, ...]], ...]
    ] = {}
    for owner_index, owner in enumerate(owners):
        owner_path = (owner.endpoints[0].owner or owner.endpoints[0].source).path
        source_groups[owner_index] = _source_groups(owner.endpoints)
        if owner.mounted:
            mount = owner.endpoints[0].mount
            creator = owner.endpoints[0].creator
            assert mount is not None
            assert creator is not None
            mount_binding = next(
                item for item in graph.mount_owners if item.owner.path == owner_path
            )
            expected_bindings = tuple(
                (
                    item.source_path,
                    item.source_route.path.as_posix(),
                    item.final_path,
                )
                for item in graph.mounted_bindings
                if item.owner.path == owner_path
            )
            has_mount_navigation = _mount_has_navigation(graph, owner)
            expected_selections = (
                _mount_selection_literals(mount_binding)
                if has_mount_navigation
                else None
            )
            lines.extend(
                [
                    f"_route_{owner_index} = _load_mount_owner(",
                    f"    module={owner.node.module + '.route'!a},",
                    f"    source_path={owner_path.as_posix()!a},",
                    f"    expected_creator={_creator_literal(creator)},",
                    f"    expected_mount={mount!a},",
                    f"    expected_routes={mount_binding.selected_routes!r},",
                    f"    expected_bindings={expected_bindings!a},",
                    *(
                        (f"    expected_selections={expected_selections!a},",)
                        if expected_selections is not None
                        else ()
                    ),
                    *_error_validation_lines(owner.node),
                    ")",
                    "",
                ]
            )
            for source_path, source_endpoints in source_groups[owner_index]:
                capture_index = len(source_capture)
                source_capture[(owner_index, source_path)] = capture_index
                lines.extend(
                    [
                        f"_source_{capture_index} = _load_route(",
                        f"    module={_module_for_route_source(source_path)!a},",
                        f"    source_path={source_path.as_posix()!a},",
                        "    expected=(",
                    ]
                )
                source_node = _source_node(graph, source_endpoints[0])
                for endpoint in source_endpoints:
                    lines.append(f"        {_surface_literal(source_node, endpoint)},")
                lines.extend(
                    [
                        "    ),",
                        "    expected_creator=None,",
                        "    expected_template_root=None,",
                        *_navigation_validation_lines(source_node),
                        "    expected_kit=True,",
                        ")",
                        "",
                    ]
                )
        else:
            source = owner.node.source_directory / "route.py"
            lines.extend(
                [
                    f"_route_{owner_index} = _load_route(",
                    f"    module={owner.node.module + '.route'!a},",
                    f"    source_path={source.as_posix()!a},",
                    "    expected=(",
                ]
            )
            for endpoint in owner.endpoints:
                lines.append(f"        {_surface_literal(owner.node, endpoint)},")
            declaration = owner.node.declaration
            kit = None if declaration is None else declaration.kit
            expected_creator = _creator_literal(None if kit is None else kit.creator)
            expected_template_root = None if kit is None else kit.template_root
            lines.extend(
                [
                    "    ),",
                    f"    expected_creator={expected_creator},",
                    f"    expected_template_root={expected_template_root!r},",
                    *_navigation_validation_lines(owner.node),
                    *_error_validation_lines(owner.node),
                    ")",
                    "",
                ]
            )

    loaded_owner_paths = {
        owner.node.owner.path for owner in owners if owner.node.owner is not None
    }
    if (
        root_owner is not None
        and root_owner.owner is not None
        and root_owner.owner.path not in loaded_owner_paths
        and (
            root_owner.error_page_template is not None
            or root_owner.error_fragment_template is not None
        )
    ):
        lines.extend(
            [
                "_root_error_route = _load_route(",
                f"    module={root_owner.module + '.route'!a},",
                f"    source_path={root_owner.owner.path.as_posix()!a},",
                "    expected=(),",
                "    expected_creator=None,",
                "    expected_template_root=None,",
                *_navigation_validation_lines(root_owner),
                *_error_validation_lines(root_owner),
                ")",
                "",
            ]
        )

    if has_mounted_owners:
        lines.extend(
            [
                "if _TYPE_CHECKING:",
                "    def _check_mounted_kit[K](",
                "        owner: _KitRouteMount[K],",
                "        source: _KitRouteDef[K],",
                "    ) -> None:",
                "        ...",
            ]
        )
        for owner_index, owner in enumerate(owners):
            if not owner.mounted:
                continue
            owner_module = owner.node.module + ".route"
            lines.append("    # Owner/source generic type witness.")
            for source_path, _ in source_groups[owner_index]:
                capture_index = source_capture[(owner_index, source_path)]
                lines.extend(
                    [
                        f"    from {owner_module} import Route as "
                        f"_owner_route_{owner_index}",
                        f"    from {_module_for_route_source(source_path)} "
                        "import Route as "
                        f"_source_route_{capture_index}",
                        f"    _check_mounted_kit(_owner_route_{owner_index}, "
                        f"_source_route_{capture_index})",
                    ]
                )
        lines.append("")

    for endpoint_index, endpoint in enumerate(endpoints):
        owner_index = owner_indexes[(endpoint.owner or endpoint.source).path]
        node = owners[owner_index].node
        route_capture = (
            f"_source_{source_capture[(owner_index, endpoint.source.path)]}"
            if endpoint.mount is not None
            else f"_route_{owner_index}"
        )
        method = "GET" if endpoint.kind in {"page", "fragment"} else endpoint.methods[0]
        lines.extend(
            [
                f"_handler_{endpoint_index} = _select_handler(",
                f"    {route_capture},",
                f"    kind={endpoint.kind!a},",
                f"    method={method!a},",
                f"    local_path={_local_path(node, endpoint)!a},",
                ")",
                "",
            ]
        )
        if endpoint.creator is not None:
            lines.extend(
                [
                    f"_creator_{endpoint_index} = _select_creator(",
                    f"    _route_{owner_index},",
                    ")",
                    "",
                ]
            )

    for middleware_index, marker in enumerate(middleware_sources):
        lines.extend(
            [
                f"_middleware_{middleware_index} = _load_middleware(",
                f"    module={_module_for_middleware_source(marker.source.path)!a},",
                f"    source_path={marker.source.path.as_posix()!a},",
                f"    route_prefix={marker.route_prefix!a},",
                f"    expected_entries={_middleware_entries_literal(marker)},",
                f"    binding={(marker.source.line, marker.source.column)!a},",
                "    consumers="
                f"{_middleware_consumers_literal(graph, endpoints, marker)},",
                ")",
                "",
            ]
        )
    lines.extend(
        [
            "def create_router(",
            "    *,",
            "    environment: _Environment | None = None,",
            "    error_handler: _RouteErrorHandler | None = None,",
            "    template_inspection: _TemplateInspectionMode = "
            "_TemplateInspectionMode.OFF,",
            ") -> _Router:",
            "    selected_template_inspection = _prepare_template_inspection(",
            "        template_inspection,",
            "        source_path='app/_pyganini/asgi.py',",
            "    )",
            "    selected_environment = _prepare_environment(",
            "        environment,",
            "        template_names=_template_names,",
            "        source_path='app/_pyganini/asgi.py',",
            "    )",
            "    selected_error_handler = _prepare_route_error_handler(",
            "        error_handler,",
            "        template_inspection=selected_template_inspection,",
            *(
                (
                    "        environment=selected_environment,",
                    "        rendering=_error_rendering,",
                    f"        owner={root_error_owner!a},",
                )
                if has_error_rendering
                else ()
            ),
            "        source_path='app/_pyganini/asgi.py',",
            "    )",
        ]
    )

    for group_index, group in enumerate(groups):
        method_endpoints = _method_endpoints(group)
        lines.extend(
            [
                f"    endpoint_{group_index} = _build_endpoint(",
                "        handlers={",
            ]
        )
        for method in _METHOD_ORDER:
            method_endpoint = method_endpoints.get(method)
            if method_endpoint is None or method == "HEAD":
                continue
            lines.append(
                "            "
                f"{method!a}: _handler_{endpoint_indexes[id(method_endpoint)]},"
            )
        lines.append("        },")
        kit_methods = {
            method: method_endpoints[method]
            for method in _METHOD_ORDER
            if method in method_endpoints
            and method != "HEAD"
            and method_endpoints[method].creator is not None
        }
        if kit_methods:
            lines.append("        creators={")
            for method in _METHOD_ORDER:
                method_endpoint = kit_methods.get(method)
                if method_endpoint is None:
                    continue
                lines.append(
                    "            "
                    f"{method!a}: _creator_{endpoint_indexes[id(method_endpoint)]},"
                )
            lines.append("        },")
        request_data_methods = {
            method: method_endpoints[method]
            for method in _METHOD_ORDER
            if method in method_endpoints
            and method != "HEAD"
            and method_endpoints[method].request_data is not None
        }
        if request_data_methods:
            lines.append("        request_data={")
            for method in _METHOD_ORDER:
                method_endpoint = request_data_methods.get(method)
                if method_endpoint is None:
                    continue
                lines.append(
                    f"            {method!a}: {_request_data_literal(method_endpoint)},"
                )
            lines.append("        },")
        navigation_by_method: dict[str, tuple[tuple[object, ...], ...]] = {}
        trail_keys_by_method: dict[str, tuple[str, ...]] = {}
        for method in _METHOD_ORDER:
            method_endpoint = method_endpoints.get(method)
            if method_endpoint is None or method == "HEAD":
                continue
            navigation_facts, accepted_keys = _navigation_facts(graph, method_endpoint)
            if navigation_facts:
                navigation_by_method[method] = navigation_facts
            if accepted_keys:
                trail_keys_by_method[method] = accepted_keys
        if navigation_by_method:
            lines.append(f"        navigation={navigation_by_method!a},")
        if trail_keys_by_method:
            lines.append(f"        trail_keys={trail_keys_by_method!a},")
        lines.append("        evidence={")
        for method in _METHOD_ORDER:
            method_endpoint = method_endpoints.get(method)
            if method_endpoint is None or method == "HEAD":
                continue
            owner_index = owner_indexes[
                (method_endpoint.owner or method_endpoint.source).path
            ]
            node = owners[owner_index].node
            evidence = _endpoint_evidence_literal(method_endpoint)
            lines.append(f"            {method!a}: {evidence!a},")
        lines.append("        },")
        lines.append("        embedded_expectations={")
        for method in _METHOD_ORDER:
            method_endpoint = method_endpoints.get(method)
            if method_endpoint is None or method == "HEAD":
                continue
            lines.append(
                f"            {method!a}: "
                f"{_embedded_fragment_expectation_literals(graph, method_endpoint)!a},"
            )
        lines.append("        },")
        lines.append("        rendering={")
        for method in _METHOD_ORDER:
            method_endpoint = method_endpoints.get(method)
            if method_endpoint is None or method == "HEAD":
                continue
            layouts = tuple(
                _layout_literal(layout)
                for layout in _selected_layouts(graph, method_endpoint)
            )
            surface = (
                "page"
                if method_endpoint.kind == "page"
                else "fragment"
                if method_endpoint.kind == "fragment"
                else "action"
            )
            inspection_marker = _marker_literal(method_endpoint, surface=surface)
            layout_surface = (
                "action-page" if method_endpoint.kind == "action" else "page"
            )
            layout_markers = tuple(
                _layout_marker_literal(
                    method_endpoint,
                    layout,
                    surface=layout_surface,
                )
                for layout in _selected_layouts(graph, method_endpoint)
            )
            embedded_fragments = _embedded_fragment_literals(graph, method_endpoint)
            lines.append(
                f"            {method!a}: "
                f"({_template_literal(method_endpoint.template)}, {layouts!a}, "
                f"{inspection_marker!a}, {layout_markers!a}, "
                f"{embedded_fragments!a}),"
            )
        lines.extend(
            [
                "        },",
                f"        parameters={group.parameters!a},",
                "        environment=selected_environment,",
                "        template_inspection=selected_template_inspection,",
                *(
                    ("        error_rendering=_error_rendering,",)
                    if has_error_rendering
                    else ()
                ),
                "    )",
            ]
        )

    for group_index, group in enumerate(groups):
        methods = _group_methods(group)
        method_endpoints = _method_endpoints(group)
        error_layouts = {
            method: tuple(
                _layout_literal(layout)
                for layout in _selected_layouts(graph, method_endpoint)
            )
            for method in _METHOD_ORDER
            if method != "HEAD"
            and (method_endpoint := method_endpoints.get(method)) is not None
        }
        error_inspection = {
            method: (
                (
                    None
                    if error_page_template is None
                    else _marker_literal(
                        method_endpoint,
                        kind="page",
                        surface="matched-error-page",
                        template=error_page_template,
                        handler="route_error_handler",
                    )
                ),
                (
                    None
                    if error_fragment_template is None
                    else _marker_literal(
                        method_endpoint,
                        kind="fragment",
                        surface="matched-error-fragment",
                        template=error_fragment_template,
                        handler="route_error_handler",
                    )
                ),
                tuple(
                    _layout_marker_literal(
                        method_endpoint,
                        layout,
                        surface="matched-error-page",
                    )
                    for layout in _selected_layouts(graph, method_endpoint)
                ),
            )
            for method in _METHOD_ORDER
            if method != "HEAD"
            and (method_endpoint := method_endpoints.get(method)) is not None
        }
        error_evidence = {
            method: _endpoint_evidence_literal(method_endpoint)
            for method in _METHOD_ORDER
            if method != "HEAD"
            and (method_endpoint := method_endpoints.get(method)) is not None
        }
        error_templates_literal = (
            f"({_template_literal(error_page_template)}, "
            f"{_template_literal(error_fragment_template)})"
        )
        group_chain = _source_node(graph, group.endpoints[0]).middleware_chain
        if not group_chain:
            continue
        captures = tuple(
            f"_middleware_{middleware_indexes[marker.source.path]}"
            for marker in group_chain
        )
        chain_evidence = _middleware_chain_literal(group_chain)
        group_consumers = tuple(
            _middleware_consumer_literal(
                endpoint,
                method=method,
                chain=group_chain,
            )
            for method, endpoint in (
                (method, _method_endpoints(group).get(method))
                for method in methods
                if method != "HEAD"
            )
            if endpoint is not None
        )
        middleware_literal = ", ".join(f"*{capture}" for capture in captures) + (
            "," if len(captures) == 1 else ""
        )
        lines.extend(
            [
                "    try:",
                f"        _generated_route_{group_index} = _Route(",
                f"            {group.path!a},",
                f"            endpoint_{group_index},",
                f"            methods={list(methods)!a},",
                f"            middleware=({middleware_literal}),",
                "            error_handler=selected_error_handler,",
                *(
                    (f"            error_layouts={error_layouts!a},",)
                    if has_error_rendering
                    else ()
                ),
                *(
                    (f"            error_inspection={error_inspection!a},",)
                    if has_error_rendering
                    else ()
                ),
                f"            error_evidence={error_evidence!a},",
                f"            error_templates={error_templates_literal},",
                "        )",
                "    except BaseException as error:",
                "        if (",
                "            isinstance(error, _DispatchError)",
                "            and error.code == 'PYGANINI015'",
                "            and error.phase == 'render-configuration'",
                "        ):",
                "            raise",
                "        raise _middleware_construction_error(",
                f"            path={group.path!a},",
                f"            methods={methods!a},",
                f"            chain={chain_evidence!a},",
                f"            consumers={group_consumers!a},",
                "        ) from error",
            ]
        )
    lines.extend(["    _generated_routes: list[_Route] = ["])
    for group_index, group in enumerate(groups):
        methods = _group_methods(group)
        method_endpoints = _method_endpoints(group)
        error_layouts = {
            method: tuple(
                _layout_literal(layout)
                for layout in _selected_layouts(graph, method_endpoint)
            )
            for method in _METHOD_ORDER
            if method != "HEAD"
            and (method_endpoint := method_endpoints.get(method)) is not None
        }
        error_inspection = {
            method: (
                (
                    None
                    if error_page_template is None
                    else _marker_literal(
                        method_endpoint,
                        kind="page",
                        surface="matched-error-page",
                        template=error_page_template,
                        handler="route_error_handler",
                    )
                ),
                (
                    None
                    if error_fragment_template is None
                    else _marker_literal(
                        method_endpoint,
                        kind="fragment",
                        surface="matched-error-fragment",
                        template=error_fragment_template,
                        handler="route_error_handler",
                    )
                ),
                tuple(
                    _layout_marker_literal(
                        method_endpoint,
                        layout,
                        surface="matched-error-page",
                    )
                    for layout in _selected_layouts(graph, method_endpoint)
                ),
            )
            for method in _METHOD_ORDER
            if method != "HEAD"
            and (method_endpoint := method_endpoints.get(method)) is not None
        }
        error_evidence = {
            method: _endpoint_evidence_literal(method_endpoint)
            for method in _METHOD_ORDER
            if method != "HEAD"
            and (method_endpoint := method_endpoints.get(method)) is not None
        }
        error_templates_literal = (
            f"({_template_literal(error_page_template)}, "
            f"{_template_literal(error_fragment_template)})"
        )
        group_chain = _source_node(graph, group.endpoints[0]).middleware_chain
        if group_chain:
            lines.append(f"            _generated_route_{group_index},")
        else:
            lines.extend(
                [
                    "            _Route(",
                    f"                {group.path!a},",
                    f"                endpoint_{group_index},",
                    f"                methods={list(methods)!a},",
                    "                error_handler=selected_error_handler,",
                    *(
                        (f"                error_layouts={error_layouts!a},",)
                        if has_error_rendering
                        else ()
                    ),
                    *(
                        (f"                error_inspection={error_inspection!a},",)
                        if has_error_rendering
                        else ()
                    ),
                    f"                error_evidence={error_evidence!a},",
                    f"                error_templates={error_templates_literal},",
                    "            ),",
                ]
            )
    lines.extend(
        [
            "    ]",
            "    if selected_error_handler is None:",
            "        return _Router(",
            "            routes=_generated_routes,",
            "            redirect_slashes=False,",
            "        )",
            "    return _ErrorRouter(",
            "        routes=_generated_routes,",
            "        redirect_slashes=False,",
            "        error_handler=selected_error_handler,",
            "    )",
            "",
            "",
            "router: _Router = create_router()",
        ]
    )
    return ("\n".join(lines) + "\n").encode("ascii")


def dispatch_plan(graph: RouteGraph) -> tuple[GeneratedArtifact, ...]:
    """Return the generated ASGI artifact for one validated route graph."""
    return (GeneratedArtifact(PurePosixPath("app/_pyganini/asgi.py"), _render(graph)),)
